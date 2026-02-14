"""Antigravity provider — direct LLM access via Google's Unified Gateway API."""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from typing import Any

import httpx

from nanobot.providers.antigravity.auth import AntigravityAuthManager
from nanobot.providers.antigravity.constants import (
    API_ENDPOINT_FALLBACKS,
    DEFAULT_API_ENDPOINT,
    DEFAULT_HEADERS,
    DEFAULT_MODEL,
    DEFAULT_PROJECT_ID,
    FALLBACK_STATUS_CODES,
    GENERATE_CONTENT_PATH,
    LOAD_CODE_ASSIST_PATH,
    MAX_RETRIES,
    MODEL_ALIASES,
    RETRY_BASE_DELAY,
    RETRYABLE_STATUS_CODES,
    STREAM_GENERATE_CONTENT_PATH,
    get_content_request_headers,
)
from nanobot.providers.antigravity.transform import (
    messages_to_gemini,
    parse_gemini_response,
    parse_sse_chunk,
    tools_to_gemini,
)
from nanobot.providers.base import LLMProvider, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)


class AntigravityProvider(LLMProvider):
    """LLM provider using Google Antigravity OAuth for model access.

    Sends requests directly via httpx in Gemini API format — does NOT
    use LiteLLM.  Includes retry with exponential backoff and automatic
    endpoint failover (daily ↔ prod).
    """

    def __init__(
        self,
        auth_manager: AntigravityAuthManager | None = None,
        endpoint: str | None = None,
        default_model: str = DEFAULT_MODEL,
        project_id: str | None = None,
    ):
        super().__init__(
            api_key=None,
            api_base=endpoint or DEFAULT_API_ENDPOINT,
        )
        self._auth = auth_manager or AntigravityAuthManager()
        self._endpoint = endpoint or DEFAULT_API_ENDPOINT
        self._default_model = default_model
        self._provided_project_id = project_id
        self._project_id_cache: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None

    # ── Stable session ID ───────────────────────────────────────────────

    _session_id: str = ""

    @property
    def session_id(self) -> str:
        """Stable session ID for this provider instance (used in request payloads)."""
        if not self._session_id:
            self._session_id = f"-{uuid.uuid4()}"
        return self._session_id

    # ── HTTP client ────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=300.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Project discovery ──────────────────────────────────────────────

    async def _ensure_project_id(self) -> str:
        """Return project ID, discovering via loadCodeAssist if needed.

        The Antigravity API rejects synthetic project IDs — we must use
        the real ``cloudaicompanionProject`` returned by loadCodeAssist.
        Falls back to DEFAULT_PROJECT_ID on discovery failure.
        """
        if self._provided_project_id:
            return self._provided_project_id

        token = await self._auth.get_valid_token()
        email = self._auth.email

        if email in self._project_id_cache:
            return self._project_id_cache[email]

        client = await self._get_client()
        body = {
            "metadata": {
                "ideType": "ANTIGRAVITY",
                "platform": 2,
                "pluginType": "GEMINI",
            }
        }

        # Try endpoints in order (prod first for loadCodeAssist per reference)
        endpoints = [API_ENDPOINT_FALLBACKS[-1], *API_ENDPOINT_FALLBACKS[:-1]]
        for ep in endpoints:
            url = f"{ep}{LOAD_CODE_ASSIST_PATH}"
            try:
                resp = await client.post(
                    url,
                    json=body,
                    headers={
                        **DEFAULT_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    project = data.get("cloudaicompanionProject", "")
                    if project:
                        logger.info("Discovered project for %s: %s", email, project)
                        self._project_id_cache[email] = project
                        return project
            except Exception:
                logger.debug("loadCodeAssist failed on %s", ep, exc_info=True)

        # Fallback
        logger.warning(
            "Could not discover project via loadCodeAssist, using default: %s",
            DEFAULT_PROJECT_ID,
        )
        self._project_id_cache[email] = DEFAULT_PROJECT_ID
        return DEFAULT_PROJECT_ID

    # ── Retry / resilience ─────────────────────────────────────────────

    def _get_endpoints(self) -> list[str]:
        """Return ordered list of endpoints to try (primary + fallbacks)."""
        if self._endpoint in API_ENDPOINT_FALLBACKS:
            # Known endpoint — put it first, then the rest in order
            rest = [ep for ep in API_ENDPOINT_FALLBACKS if ep != self._endpoint]
            return [self._endpoint, *rest]
        else:
            # Custom endpoint — no fallback
            return [self._endpoint]

    @staticmethod
    def _get_retry_delay(response: httpx.Response, attempt: int) -> float:
        """Calculate retry delay: respect Retry-After header or use exponential backoff."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return RETRY_BASE_DELAY * (2**attempt)

    async def _request_with_retry(
        self,
        body: dict[str, Any],
        token: str,
    ) -> httpx.Response:
        """Send request with retry on transient errors and endpoint fallback.

        Strategy:
        - For each endpoint: retry up to MAX_RETRIES on 429/500/503 with backoff
        - On connection error: skip to next endpoint immediately
        - On non-retryable HTTP error: raise immediately
        """
        client = await self._get_client()
        headers = {
            **get_content_request_headers(),
            "Authorization": f"Bearer {token}",
        }
        endpoints = self._get_endpoints()
        last_error: Exception | None = None

        for endpoint in endpoints:
            url = f"{endpoint}{GENERATE_CONTENT_PATH}"

            for attempt in range(MAX_RETRIES):
                try:
                    logger.debug(
                        "Antigravity request: url=%s headers=%s body_keys=%s model=%s project=%s",
                        url,
                        {k: v[:50] if isinstance(v, str) else v for k, v in headers.items()},
                        list(body.keys()) if isinstance(body, dict) else "?",
                        body.get("model") if isinstance(body, dict) else "?",
                        body.get("project") if isinstance(body, dict) else "?",
                    )
                    response = await client.post(
                        url,
                        json=body,
                        headers=headers,
                    )

                    if response.status_code not in RETRYABLE_STATUS_CODES:
                        # 403/404 → try next endpoint (SERVICE_DISABLED, NOT_FOUND)
                        if response.status_code in FALLBACK_STATUS_CODES:
                            last_error = httpx.HTTPStatusError(
                                f"{response.status_code}",
                                request=response.request,
                                response=response,
                            )
                            logger.debug(
                                "Fallback-eligible %d on %s, trying next endpoint",
                                response.status_code,
                                endpoint,
                            )
                            break  # Next endpoint
                        response.raise_for_status()
                        return response

                    # Retryable status — backoff and retry
                    last_error = httpx.HTTPStatusError(
                        f"{response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    if attempt < MAX_RETRIES - 1:
                        delay = self._get_retry_delay(response, attempt)
                        logger.debug(
                            "Retry %d/%d after %.1fs (status %d, endpoint %s)",
                            attempt + 1,
                            MAX_RETRIES,
                            delay,
                            response.status_code,
                            endpoint,
                        )
                        await asyncio.sleep(delay)
                    else:
                        # Exhausted retries on this endpoint — try next
                        logger.debug(
                            "Exhausted retries on %s, trying fallback",
                            endpoint,
                        )
                        break

                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    last_error = e
                    logger.debug(
                        "Connection failed on %s: %s, trying fallback",
                        endpoint,
                        e,
                    )
                    break  # Next endpoint

        # All endpoints exhausted
        if last_error:
            raise last_error
        raise RuntimeError("All Antigravity endpoints exhausted")

    # ── LLMProvider interface ──────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        model = model or self._default_model

        try:
            token = await self._auth.get_valid_token()
            project_id = await self._ensure_project_id()
            body = self._build_request_body(
                messages,
                tools,
                model,
                max_tokens,
                temperature,
                project_id,
            )

            response = await self._request_with_retry(body, token)
            data = response.json()

            parsed = parse_gemini_response(data, model=model)
            return LLMResponse(
                content=parsed["content"],
                tool_calls=parsed["tool_calls"],
                finish_reason=parsed["finish_reason"],
                usage=parsed["usage"],
                reasoning_content=parsed["reasoning_content"],
            )

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except Exception:
                pass
            return LLMResponse(
                content=f"Antigravity API error {e.response.status_code}: {error_body}",
                finish_reason="error",
            )
        except Exception as e:
            return LLMResponse(
                content=f"Antigravity error: {e}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self._default_model

    # ── Streaming ──────────────────────────────────────────────────────

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        """Stream chat completion via SSE.

        Yields ``LLMStreamChunk`` objects as they arrive from the
        Antigravity streaming endpoint.
        """
        import json as _json

        model = model or self._default_model

        token = await self._auth.get_valid_token()
        project_id = await self._ensure_project_id()
        body = self._build_request_body(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            project_id,
        )

        client = await self._get_client()
        url = f"{self._endpoint}{STREAM_GENERATE_CONTENT_PATH}?alt=sse"
        headers = {
            **get_content_request_headers(),
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        }

        async with client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]  # strip "data: "
                if payload.strip() == "[DONE]":
                    break
                try:
                    event = _json.loads(payload)
                except _json.JSONDecodeError:
                    continue

                parsed = parse_sse_chunk(event)
                yield LLMStreamChunk(
                    content_delta=parsed["content_delta"],
                    tool_calls_delta=parsed["tool_calls_delta"],
                    reasoning_delta=parsed["reasoning_delta"],
                    finish_reason=parsed["finish_reason"],
                    usage=parsed["usage"],
                )

    # ── Model resolution ─────────────────────────────────────────────────

    # LiteLLM-style provider prefixes to strip (e.g. "anthropic/claude-opus-4-5")
    _LITELLM_PREFIXES = (
        "anthropic/",
        "openai/",
        "google/",
        "bedrock/",
        "vertex_ai/",
        "deepseek/",
        "groq/",
        "openrouter/",
    )

    @staticmethod
    def _resolve_model(model: str) -> str:
        """Resolve user-facing model name to Antigravity API model name.

        Transformations (matching the reference model-resolver):
        - Strip LiteLLM provider prefixes (``anthropic/``, ``openai/``, etc.)
        - Strip ``antigravity-`` prefix (the API body uses bare model names)
        - Apply model aliases (e.g. ``claude-opus-4-5`` → ``claude-opus-4-6-thinking``)
        - Strip ``-preview`` suffix
        - For ``gemini-3-pro`` without a tier suffix, append ``-low``

        Note: the ``antigravity-`` prefix is a registry/routing convention;
        the actual API expects bare names like ``claude-sonnet-4-5``.
        """
        resolved = model.strip()

        # Strip LiteLLM provider prefix (e.g. "anthropic/claude-opus-4-5" → "claude-opus-4-5")
        for prefix in AntigravityProvider._LITELLM_PREFIXES:
            if resolved.lower().startswith(prefix):
                resolved = resolved[len(prefix) :]
                break

        # Strip antigravity- prefix (API body doesn't use it)
        if resolved.lower().startswith("antigravity-"):
            resolved = resolved[len("antigravity-") :]

        # Strip -preview
        if resolved.lower().endswith("-preview"):
            resolved = resolved[: -len("-preview")]

        # Apply aliases (e.g. claude-opus-4-5 → claude-opus-4-6-thinking)
        resolved = MODEL_ALIASES.get(resolved, resolved)

        # Gemini 3 Pro auto-tier: if no tier suffix, default to -low
        tier_suffixes = ("-minimal", "-low", "-medium", "-high")
        if resolved.lower().startswith("gemini-3-pro") and not resolved.lower().endswith(
            tier_suffixes
        ):
            resolved = f"{resolved}-low"

        return resolved

    # ── Synthetic project ID ───────────────────────────────────────────

    @staticmethod
    def _generate_synthetic_project_id() -> str:
        """Generate a random synthetic project ID matching reference format."""
        adjectives = ("useful", "bright", "swift", "calm", "bold")
        nouns = ("fuze", "wave", "spark", "flow", "core")
        adj = random.choice(adjectives)  # noqa: S311
        noun = random.choice(nouns)  # noqa: S311
        suffix = uuid.uuid4().hex[:5]
        return f"{adj}-{noun}-{suffix}"

    # ── Request building ───────────────────────────────────────────────

    def _build_request_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
        project_id: str,
    ) -> dict[str, Any]:
        """Build Gemini-format request body wrapped for the Antigravity internal API.

        The Antigravity v1internal endpoint expects::

            {
                "project": "<project_id>",
                "model": "antigravity-<model_name>",
                "request": { contents, generationConfig, ... },
                "requestType": "agent",
                "userAgent": "antigravity"
            }
        """
        api_model = self._resolve_model(model)
        contents, system_instruction = messages_to_gemini(messages)

        request_payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        if system_instruction:
            request_payload["systemInstruction"] = system_instruction

        # Tool declarations
        gemini_tools = tools_to_gemini(tools)
        if gemini_tools:
            request_payload["tools"] = gemini_tools

        # Thinking model support
        if self._is_thinking_model(api_model):
            # Reference implementation uses minimum 8192 for high-reasoning models
            # We use a safe default of 8192, or half of max_tokens if larger
            thinking_budget = max(8192, max_tokens // 2)

            # Ensure maxOutputTokens is large enough to accommodate thinking + generation
            if max_tokens < thinking_budget + 4096:
                max_tokens = thinking_budget + 4096

            request_payload["generationConfig"]["thinkingConfig"] = {
                "includeThoughts": True,
                "thinkingBudget": thinking_budget,
            }
            request_payload["generationConfig"]["maxOutputTokens"] = max_tokens

        # Attach stable session ID (required by the API for signature caching)
        request_payload["sessionId"] = self.session_id

        return {
            "project": project_id,
            "model": api_model,
            "request": request_payload,
            "requestType": "agent",
            "userAgent": "antigravity",
            "requestId": f"agent-{uuid.uuid4()}",
        }

    @staticmethod
    def _is_thinking_model(model: str) -> bool:
        """Check if model requires thinking configuration."""
        return model.lower().endswith("-thinking")
