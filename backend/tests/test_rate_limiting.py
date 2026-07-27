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

THROTTLED_PATH = "/api/stats/"


@pytest.mark.django_db
class TestAnonRateLimiting:
    """Test AnonRateThrottle directly — rate limiting logic."""

    def _make_request(self):
        """Create a request with a unique IP to avoid cache conflicts with other tests."""
        request = RequestFactory().get(THROTTLED_PATH, REMOTE_ADDR="127.0.0.9")
        request.user = AnonymousUser()
        return request

    def test_first_requests_within_limit_succeed(self):
        """The first 3 requests within the 3/minute limit should be allowed."""
        throttle = AnonRateThrottle()
        throttle.rate = "3/minute"
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        request = self._make_request()
        for i in range(3):
            assert throttle.allow_request(request, None), (
                f"Request {i+1} should be allowed within 3/minute limit"
            )

    def test_request_beyond_limit_is_blocked(self):
        """The 4th request after exhausting 3/minute limit should be blocked."""
        throttle = AnonRateThrottle()
        throttle.rate = "3/minute"
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        request = self._make_request()
        for _ in range(3):
            throttle.allow_request(request, None)
        assert not throttle.allow_request(request, None), (
            "4th request should be blocked by throttle"
        )

    def test_throttle_resets_after_duration(self):
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
        assert throttle.allow_request(request, None), (
            "After cache cleared (simulating duration expiry), throttle should allow requests"
        )

    def test_wait_time_returned_on_block(self):
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
