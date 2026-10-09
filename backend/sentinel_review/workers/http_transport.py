"""
HTTP transport layer for GitHub API calls.

Handles connection pooling, circuit breaker integration, and
request-level error handling.
"""

import logging
from typing import Any

import httpx

from .circuit_breaker import CircuitBreakerOpenError, github_circuit_breaker

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class HTTPTransport:
    """Thin HTTP client wrapper with connection pooling and circuit breaker support."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        token: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an authenticated request to the GitHub API.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /repos/owner/repo/pulls/42) or full URL
            token: Bearer token for authentication
            **kwargs: Additional arguments passed to httpx.Client.request

        Returns:
            httpx.Response object

        Raises:
            ConnectionError: If the circuit breaker is open or request fails
            httpx.HTTPStatusError: If the API returns an error status code
        """
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        url = path if path.startswith("http") else f"{GITHUB_API_BASE}{path}"

        try:
            resp = github_circuit_breaker.call(
                self._client.request, method, url, headers=headers, **kwargs
            )
        except CircuitBreakerOpenError as e:
            logger.error("Circuit breaker open for GitHub API: %s", e)
            raise ConnectionError(str(e)) from e

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

    def __enter__(self) -> "HTTPTransport":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
