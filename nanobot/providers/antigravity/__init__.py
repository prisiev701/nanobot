"""Antigravity OAuth provider for accessing Google's Unified Gateway API."""

from nanobot.providers.antigravity.provider import AntigravityProvider
from nanobot.providers.antigravity.auth import AntigravityAuthManager

__all__ = ["AntigravityProvider", "AntigravityAuthManager"]
