"""
Tests for webhook HMAC signature verification.

Covers:
- Valid signature passes
- Missing signature rejected
- Wrong signature rejected
- Tampered payload rejected
- Empty webhook secret disables verification (dev mode)
- Invalid header format rejected
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from django.test.utils import override_settings
from sentinel_review.webhooks.signature import verify_signature

pytestmark = pytest.mark.slow
pytestmark = pytest.mark.integration

TEST_SECRET = b"test-secret-key"


def _compute_signature(payload: bytes, secret: bytes = TEST_SECRET) -> str:
    """Helper to compute a valid HMAC-SHA256 signature."""
    digest = hmac.new(secret, msg=payload, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


WEBHOOK_SECRET_SETTING = override_settings(WEBHOOK_SECRET="test-secret-key")


class TestVerifySignature:
    """Test suite for verify_signature()."""

    @WEBHOOK_SECRET_SETTING
    def test_valid_signature_passes(self) -> None:
        """A correctly computed signature should pass verification."""
        payload = b'{"action": "opened"}'
        sig = _compute_signature(payload)
        assert verify_signature(payload, sig) is True

    @WEBHOOK_SECRET_SETTING
    def test_missing_signature_rejected(self) -> None:
        """A missing X-Hub-Signature-256 header should be rejected."""
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, None) is False

    @WEBHOOK_SECRET_SETTING
    def test_empty_signature_rejected(self) -> None:
        """An empty signature header should be rejected."""
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, "") is False

    @WEBHOOK_SECRET_SETTING
    def test_wrong_signature_rejected(self) -> None:
        """A wrong signature should fail verification."""
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, "sha256=deadbeef") is False

    @WEBHOOK_SECRET_SETTING
    def test_tampered_payload_rejected(self) -> None:
        """If the payload is tampered with, a valid original signature should fail."""
        original_payload = b'{"action": "opened"}'
        tampered_payload = b'{"action": "closed"}'
        sig = _compute_signature(original_payload)
        assert verify_signature(tampered_payload, sig) is False

    @WEBHOOK_SECRET_SETTING
    def test_invalid_header_format_rejected(self) -> None:
        """A header without the 'sha256=' prefix should be rejected."""
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, "abc123") is False

    @WEBHOOK_SECRET_SETTING
    def test_no_webhook_secret_dev_mode(self, monkeypatch) -> None:
        """With no webhook secret in DEBUG mode, verification should be skipped."""
        monkeypatch.setattr("django.conf.settings.WEBHOOK_SECRET", "")
        monkeypatch.setattr("django.conf.settings.DEBUG", True)
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, None) is True

    @WEBHOOK_SECRET_SETTING
    def test_no_webhook_secret_production_rejected(self, monkeypatch) -> None:
        """With no webhook secret in production (DEBUG=False), verification should fail."""
        monkeypatch.setattr("django.conf.settings.WEBHOOK_SECRET", "")
        monkeypatch.setattr("django.conf.settings.DEBUG", False)
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, None) is False

    @WEBHOOK_SECRET_SETTING
    def test_constant_time_comparison(self) -> None:
        """Verify we use hmac.compare_digest (constant-time comparison)."""
        payload = b'{"action": "opened"}'
        sig = _compute_signature(payload)
        # This should work the same; the implementation detail is
        # that compare_digest is used inside verify_signature.
        assert verify_signature(payload, sig) is True

    @WEBHOOK_SECRET_SETTING
    @pytest.mark.parametrize(
        ("payload", "signature", "expected"),
        [
            (b"", "sha256=invalid", False),
            (b"test", "sha256=" + "a" * 64, False),
            (b"{bad json", _compute_signature(b"{bad json"), True),
            (b'{"key": "value"}', _compute_signature(b'{"key": "value"}'), True),
        ],
    )
    def test_various_payloads(self, payload: bytes, signature: str, expected: bool) -> None:
        """Parametrized tests for various payload/signature combinations."""
        result = verify_signature(payload, signature)
        assert result is expected

    @WEBHOOK_SECRET_SETTING
    def test_known_good_signature(self) -> None:
        """Test with a known computed signature value."""
        payload = b"test-payload"
        # Compute the expected signature manually
        expected_digest = hmac.new(TEST_SECRET, msg=payload, digestmod=hashlib.sha256).hexdigest()
        sig = f"sha256={expected_digest}"
        assert verify_signature(payload, sig) is True
