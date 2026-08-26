"""
API Key Authentication — Sentinel Review

Custom DRF authentication class that validates a Bearer token from the
Authorization header against the SENTINEL_API_KEY environment variable.

Usage:
    Set SENTINEL_API_KEY env var to enable. When unset, API key auth is
    skipped (backward compatible with session/basic auth).

In settings.py, add to DEFAULT_AUTHENTICATION_CLASSES:
    "sentinel_review.api.authentication.APIKeyAuthentication",
"""

import os
import secrets

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APIKeyAuthentication(BaseAuthentication):
    """Authenticate requests via Bearer token matching SENTINEL_API_KEY."""

    keyword = "Bearer"

    def authenticate(self, request) -> tuple[None, str] | None:
        api_key = os.environ.get("SENTINEL_API_KEY", "")
        if not api_key:
            return None  # No key configured — skip API key auth

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        token = parts[1]
        if not secrets.compare_digest(token, api_key):
            raise AuthenticationFailed("Invalid API key")

        # Return a dummy user tuple — the key itself is the credential
        return (None, token)

    def authenticate_header(self, request) -> str:
        return self.keyword
