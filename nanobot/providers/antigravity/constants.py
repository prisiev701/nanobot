"""Constants for Antigravity OAuth provider."""

import platform
import random

# OAuth Client Credentials (from Antigravity desktop client, public)
CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
CLIENT_SECRET = "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"

# OAuth Endpoints
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# OAuth Scopes
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

# Antigravity API Endpoints (fallback order: daily → autopush → prod)
API_ENDPOINT_DAILY = "https://daily-cloudcode-pa.sandbox.googleapis.com"
API_ENDPOINT_AUTOPUSH = "https://autopush-cloudcode-pa.sandbox.googleapis.com"
API_ENDPOINT_PROD = "https://cloudcode-pa.googleapis.com"
DEFAULT_API_ENDPOINT = API_ENDPOINT_PROD

API_ENDPOINT_FALLBACKS = (
    API_ENDPOINT_DAILY,
    API_ENDPOINT_AUTOPUSH,
    API_ENDPOINT_PROD,
)

# API Paths
GENERATE_CONTENT_PATH = "/v1internal:generateContent"
STREAM_GENERATE_CONTENT_PATH = "/v1internal:streamGenerateContent"
LOAD_CODE_ASSIST_PATH = "/v1internal:loadCodeAssist"

# OAuth Callback
OAUTH_REDIRECT_PORT = 51121
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_REDIRECT_PORT}/oauth-callback"

# Antigravity version to impersonate
ANTIGRAVITY_VERSION = "1.15.8"

# Platform strings matching the reference implementation
_ANTIGRAVITY_PLATFORMS = ("windows/amd64", "darwin/arm64", "darwin/amd64")
_ANTIGRAVITY_API_CLIENTS = (
    "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "google-cloud-sdk vscode/1.96.0",
    "google-cloud-sdk vscode/1.95.0",
)

_PLATFORM_TAG = "MACOS" if platform.system() == "Darwin" else "WINDOWS"


def get_randomized_user_agent() -> str:
    """Short-format User-Agent matching Antigravity Manager behaviour."""
    plat = random.choice(_ANTIGRAVITY_PLATFORMS)  # noqa: S311
    return f"antigravity/{ANTIGRAVITY_VERSION} {plat}"


# DEFAULT_HEADERS — full header set used for loadCodeAssist (discovery) only.
# generateContent requests MUST NOT send X-Goog-Api-Client or Client-Metadata;
# see CONTENT_REQUEST_HEADERS below.
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Antigravity/{ANTIGRAVITY_VERSION} "
        f"Chrome/138.0.7204.235 Electron/37.3.1 Safari/537.36"
    ),
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": (
        f'{{"ideType":"ANTIGRAVITY","platform":"{_PLATFORM_TAG}","pluginType":"GEMINI"}}'
    ),
}


def get_content_request_headers() -> dict[str, str]:
    """Headers for generateContent / streamGenerateContent requests.

    Per the reference implementation (request.ts L1399-1401):
    > AM only sends User-Agent on content requests —
    > no X-Goog-Api-Client, no Client-Metadata header.
    """
    return {
        "User-Agent": get_randomized_user_agent(),
    }


# Available Models (antigravity-prefixed models use Antigravity endpoints)
MODELS = (
    # Antigravity models
    "claude-sonnet-4-5",
    "claude-sonnet-4-5-thinking",
    "claude-opus-4-6-thinking",
    "gemini-3-pro",  # variants: -low, -high
    "gemini-3-flash",  # variants: -minimal, -low, -medium, -high
    # Gemini CLI models (no antigravity- prefix, use prod endpoint)
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
)

# Default model
DEFAULT_MODEL = "claude-sonnet-4-5"

# Model aliases — map deprecated/shorthand names to current model names
MODEL_ALIASES: dict[str, str] = {
    "claude-opus-4-5": "claude-opus-4-6-thinking",
    "claude-opus-4-5-thinking": "claude-opus-4-6-thinking",
    "claude-opus-4-6": "claude-opus-4-6-thinking",
}

# Fallback project id when Antigravity does not return one (e.g. business accounts)
DEFAULT_PROJECT_ID = "rising-fact-p41fc"

# Credential storage
CREDENTIALS_DIR = ".nanobot/antigravity"
CREDENTIALS_FILE = "credentials.json"

# Retry / resilience
RETRYABLE_STATUS_CODES = frozenset({429, 500, 503})
# Status codes that should trigger endpoint fallback (try next endpoint, don't retry same)
FALLBACK_STATUS_CODES = frozenset({403, 404})
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt

# JSON Schema keys rejected by Gemini API
REJECTED_SCHEMA_KEYS = frozenset(
    {
        "const",
        "$ref",
        "$defs",
        "default",
        "examples",
        "title",
    }
)

# JSON Schema composition keys that need special handling
COMPOSITION_SCHEMA_KEYS = frozenset({"anyOf", "oneOf", "allOf"})
