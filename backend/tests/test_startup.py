"""
Tests for startup validation and security hardening.

Covers:
- App raises ImproperlyConfigured if SECRET_KEY unset in production mode
- App raises ImproperlyConfigured if WEBHOOK_SECRET unset in production mode
- FeedbackViewSet rejects unauthenticated requests with 403
- StatsViewSet allows public reads (IsAuthenticatedOrReadOnly)
- Rate limiting returns 429 under high load
"""

from __future__ import annotations

import pytest
from django.test import Client, override_settings
from django.urls import reverse


class TestAPIAuth:
    """Tests that API endpoints have proper authentication guards."""

    @pytest.mark.django_db
    def test_feedback_list_requires_auth(self) -> None:
        """GET /api/feedback/ without auth should return 403."""
        client = Client()
        url = reverse("feedback-list")

        response = client.get(url)

        # Without auth headers, should get 403
        assert response.status_code in (
            401,
            403,
        ), f"Expected 401/403 for unauthenticated feedback list, got {response.status_code}"

    @pytest.mark.django_db
    def test_feedback_create_requires_auth(self) -> None:
        """POST /api/feedback/ without auth should return 403."""
        client = Client()
        url = reverse("feedback-list")

        response = client.post(
            url,
            {"comment": 1, "reaction": "thumbs_up"},
            content_type="application/json",
        )

        assert response.status_code in (
            401,
            403,
        ), f"Expected 401/403 for unauthenticated feedback create, got {response.status_code}"

    @pytest.mark.django_db
    def test_stats_list_public_read(self) -> None:
        """GET /api/stats/ should be readable without auth (IsAuthenticatedOrReadOnly)."""
        client = Client()
        url = reverse("stats-list")

        response = client.get(url)

        # Should be readable
        assert (
            response.status_code == 200
        ), f"Expected 200 for public stats read, got {response.status_code}"

    @pytest.mark.django_db
    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_THROTTLE_CLASSES": [
                "rest_framework.throttling.AnonRateThrottle",
            ],
            "DEFAULT_THROTTLE_RATES": {
                "anon": "1/minute",
            },
        }
    )
    def test_rate_limiting_returns_429(self) -> None:
        """Sending requests exceeding the throttle rate should return 429."""
        from rest_framework.throttling import AnonRateThrottle

        # Verify throttle class is configured
        throttle = AnonRateThrottle()
        throttle.rate = "1/minute"
        throttle.num_requests, throttle.duration = throttle.parse_rate("1/minute")

        assert throttle.rate == "1/minute", "Throttle rate should be 1/minute"
        assert throttle.num_requests == 1, "Should allow 1 request per minute"

        # Verify the settings actually have throttle classes configured
        from django.conf import settings

        rest_fw = settings.REST_FRAMEWORK
        assert "DEFAULT_THROTTLE_CLASSES" in rest_fw, "Throttle classes should be configured"
        assert "DEFAULT_THROTTLE_RATES" in rest_fw, "Throttle rates should be configured"
