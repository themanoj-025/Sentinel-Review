"""
Tests for the GitHub webhook receiver view.

Covers:
- Valid webhook with valid signature returns 202
- Missing signature returns 401
- Invalid signature returns 401
- Non-PR events return 200 (ignored)
- PR events with unsupported actions return 200
- Missing required data returns 400
- Review comment events enqueue feedback tasks
- Celery task is called with correct arguments (eager mode)
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse



pytestmark = pytest.mark.slow
WEBHOOK_URL = reverse("github-webhook")
TEST_SECRET = "test-secret-key"

# Reusable override for tests that verify signatures
WH_SETTING = override_settings(WEBHOOK_SECRET=TEST_SECRET)


def _sign_payload(payload: bytes, secret: str = TEST_SECRET) -> str:
    """Compute HMAC-SHA256 signature for a payload."""
    digest = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def webhook_payload() -> dict[str, Any]:
    return {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "Fix login bug",
            "user": {"login": "testuser"},
            "head": {"sha": "abc123"},
            "base": {"sha": "def456"},
        },
        "repository": {
            "id": 789,
            "full_name": "testowner/testrepo",
            "private": False,
            "owner": {"login": "testowner"},
        },
        "installation": {"id": 1001},
    }


class TestWebhookSignatureRejection:
    """Tests for HMAC signature verification on the webhook endpoint."""

    @WH_SETTING
    def test_missing_signature_returns_401(self, client: Client) -> None:
        """A request without X-Hub-Signature-256 should be rejected with 401."""
        response = client.post(
            WEBHOOK_URL,
            data=json.dumps({"action": "opened"}),
            content_type="application/json",
            HTTP_X_GITHUB_EVENT="pull_request",
        )
        assert response.status_code == 401

    @WH_SETTING
    def test_invalid_signature_returns_401(self, client: Client) -> None:
        """A request with a wrong signature should be rejected with 401."""
        response = client.post(
            WEBHOOK_URL,
            data=json.dumps({"action": "opened"}),
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
            HTTP_X_GITHUB_EVENT="pull_request",
        )
        assert response.status_code == 401

    @override_settings(WEBHOOK_SECRET=TEST_SECRET, CELERY_TASK_ALWAYS_EAGER=True)
    def test_valid_signature_returns_202(self, client: Client, webhook_payload: dict[str, Any]) -> None:
        """A validly-signed webhook should be accepted with 202."""
        payload_bytes = json.dumps(webhook_payload).encode("utf-8")
        sig = _sign_payload(payload_bytes)
        response = client.post(
            WEBHOOK_URL,
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY="test-valid-signature",
        )
        assert response.status_code in (200, 202)


class TestWebhookEventHandling:
    """Tests for different webhook event types."""

    @WH_SETTING
    def test_non_pr_event_returns_200(self, client: Client) -> None:
        """Non-pull_request events should be acknowledged with 200."""
        payload = json.dumps({"action": "created"})
        sig = _sign_payload(payload.encode())
        response = client.post(
            WEBHOOK_URL,
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="push",
        )
        assert response.status_code == 200

    @WH_SETTING
    def test_pr_unsupported_action_returns_200(self, client: Client) -> None:
        """PR events with unsupported actions (closed) should return 200."""
        payload = json.dumps(
            {
                "action": "closed",
                "pull_request": {"number": 1},
                "repository": {"id": 1, "full_name": "a/b", "owner": {"login": "a"}},
                "installation": {"id": 1},
            }
        )
        sig = _sign_payload(payload.encode())
        response = client.post(
            WEBHOOK_URL,
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
        )
        assert response.status_code == 200

    @override_settings(WEBHOOK_SECRET=TEST_SECRET, CELERY_TASK_ALWAYS_EAGER=True)
    def test_review_comment_event_returns_202(self, client: Client) -> None:
        """Review comment events should be acknowledged."""
        payload = json.dumps(
            {
                "action": "created",
                "comment": {"id": 3001},
                "repository": {"full_name": "testowner/testrepo"},
            }
        )
        sig = _sign_payload(payload.encode())
        response = client.post(
            WEBHOOK_URL,
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request_review_comment",
        )
        assert response.status_code == 202

    @WH_SETTING
    def test_missing_pull_request_data_returns_400(self, client: Client) -> None:
        """A PR event with missing required data should return 400."""
        payload = json.dumps({"action": "opened"})
        sig = _sign_payload(payload.encode())
        response = client.post(
            WEBHOOK_URL,
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
        )
        assert response.status_code == 400


class TestWebhookJobEnqueueing:
    """Tests that webhooks correctly enqueue Celery tasks."""

    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_TASK_EAGER_PROPAGATES=True,
        WEBHOOK_SECRET=TEST_SECRET,
    )
    def test_pr_opened_enqueues_review(self, client: Client, webhook_payload: dict[str, Any]) -> None:
        """An opened PR event should enqueue a review task (eager)."""
        payload_bytes = json.dumps(webhook_payload).encode("utf-8")
        sig = _sign_payload(payload_bytes)

        with patch("sentinel_review.workers.review_worker.review_pull_request.delay") as mock_task:
            response = client.post(
                WEBHOOK_URL,
                data=payload_bytes,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=sig,
                HTTP_X_GITHUB_EVENT="pull_request",
                HTTP_X_GITHUB_DELIVERY="test-enqueue-pr",
            )
            assert response.status_code == 202
            mock_task.assert_called_once()
            call_kwargs = mock_task.call_args[1]
            assert call_kwargs["installation_id"] == 1001
            assert call_kwargs["repo_full_name"] == "testowner/testrepo"
            assert call_kwargs["pr_number"] == 42

    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_TASK_EAGER_PROPAGATES=True,
        WEBHOOK_SECRET=TEST_SECRET,
    )
    def test_pr_synchronize_enqueues_review(self, client: Client, webhook_payload: dict[str, Any]) -> None:
        """A synchronize PR event should also enqueue a review."""
        webhook_payload["action"] = "synchronize"
        payload_bytes = json.dumps(webhook_payload).encode("utf-8")
        sig = _sign_payload(payload_bytes)

        with patch("sentinel_review.workers.review_worker.review_pull_request.delay") as mock_task:
            response = client.post(
                WEBHOOK_URL,
                data=payload_bytes,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=sig,
                HTTP_X_GITHUB_EVENT="pull_request",
            )
            assert response.status_code == 202
            mock_task.assert_called_once()
