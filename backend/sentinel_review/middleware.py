"""Custom security headers middleware.

Django's ``SecurityMiddleware`` already emits ``X-Content-Type-Options``
(``SECURE_CONTENT_TYPE_NOSNIFF``) and ``XFrameOptionsMiddleware`` emits
``X-Frame-Options``. This middleware adds the remaining headers so the
portfolio's API responses carry the same set as the other backends.
"""

from __future__ import annotations


class SecurityHeadersMiddleware:
    """Add security headers to every HTTP response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-XSS-Protection"] = "0"
        response["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )
        response["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none';"
        return response
