"""
Rate-limit burst test — proves DRF throttle classes would return 429 under load.

Tests the throttle class directly with explicit rates, bypassing DRF's
api_settings cache which doesn't properly respond to @override_settings.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test.client import RequestFactory
from rest_framework.throttling import AnonRateThrottle

THROTTLED_PATH = "/api/v1/stats/"


@pytest.mark.django_db
class TestAnonRateLimiting:
    """Test AnonRateThrottle directly — rate limiting logic."""

    def _make_request(self):
        """Create a request with a unique IP to avoid cache conflicts with other tests."""
        request = RequestFactory().get(THROTTLED_PATH, REMOTE_ADDR="127.0.0.9")
        request.user = AnonymousUser()
        return request

    def test_first_requests_within_limit_succeed(self) -> None:
        """The first 3 requests within the 3/minute limit should be allowed."""
        throttle = AnonRateThrottle()
        throttle.rate = "3/minute"
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        request = self._make_request()
        for i in range(3):
            assert throttle.allow_request(
                request, None
            ), f"Request {i + 1} should be allowed within 3/minute limit"

    def test_request_beyond_limit_is_blocked(self) -> None:
        """The 4th request after exhausting 3/minute limit should be blocked."""
        throttle = AnonRateThrottle()
        throttle.rate = "3/minute"
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        request = self._make_request()
        for _ in range(3):
            throttle.allow_request(request, None)
        assert not throttle.allow_request(
            request, None
        ), "4th request should be blocked by throttle"

    def test_throttle_resets_after_duration(self) -> None:
        """After clearing the cache (simulating duration expiry), requests allowed again."""
        throttle = AnonRateThrottle()
        throttle.rate = "3/minute"
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        request = self._make_request()
        throttle.allow_request(request, None)
        throttle.allow_request(request, None)
        throttle.allow_request(request, None)
        # Clear Django cache AND local history to simulate duration expiry
        if throttle.key:
            cache.delete(throttle.key)
        throttle.history = []
        assert throttle.allow_request(
            request, None
        ), "After cache cleared (simulating duration expiry), throttle should allow requests"

    def test_wait_time_returned_on_block(self) -> None:
        """When blocked, throttle.wait() should return a positive number."""
        throttle = AnonRateThrottle()
        throttle.rate = "3/minute"
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        request = self._make_request()
        for _ in range(3):
            throttle.allow_request(request, None)
        assert not throttle.allow_request(request, None)
        wait_time = throttle.wait()
        assert wait_time is not None, "Wait time should be returned when throttled"
        assert wait_time > 0, "Wait time should be positive when throttled"

    def test_429_response_has_retry_after_header(self) -> None:
        """When API returns 429, the Retry-After header should be present.

        Uses a minimal DRF APIView subclass with a throttle that has a
        hardcoded 1/second rate (bypassing DRF's api_settings cache)
        and verifies the second request gets a 429 with Retry-After.

        Uses a unique IP to avoid cache conflicts with other tests.
        """
        from django.core.cache import cache
        from django.http import HttpResponse
        from rest_framework.throttling import AnonRateThrottle
        from rest_framework.views import APIView

        # Clear any cache entries left by other tests that could interfere
        cache.clear()

        class _BurstThrottle(AnonRateThrottle):
            """Throttle with hardcoded rate — no settings dependency."""

            rate = "1/second"

            def __init__(self):
                self.rate = "1/second"
                self.num_requests, self.duration = self.parse_rate(self.rate)

        class _TestView(APIView):
            throttle_classes = [_BurstThrottle]
            permission_classes = []

            def get(self, request):
                return HttpResponse("ok")

        view = _TestView.as_view()

        from django.test.client import RequestFactory

        # Use a unique IP to isolate from other tests' cache state
        unique_ip = "127.0.0.99"
        factory = RequestFactory()
        req1 = factory.get("/test/", REMOTE_ADDR=unique_ip)
        req1.user = AnonymousUser()
        resp1 = view(req1)

        req2 = factory.get("/test/", REMOTE_ADDR=unique_ip)
        req2.user = AnonymousUser()
        resp2 = view(req2)

        assert resp1.status_code == 200, f"First request should be 200, got {resp1.status_code}"
        assert resp2.status_code == 429, f"Second request should be 429, got {resp2.status_code}"
        # Retry-After should be a positive integer
        retry_after = resp2.headers.get("Retry-After")
        assert retry_after is not None, "429 response should include Retry-After header"
        try:
            seconds = int(retry_after)
            assert seconds > 0, f"Retry-After should be positive, got {seconds}"
        except (ValueError, TypeError):
            pytest.fail(f"Retry-After should be an integer, got {retry_after!r}")
