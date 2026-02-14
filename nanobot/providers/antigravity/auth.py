"""OAuth PKCE authentication for Antigravity — multi-account support."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from dataclasses import asdict, dataclass, fields
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from nanobot.providers.antigravity.constants import (
    AUTH_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    CREDENTIALS_DIR,
    CREDENTIALS_FILE,
    OAUTH_REDIRECT_PORT,
    OAUTH_REDIRECT_URI,
    SCOPES,
    TOKEN_URL,
    USERINFO_URL,
)


@dataclass
class AntigravityCredentials:
    """Stored OAuth credentials for a single account."""

    access_token: str
    refresh_token: str
    expires_at: float  # Unix timestamp
    email: str = ""

    @property
    def is_expired(self) -> bool:
        """Check if access token is expired (with 5-minute buffer)."""
        return time.time() >= (self.expires_at - 300)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AntigravityCredentials:
        valid_keys = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


class AntigravityAuthManager:
    """Manages OAuth PKCE flow and token lifecycle for multiple accounts.

    Storage format (``credentials.json``)::

        {
            "active": "user@example.com",
            "accounts": {
                "user@example.com": { ... credential fields ... },
                "other@example.com": { ... credential fields ... }
            }
        }

    Backward-compatible: automatically migrates the legacy single-credential
    format (flat ``{access_token, ...}`` dict) on first load.
    """

    def __init__(self, credentials_dir: Path | None = None):
        self._creds_dir = credentials_dir or (Path.home() / CREDENTIALS_DIR)
        self._creds_file = self._creds_dir / CREDENTIALS_FILE
        self._accounts: dict[str, AntigravityCredentials] = {}
        self._active_email: str = ""
        self._load()

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def is_authenticated(self) -> bool:
        return self._active_email != "" and self._active_email in self._accounts

    @property
    def email(self) -> str:
        return self._active_email if self.is_authenticated else ""

    @property
    def accounts(self) -> list[str]:
        """Return list of all stored account emails."""
        return list(self._accounts.keys())

    @property
    def active_credentials(self) -> AntigravityCredentials | None:
        """Return credentials for the active account."""
        return self._accounts.get(self._active_email)

    # ── Persistence ────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load credentials from disk.  Handles both legacy and multi-account formats."""
        if not self._creds_file.exists():
            return

        try:
            data = json.loads(self._creds_file.read_text())
        except (json.JSONDecodeError, OSError):
            return

        if "accounts" in data:
            # Multi-account format
            self._active_email = data.get("active", "")
            for email, creds_data in data.get("accounts", {}).items():
                try:
                    self._accounts[email] = AntigravityCredentials.from_dict(creds_data)
                except (TypeError, KeyError):
                    continue
        elif "access_token" in data:
            # Legacy single-credential format — migrate
            try:
                creds = AntigravityCredentials.from_dict(data)
                email = creds.email or "unknown"
                self._accounts[email] = creds
                self._active_email = email
                # Persist in new format
                self._save()
            except (TypeError, KeyError):
                pass

    def _save(self) -> None:
        """Save all credentials to disk in multi-account format."""
        self._creds_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "active": self._active_email,
            "accounts": {email: creds.to_dict() for email, creds in self._accounts.items()},
        }
        self._creds_file.write_text(json.dumps(data, indent=2))
        self._creds_file.chmod(0o600)

    # ── Token management ───────────────────────────────────────────────

    async def get_valid_token(self) -> str:
        """Get a valid access token for the active account, refreshing if needed."""
        creds = self.active_credentials
        if not creds:
            raise RuntimeError("Not authenticated. Run 'nanobot auth login' first.")
        if creds.is_expired:
            await self._refresh()
        return creds.access_token

    async def _refresh(self) -> None:
        """Refresh the access token using refresh_token."""
        creds = self.active_credentials
        if not creds or not creds.refresh_token:
            raise RuntimeError("No refresh token. Run 'nanobot auth login' again.")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "refresh_token": creds.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()

        creds.access_token = data["access_token"]
        creds.expires_at = time.time() + data.get("expires_in", 3600)
        if "refresh_token" in data:
            creds.refresh_token = data["refresh_token"]
        self._save()

    # ── Account management ─────────────────────────────────────────────

    def switch(self, email: str) -> bool:
        """Switch the active account. Returns True if successful."""
        if email not in self._accounts:
            return False
        self._active_email = email
        self._save()
        return True

    # ── OAuth PKCE login flow ──────────────────────────────────────────

    def login(self) -> AntigravityCredentials:
        """Run OAuth PKCE flow.  Opens browser, waits for callback.

        This is a synchronous/blocking method suitable for CLI usage.
        The new account is added (or replaced if same email) and set as active.
        """
        # PKCE verifier + challenge
        code_verifier = secrets.token_urlsafe(64)
        challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode()

        # State for CSRF protection
        state = secrets.token_urlsafe(32)

        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{AUTH_URL}?{urlencode(params)}"

        # ── Local callback server ──────────────────────────────────────
        auth_code: str | None = None
        error: str | None = None

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                nonlocal auth_code, error
                query = parse_qs(urlparse(self.path).query)

                if "error" in query:
                    error = query["error"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<h1>Authentication failed</h1><p>You can close this tab.</p>"
                    )
                    return

                received_state = query.get("state", [None])[0]
                if received_state != state:
                    error = "State mismatch"
                    self.send_response(400)
                    self.end_headers()
                    return

                auth_code = query.get("code", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h1>Authentication successful!</h1>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                )

            def log_message(self, format, *args):  # noqa: A002
                pass  # suppress HTTP server logs

        server = HTTPServer(("localhost", OAUTH_REDIRECT_PORT), _Handler)
        server.timeout = 120  # 2-minute timeout

        webbrowser.open(auth_url)

        while auth_code is None and error is None:
            server.handle_request()
        server.server_close()

        if error:
            raise RuntimeError(f"OAuth error: {error}")
        if not auth_code:
            raise RuntimeError("No authorization code received")

        # Exchange code for tokens
        token_data = self._exchange_code(auth_code, code_verifier)

        # Fetch user email
        email = self._get_user_email(token_data["access_token"])

        creds = AntigravityCredentials(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            expires_at=time.time() + token_data.get("expires_in", 3600),
            email=email,
        )

        # Add/replace and set as active
        self._accounts[email] = creds
        self._active_email = email
        self._save()
        return creds

    # ── Helpers (synchronous, used during login) ───────────────────────

    def _exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        with httpx.Client() as client:
            response = client.post(
                TOKEN_URL,
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "code": code,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": OAUTH_REDIRECT_URI,
                },
            )
            response.raise_for_status()
            return response.json()

    def _get_user_email(self, access_token: str) -> str:
        """Fetch user email from Google userinfo endpoint."""
        try:
            with httpx.Client() as client:
                response = client.get(
                    USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                return response.json().get("email", "")
        except Exception:
            return ""

    def logout(self, email: str | None = None) -> None:
        """Remove stored credentials.

        Args:
            email: Specific account to remove. If None, removes the active account.
                   Pass ``"*"`` to remove all accounts.
        """
        if email == "*":
            # Remove all
            self._accounts.clear()
            self._active_email = ""
        elif email:
            # Remove specific
            self._accounts.pop(email, None)
            if self._active_email == email:
                # Switch to next available or empty
                self._active_email = next(iter(self._accounts), "")
        else:
            # Remove active
            if self._active_email:
                self._accounts.pop(self._active_email, None)
                self._active_email = next(iter(self._accounts), "")

        if self._accounts:
            self._save()
        elif self._creds_file.exists():
            self._creds_file.unlink()
