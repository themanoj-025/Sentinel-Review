"""
GitHub API client — thin facade.

Composes TokenManager (JWT/installation token caching) and
HTTPTransport (httpx connection pool + circuit breaker) into
a unified interface for GitHub API operations.
"""

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .http_transport import HTTPTransport
from .token_manager import TokenManager

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

    Thin facade that delegates auth to TokenManager and HTTP transport
    to HTTPTransport. Uses a single long-lived httpx.Client with connection
    pooling for performance.
    """

    def __init__(self) -> Any:
        self._token_manager = TokenManager()
        self._transport = HTTPTransport()

    def close(self) -> Any:
        """Close the underlying httpx client."""
        self._transport.close()

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *args) -> Any:
        self.close()

    def _request(
        self, method: str, path: str, installation_id: int | None = None, **kwargs
    ) -> httpx.Response:
        """Make an authenticated request using installation token or JWT."""
        if installation_id:
            token = self._token_manager.get_installation_token(
                installation_id,
                # Use the raw httpx client for token exchange to avoid
                # HTTPTransport's Authorization header injection overwriting the JWT
                lambda url, headers: self._transport._client.request(
                    "POST", url, headers=headers
                ).json(),
            )
        else:
            token = self._token_manager.get_jwt()

        return self._transport.request(method, path, token, **kwargs)

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
