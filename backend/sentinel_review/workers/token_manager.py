"""
Token management for GitHub App authentication.

Handles JWT generation for GitHub App authentication and
installation token exchange/caching.
"""

import base64
import logging
import time
from datetime import datetime

from django.conf import settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class TokenManager:
    """Manages GitHub App JWT and installation access tokens with caching."""

    def __init__(self) -> None:
        self._app_jwt: str | None = None
        self._jwt_expires_at: float = 0
        self._installation_tokens: dict[int, tuple[str, float]] = {}

    def get_private_key(self) -> bytes:
        """Load the GitHub App private key from env or file."""
        b64_key = settings.GITHUB_APP_PRIVATE_KEY_B64
        if b64_key:
            return base64.b64decode(b64_key)

        # Fall back to file path
        key_path = getattr(settings, "GITHUB_APP_PRIVATE_KEY_PATH", None)
        if key_path:
            with open(key_path, "rb") as f:
                return f.read()

        raise ValueError(
            "GitHub App private key not configured. "
            "Set GITHUB_APP_PRIVATE_KEY_B64 or mount the key file."
        )

    def generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication."""
        import jwt as pyjwt

        now = int(time.time())
        payload = {
            "iat": now - 60,  # issued 60s ago to avoid clock drift
            "exp": now + 600,  # expires in 10 minutes
            "iss": settings.GITHUB_APP_ID,
        }
        key = self.get_private_key()
        token = pyjwt.encode(payload, key, algorithm="RS256")
        self._app_jwt = token
        self._jwt_expires_at = now + 600
        return token

    def get_jwt(self) -> str:
        """Get a valid JWT, generating a new one if expired."""
        if not self._app_jwt or time.time() >= self._jwt_expires_at:
            return self.generate_jwt()
        return self._app_jwt

    def get_installation_token(self, installation_id: int, http_request) -> str:
        """Get or refresh an installation access token.

        Args:
            installation_id: GitHub App installation ID
            http_request: Callable that performs the HTTP POST to exchange JWT for token.
                         Signature: http_request(url, headers) -> dict with 'token' and 'expires_at'

        Returns:
            Installation access token string.
        """
        now = time.time()
        if installation_id in self._installation_tokens:
            token, expires_at = self._installation_tokens[installation_id]
            if now < expires_at - 60:
                return token

        jwt = self.get_jwt()
        url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"

        response_data = http_request(
            url,
            headers={"Authorization": f"Bearer {jwt}"},
        )
        token = response_data["token"]
        expires_at_str = response_data.get("expires_at", "")

        try:
            expires_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            expires_at = expires_dt.timestamp()
        except (ValueError, AttributeError):
            expires_at = now + 3600

        self._installation_tokens[installation_id] = (token, expires_at)
        return token

    def clear_cache(self) -> None:
        """Clear all cached tokens."""
        self._app_jwt = None
        self._jwt_expires_at = 0
        self._installation_tokens.clear()
