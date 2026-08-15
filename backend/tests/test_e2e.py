"""
End-to-end integration tests for the full review pipeline.

Exercises the complete flow: webhook received → Celery task (eager) →
mocked GitHub API → mocked LLM provider → database records created.

This is the highest-value test in the suite because it validates that
all components wire together correctly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from sentinel_review.models.comment import Comment
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review
from sentinel_review.workers.cache import cache_clear_all
from sentinel_review.workers.github_client import GitHubRepoContext
from sentinel_review.workers.llm import LLMResult

WEBHOOK_URL = reverse("github-webhook")
TEST_SECRET = "test-secret-key"

# E2E settings: eager Celery + propagate exceptions for testing
E2E_SETTINGS = override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    WEBHOOK_SECRET=TEST_SECRET,
)


def _sign_payload(payload: bytes, secret: str = TEST_SECRET) -> str:
    """Compute HMAC-SHA256 signature for a payload."""
    digest = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_webhook_payload() -> dict[str, Any]:
    """Build a standard webhook payload for an opened PR."""
    return {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "Fix critical security issue",
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


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def e2e_mocks():
    """Set up mocks for GitHubClient and LLM provider.

    Returns the mock objects for additional assertions.
    """
    from sentinel_review.workers.llm import LLMResult
    from sentinel_review.workers.schemas import Finding

    # Mock GitHub client
    mock_client = MagicMock()
    mock_client.get_diff.return_value = (
        "diff --git a/app.py b/app.py\n"
        "index abc123..def456 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,5 +1,7 @@\n"
        " def get_user(email):\n"
        '-    query = "SELECT * FROM users WHERE email = %s" % email\n'
        "+    query = f\"SELECT * FROM users WHERE email = '{email}'\"\n"
        "     cursor.execute(query)\n"
        "     return cursor.fetchone()\n"
        "\n"
        "+def delete_user(user_id):\n"
        '+    db.execute("DELETE FROM users WHERE id = " + str(user_id))\n'
    )
    mock_client.get_repo_context.return_value = GitHubRepoContext(
        full_name="testowner/testrepo",
        default_branch="main",
        has_contributing=False,
        has_linter_config=False,
    )
    mock_client.get_file_content.return_value = "def foo():\n    pass\n"
    mock_client.post_review.return_value = {
        "id": 5001,
        "comments": [{"id": 3001}, {"id": 3002}],
    }

    # Mock LLM provider
    mock_provider = MagicMock()
    mock_provider.review_diff.return_value = LLMResult(
        findings=[
            Finding(
                file_path="app.py",
                line_number=2,
                category="security",
                severity="blocking",
                comment="SQL injection vulnerability — user input is interpolated directly into query string.",
                suggested_fix="Use parameterized queries.",
            ),
            Finding(
                file_path="app.py",
                line_number=8,
                category="security",
                severity="blocking",
                comment="SQL injection via string concatenation in delete_user.",
            ),
        ],
        total_tokens=500,
        latency_ms=1500,
    )

    # Apply patches
    patcher_github = patch(
        "sentinel_review.workers.pipeline.GitHubClient",
        return_value=mock_client,
    )
    patcher_llm = patch(
        "sentinel_review.workers.pipeline.get_llm_provider",
        return_value=mock_provider,
    )

    # Clear cache to prevent cross-test contamination
    cache_clear_all()

    mock_github_cls = patcher_github.start()
    mock_llm_fn = patcher_llm.start()

    yield {
        "mock_client": mock_client,
        "mock_provider": mock_provider,
        "mock_github_cls": mock_github_cls,
        "mock_llm_fn": mock_llm_fn,
    }

    patcher_github.stop()
    patcher_llm.stop()


class TestE2EPipeline:
    """End-to-end tests: webhook → Celery → GitHub → LLM → Database."""

    @E2E_SETTINGS
    @pytest.mark.django_db(transaction=True)
    def test_full_pipeline_creates_review_and_comments(self, client, e2e_mocks, db):
        """Full pipeline: valid webhook → 202 → Review+Comment rows created."""
        payload = _build_webhook_payload()
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = _sign_payload(payload_bytes)

        response = client.post(
            WEBHOOK_URL,
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY="e2e-test-delivery-1",
        )

        assert (
            response.status_code == 202
        ), f"Expected 202 Accepted, got {response.status_code}: {response.content[:200]}"

        install = Installation.objects.filter(github_installation_id=1001).first()
        assert install is not None, "Installation should have been created"
        assert install.account_login == "testowner"

        repo = Repo.objects.filter(full_name="testowner/testrepo").first()
        assert repo is not None, "Repo should have been created"
        assert repo.github_repo_id == 789
        assert repo.is_private is False

        pr = PullRequest.objects.filter(repo=repo, github_pr_number=42).first()
        assert pr is not None, "PullRequest should have been created"
        assert pr.title == "Fix critical security issue"
        assert pr.author_login == "testuser"

        review = Review.objects.filter(pull_request=pr).first()
        assert review is not None, "Review should have been created"
        assert (
            review.status == Review.Status.COMPLETED
        ), f"Expected COMPLETED status, got {review.status}"
        assert review.triggered_by == "opened"
        assert review.findings_count == 2, f"Expected 2 findings, got {review.findings_count}"
        assert review.latency_ms > 0, "Latency should be recorded"
        assert review.token_cost == 500, "Token cost should match mock"

        comments = Comment.objects.filter(review=review).order_by("line_number")
        assert len(comments) == 2, f"Expected 2 comments, got {len(comments)}"

        # First comment: line 2, security, blocking
        c1 = comments[0]
        assert c1.file_path == "app.py", f"Expected app.py, got {c1.file_path}"
        assert c1.line_number == 2, f"Expected line 2, got {c1.line_number}"
        assert c1.category == "security", f"Expected security, got {c1.category}"
        assert c1.severity == "blocking", f"Expected blocking, got {c1.severity}"
        assert "SQL injection" in c1.content, f"Expected SQL injection in: {c1.content}"
        assert c1.suggested_fix is not None
        assert "parameterized" in c1.suggested_fix.lower()

        # Second comment: line 8, security, blocking
        c2 = comments[1]
        assert c2.file_path == "app.py"
        assert c2.line_number == 8
        assert c2.category == "security"
        assert c2.severity == "blocking"

        mock_client = e2e_mocks["mock_client"]
        mock_client.get_diff.assert_called_once_with(1001, "testowner/testrepo", 42)
        mock_client.get_repo_context.assert_called_once_with(1001, "testowner/testrepo")
        mock_client.post_review.assert_called_once()
        call_kwargs = mock_client.post_review.call_args[1]
        assert call_kwargs["repo_full_name"] == "testowner/testrepo"
        assert call_kwargs["pr_number"] == 42
        assert (
            len(call_kwargs["comments"]) == 2
        ), f"Expected 2 posted comments, got {len(call_kwargs['comments'])}"
        # Verify review body contains summary info
        assert "Sentinel Review Complete" in call_kwargs.get("review_body", "")
        assert "blocking" in call_kwargs.get("review_body", "")

        mock_provider = e2e_mocks["mock_provider"]
        mock_provider.review_diff.assert_called_once()

    @E2E_SETTINGS
    @pytest.mark.django_db(transaction=True)
    def test_webhook_ignores_non_pr_events(self, client, db):
        """Non-PR events should return 200 without creating records."""
        payload = json.dumps({"action": "created"}).encode("utf-8")
        sig = _sign_payload(payload)

        response = client.post(
            WEBHOOK_URL,
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="push",
            HTTP_X_GITHUB_DELIVERY="e2e-test-push",
        )

        assert response.status_code == 200
        # No records should be created
        assert Review.objects.count() == 0
        assert Comment.objects.count() == 0

    @E2E_SETTINGS
    @pytest.mark.django_db(transaction=True)
    def test_duplicate_webhook_delivery_does_not_create_duplicate_review(
        self, client, e2e_mocks, db
    ):
        """Same delivery_id sent twice should not create a second Review."""
        payload = _build_webhook_payload()
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = _sign_payload(payload_bytes)

        # First delivery
        response1 = client.post(
            WEBHOOK_URL,
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY="e2e-test-duplicate",
        )
        assert response1.status_code == 202

        review_count_after_first = Review.objects.count()

        # Second delivery with same delivery_id
        response2 = client.post(
            WEBHOOK_URL,
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY="e2e-test-duplicate",
        )
        # Should return 200 (duplicate - not 202)
        assert response2.status_code == 200
        assert "duplicate" in response2.content.decode().lower()

        # No additional review should be created
        assert (
            Review.objects.count() == review_count_after_first
        ), "Duplicate delivery should not create additional Review records"

    @E2E_SETTINGS
    @pytest.mark.django_db(transaction=True)
    def test_bad_signature_rejected(self, client, db):
        """Webhook with invalid signature should be rejected."""
        payload = json.dumps(_build_webhook_payload()).encode("utf-8")

        response = client.post(
            WEBHOOK_URL,
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=invalid",
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY="e2e-test-bad-sig",
        )

        assert response.status_code == 401
        assert Review.objects.count() == 0

    @E2E_SETTINGS
    @pytest.mark.django_db(transaction=True)
    def test_github_failure_marks_review_as_failed(self, client, e2e_mocks, db):
        """When GitHub API fails, the review should be marked FAILED."""
        mock_client = e2e_mocks["mock_client"]
        mock_client.get_diff.side_effect = ConnectionError("GitHub API timeout")

        payload = _build_webhook_payload()
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = _sign_payload(payload_bytes)

        response = client.post(
            WEBHOOK_URL,
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY="e2e-test-fail-github",
        )

        assert response.status_code == 202

        # Review should exist and be marked FAILED
        pr = PullRequest.objects.filter(github_pr_number=42).first()
        assert pr is not None
        review = Review.objects.filter(pull_request=pr).first()
        assert review is not None
        assert review.status == Review.Status.FAILED, f"Expected FAILED, got {review.status}"
        assert review.error_message, "Error message should be set"
        assert "GitHub API" in review.error_message
        assert review.findings_count is None or review.findings_count == 0

    @E2E_SETTINGS
    @pytest.mark.django_db(transaction=True)
    def test_empty_diff_creates_review_with_no_comments(self, client, e2e_mocks, db):
        """Empty diff should still create a Review but with 0 Comments."""
        mock_client = e2e_mocks["mock_client"]
        mock_client.get_diff.return_value = ""

        mock_provider = e2e_mocks["mock_provider"]
        mock_provider.review_diff.return_value = LLMResult(
            findings=[], total_tokens=50, latency_ms=200
        )

        payload = _build_webhook_payload()
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = _sign_payload(payload_bytes)

        response = client.post(
            WEBHOOK_URL,
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY="e2e-test-empty-diff",
        )

        assert response.status_code == 202

        pr = PullRequest.objects.filter(github_pr_number=42).first()
        assert pr is not None
        review = Review.objects.filter(pull_request=pr).first()
        assert review is not None
        assert review.status == Review.Status.COMPLETED, f"Expected COMPLETED, got {review.status}"
        assert review.findings_count == 0
        assert Comment.objects.filter(review=review).count() == 0
