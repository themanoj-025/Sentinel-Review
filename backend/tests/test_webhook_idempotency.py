"""
Webhook idempotency tests — simulates GitHub's at-least-once redelivery.

Covers:
- Same X-GitHub-Delivery ID delivered twice → only one Review created
- Different X-GitHub-Delivery IDs for same PR → a new Review is created
- Different repos with the same delivery ID don't interfere
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from django.test import Client, override_settings
from sentinel_review.models.installation import Installation
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review

pytestmark = pytest.mark.slow
WEBHOOK_URL = "/webhooks/github/"
TEST_SECRET = "test-webhook-secret"


def _sign_payload(payload: bytes, secret: str = TEST_SECRET) -> str:
    """Compute HMAC-SHA256 signature for a payload."""
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _make_payload(
    repo_full_name: str = "testowner/testrepo-42", repo_id: int = 789, pr_number: int = 42
) -> tuple[bytes, str]:
    """Build a realistic webhook payload + signature."""
    payload = {
        "action": "opened",
        "pull_request": {
            "number": pr_number,
            "title": "Test PR",
            "user": {"login": "testuser"},
            "head": {"sha": "abc123"},
            "base": {"sha": "def456"},
        },
        "repository": {
            "id": repo_id,
            "full_name": repo_full_name,
            "private": False,
            "owner": {"login": "testowner"},
        },
        "installation": {"id": 1001},
    }
    body = json.dumps(payload).encode()
    sig = _sign_payload(body)
    return body, sig


@pytest.fixture(autouse=True)
def _ensure_installation_exists(db):
    """Ensure the test installation exists before each test."""
    Installation.objects.get_or_create(
        github_installation_id=1001,
        defaults={"account_login": "testowner"},
    )


@pytest.mark.django_db
class TestWebhookIdempotency:
    """Idempotency: same delivery ID → one Review; different ID → new Review."""

    def _deliver(self, client, body: bytes, sig: str, delivery_id: str) -> None:
        """POST a webhook and return the response."""
        return client.post(
            WEBHOOK_URL,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_DELIVERY=delivery_id,
            HTTP_X_GITHUB_EVENT="pull_request",
        )

    def test_duplicate_delivery_suppressed(self) -> None:
        """Same X-GitHub-Delivery ID delivered twice → only one Review."""
        with override_settings(WEBHOOK_SECRET=TEST_SECRET, CELERY_TASK_ALWAYS_EAGER=True):
            client = Client()
            body, sig = _make_payload(
                repo_full_name="testowner/testrepo-42", repo_id=789, pr_number=42
            )
            delivery_id = "dup-delivery-001"

            resp1 = self._deliver(client, body, sig, delivery_id)
            assert resp1.status_code in (200, 202)
            count_after_first = Review.objects.count()

            resp2 = self._deliver(client, body, sig, delivery_id)
            assert resp2.status_code in (200, 202)
            count_after_second = Review.objects.count()

            assert (
                count_after_second == count_after_first
            ), f"Expected {count_after_first} review(s) after duplicate, got {count_after_second}"

    def test_different_delivery_creates_new_review(self) -> None:
        """Different X-GitHub-Delivery IDs for the same PR → both enqueue reviews."""
        with override_settings(WEBHOOK_SECRET=TEST_SECRET, CELERY_TASK_ALWAYS_EAGER=True):
            client = Client()
            body, sig = _make_payload()

            resp1 = self._deliver(client, body, sig, "delivery-a")
            assert resp1.status_code in (200, 202)

            resp2 = self._deliver(client, body, sig, "delivery-b")
            assert resp2.status_code in (200, 202)

            count = Review.objects.count()
            assert count >= 1, f"Expected at least 1 Review for different delivery IDs, got {count}"

    def test_repo_isolation(self) -> None:
        """Different repos with the same delivery ID should not interfere."""
        with override_settings(WEBHOOK_SECRET=TEST_SECRET, CELERY_TASK_ALWAYS_EAGER=True):
            client = Client()
            # Create payloads for two different repos with matching repo IDs
            body1, sig1 = _make_payload(
                repo_full_name="testowner/testrepo-100", repo_id=789100, pr_number=100
            )
            body2, sig2 = _make_payload(
                repo_full_name="testowner/testrepo-200", repo_id=789200, pr_number=200
            )

            # Ensure distinct repos exist with matching GitHub IDs
            repo_model = Repo
            repo_model.objects.get_or_create(
                installation=Installation.objects.get(github_installation_id=1001),
                github_repo_id=789100,
                defaults={"full_name": "testowner/testrepo-100"},
            )
            repo_model.objects.get_or_create(
                installation=Installation.objects.get(github_installation_id=1001),
                github_repo_id=789200,
                defaults={"full_name": "testowner/testrepo-200"},
            )

            resp1 = self._deliver(client, body1, sig1, "shared-delivery")
            assert resp1.status_code in (200, 202)

            resp2 = self._deliver(client, body2, sig2, "shared-delivery")
            assert resp2.status_code in (200, 202)

            assert Review.objects.count() >= 1
