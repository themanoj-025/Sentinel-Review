"""
GitHub webhook receiver for pull request events.

Accepts webhook payloads from GitHub, verifies HMAC signature,
enqueues a Celery review job, and responds quickly (under 10s per
GitHub's timeout expectation).
"""

import json
import logging

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from sentinel_review.webhooks.signature import verify_signature
from sentinel_review.workers.review_worker import review_pull_request

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def github_webhook(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming GitHub webhook events.

    Verifies the HMAC signature, then enqueues a Celery task for
    pull request events. Returns 200 immediately to meet GitHub's
    10-second timeout expectation.
    """
    # Read raw body for signature verification
    raw_body = request.body

    # Verify HMAC signature
    signature = request.META.get("HTTP_X_HUB_SIGNATURE_256")
    if not verify_signature(raw_body, signature):
        logger.warning("Webhook signature verification failed")
        return HttpResponse("Signature verification failed", status=401)

    # Parse event type
    event = request.META.get("HTTP_X_GITHUB_EVENT", "")
    delivery_id = request.META.get("HTTP_X_GITHUB_DELIVERY", "")

    logger.info(f"Received webhook: event={event}, delivery={delivery_id}")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON payload: {e}")
        return HttpResponse("Invalid JSON", status=400)

    # Only process pull_request events
    if event == "pull_request":
        return _handle_pull_request_event(payload, delivery_id)

    # Handle pull_request_review_comment events for feedback
    if event == "pull_request_review_comment":
        return _handle_review_comment_event(payload, delivery_id)

    # For reaction events (👍/👎)
    if event == "pull_request_review" and payload.get("action") == "submitted":
        return _handle_review_submitted_event(payload, delivery_id)

    # Acknowledge other events
    logger.debug(f"Ignoring event type: {event}")
    return HttpResponse("OK")


def _handle_pull_request_event(payload: dict, delivery_id: str) -> HttpResponse:
    """Handle pull_request opened/synchronize events."""
    action = payload.get("action")
    if action not in ("opened", "synchronize"):
        return HttpResponse("OK - ignored action")

    pr_data = payload.get("pull_request", {})
    repo_data = payload.get("repository", {})
    installation_data = payload.get("installation", {})

    if not all([pr_data, repo_data, installation_data]):
        logger.error("Missing required data in webhook payload")
        return HttpResponse("Missing data", status=400)

    installation_id = installation_data.get("id")
    repo_full_name = repo_data.get("full_name", "")
    pr_number = pr_data.get("number")
    pr_title = pr_data.get("title", "")
    pr_author = pr_data.get("user", {}).get("login", "")
    head_sha = pr_data.get("head", {}).get("sha", "")
    base_sha = pr_data.get("base", {}).get("sha", "")
    repo_id = repo_data.get("id")
    is_private = repo_data.get("private", False)
    account_login = (repo_data.get("owner") or {}).get("login", "")

    # Enqueue the review task
    review_pull_request.delay(
        installation_id=installation_id,
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_author=pr_author,
        head_sha=head_sha,
        base_sha=base_sha,
        is_private=is_private,
        account_login=account_login,
        action=action,
    )

    logger.info(
        f"Enqueued review: {repo_full_name}#{pr_number} "
        f"(delivery={delivery_id})"
    )
    return HttpResponse("Accepted", status=202)


def _handle_review_comment_event(payload: dict, delivery_id: str) -> HttpResponse:
    """Handle pull_request_review_comment events (for feedback capture)."""
    action = payload.get("action")
    if action not in ("created",):
        return HttpResponse("OK - ignored action")

    from sentinel_review.workers.feedback_worker import process_reaction

    comment_data = payload.get("comment", {})
    repo_data = payload.get("repository", {})

    comment_id = comment_data.get("id")
    repo_full_name = repo_data.get("full_name", "")

    if comment_id:
        process_reaction.delay(
            comment_id=comment_id,
            repo_full_name=repo_full_name,
        )

    return HttpResponse("Accepted", status=202)


def _handle_review_submitted_event(payload: dict, delivery_id: str) -> HttpResponse:
    """Handle pull_request_review submitted events."""
    # Can be extended for review-level feedback
    return HttpResponse("OK")
