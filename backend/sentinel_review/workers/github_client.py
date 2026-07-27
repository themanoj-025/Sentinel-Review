"""
GitHub API client.

Handles JWT generation for GitHub App authentication,
installation token exchange, diff fetching, and comment posting.
"""

import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from django.conf import settings

from .circuit_breaker import CircuitBreakerOpenError, github_circuit_breaker

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class GitHubRepoContext:
    """Context information about a repository for review."""

    full_name: str
    default_branch: str | None = None
    has_contributing: bool = False
    has_linter_config: bool = False
    contributing_content: str | None = None
    linter_config_content: dict | None = None


class GitHubClient:
    """Client for interacting with the GitHub API as a GitHub App.

    Uses a single long-lived httpx.Client with connection pooling for
    performance. Tokens are cached and refreshed as needed.
    """

    def __init__(self):
        self._app_jwt: str | None = None
        self._jwt_expires_at: float = 0
        self._installation_tokens: dict[int, tuple[str, float]] = {}
        # Single shared httpx client with connection pooling
        self._client = httpx.Client(
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    def close(self):
        """Close the underlying httpx client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _get_private_key(self) -> bytes:
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

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication."""
        import jwt as pyjwt

        now = int(time.time())
        payload = {
            "iat": now - 60,  # issued 60s ago to avoid clock drift
            "exp": now + 600,  # expires in 10 minutes
            "iss": settings.GITHUB_APP_ID,
        }
        key = self._get_private_key()
        token = pyjwt.encode(payload, key, algorithm="RS256")
        self._app_jwt = token
        self._jwt_expires_at = now + 600
        return token

    def _get_jwt(self) -> str:
        """Get a valid JWT, generating a new one if expired."""
        if not self._app_jwt or time.time() >= self._jwt_expires_at:
            return self._generate_jwt()
        return self._app_jwt

    def _get_installation_token(self, installation_id: int) -> str:
        """Get or refresh an installation access token."""
        now = time.time()
        if installation_id in self._installation_tokens:
            token, expires_at = self._installation_tokens[installation_id]
            if now < expires_at - 60:  # Refresh if within 60 seconds of expiry
                return token

        jwt = self._get_jwt()
        url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"

        resp = self._client.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["token"]
        expires_at_str = data.get("expires_at", "")

        try:
            expires_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            expires_at = expires_dt.timestamp()
        except (ValueError, AttributeError):
            expires_at = now + 3600  # Default 1 hour

        self._installation_tokens[installation_id] = (token, expires_at)
        return token

    def _request(
        self,
        method: str,
        path: str,
        installation_id: int | None = None,
        **kwargs,
    ) -> httpx.Response:
        """Make an authenticated request to the GitHub API."""
        headers = kwargs.pop("headers", {})

        if installation_id:
            token = self._get_installation_token(installation_id)
            headers["Authorization"] = f"Bearer {token}"
        else:
            jwt = self._get_jwt()
            headers["Authorization"] = f"Bearer {jwt}"

        url = path if path.startswith("http") else f"{GITHUB_API_BASE}{path}"

        # Use circuit breaker to protect against GitHub API outages
        try:
            resp = github_circuit_breaker.call(
                self._client.request, method, url, headers=headers, **kwargs
            )
        except CircuitBreakerOpenError as e:
            logger.error("Circuit breaker open for GitHub API: %s", e)
            raise ConnectionError(str(e)) from e  # Convert to ConnectionError for caller handling

        if resp.status_code >= 400:
            logger.error(
                "GitHub API error: %s %s %s: %s",
                resp.status_code,
                method,
                path,
                resp.text[:500],
            )
        resp.raise_for_status()
        return resp

    def get_diff(self, installation_id: int, repo_full_name: str, pr_number: int) -> str:
        """Fetch the diff of a pull request."""
        path = f"/repos/{repo_full_name}/pulls/{pr_number}"
        resp = self._request(
            "GET",
            path,
            installation_id=installation_id,
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        return resp.text

    def get_file_content(
        self, installation_id: int, repo_full_name: str, file_path: str, ref: str
    ) -> str | None:
        """Fetch the full content of a file at a specific ref."""
        path = f"/repos/{repo_full_name}/contents/{file_path}?ref={ref}"
        try:
            resp = self._request("GET", path, installation_id=installation_id)
            data = resp.json()
            if data.get("encoding") == "base64":
                content = data.get("content", "")
                return base64.b64decode(content).decode("utf-8", errors="replace")
            return data.get("content", "")
        except (httpx.HTTPStatusError, KeyError, ValueError) as e:
            logger.warning("Failed to fetch file %s: %s", file_path, e)
            return None

    def get_repo_context(self, installation_id: int, repo_full_name: str) -> GitHubRepoContext:
        """Gather repository context (CONTRIBUTING.md, linter config)."""
        ctx = GitHubRepoContext(full_name=repo_full_name)

        # Get repo info
        try:
            resp = self._request("GET", f"/repos/{repo_full_name}", installation_id=installation_id)
            data = resp.json()
            ctx.default_branch = data.get("default_branch")
        except httpx.HTTPStatusError:
            pass

        # Check for CONTRIBUTING.md
        for path_candidate in ["CONTRIBUTING.md", "CONTRIBUTING", "CONTRIBUTING.adoc"]:
            try:
                content = self.get_file_content(
                    installation_id,
                    repo_full_name,
                    path_candidate,
                    ctx.default_branch or "main",
                )
                if content:
                    ctx.has_contributing = True
                    ctx.contributing_content = content[:5000]
                    break
            except httpx.HTTPStatusError:
                continue

        # Check for linter/config files
        linter_files = [
            ".eslintrc",
            ".eslintrc.json",
            ".eslintrc.js",
            ".eslintrc.yaml",
            "pyproject.toml",
            ".flake8",
            "setup.cfg",
            ".pylintrc",
            "tsconfig.json",
            ".prettierrc",
            ".prettierrc.json",
            "rustfmt.toml",
            "go.mod",
        ]
        for lf in linter_files:
            try:
                content = self.get_file_content(
                    installation_id,
                    repo_full_name,
                    lf,
                    ctx.default_branch or "main",
                )
                if content:
                    ctx.has_linter_config = True
                    if ctx.linter_config_content is None:
                        ctx.linter_config_content = {}
                    ctx.linter_config_content[lf] = content[:2000]
            except httpx.HTTPStatusError:
                continue

        return ctx

    def post_review(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
        comments: list[dict[str, Any]],
        review_body: str = "### 🔍 Sentinel Review\n\nAutomated review complete. See inline comments for details.",
    ) -> dict[str, Any]:
        """Post a review with inline comments to a pull request."""
        path = f"/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        payload = {
            "body": review_body,
            "event": "COMMENT",
            "comments": comments,
        }
        resp = self._request("POST", path, installation_id=installation_id, json=payload)
        result = resp.json()
        logger.info(
            "Posted review to %s#%d: %d comments (review_id=%s)",
            repo_full_name,
            pr_number,
            len(comments),
            result.get("id"),
        )
        return result

    def get_comment_reactions(
        self, installation_id: int, repo_full_name: str, comment_id: int
    ) -> list[dict]:
        """Get reactions for a specific review comment."""
        path = f"/repos/{repo_full_name}/pulls/comments/{comment_id}/reactions"
        try:
            resp = self._request("GET", path, installation_id=installation_id)
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            logger.warning("Failed to get reactions for comment %d: %s", comment_id, e)
            return []
