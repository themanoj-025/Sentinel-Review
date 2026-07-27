"""
GitHub webhook receiver for pull request events.

Accepts webhook payloads from GitHub, verifies HMAC signature,
enqueues a Celery review job, and responds quickly (under 10s per
GitHub's timeout expectation).

Implements idempotency via X-GitHub-Delivery header — duplicate deliveries
are silently acknowledged but not re-processed.
"""

import json
import logging
import os
import time

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from sentinel_review.webhooks.signature import verify_signature
from sentinel_review.workers.review_worker import review_pull_request

logger = logging.getLogger(__name__)

# In-memory set of recently processed delivery IDs (for single-process deployments)
# In production with multiple workers, this is replaced by Redis.
_PROCESSED_DELIVERIES: set[str] = set()
_DELIVERY_TTL = 300  # 5 minutes — GitHub may redeliver within this window


def _is_duplicate_delivery(delivery_id: str) -> bool:
    """Check if a webhook delivery has already been processed."""
    if not delivery_id:
        return False

    # Try Redis-based dedup first (production)
    redis_url = os.environ.get("CELERY_BROKER_URL", "")
    if redis_url:
        try:
            import redis as redis_lib

            r = redis_lib.from_url(redis_url, socket_connect_timeout=2.0, decode_responses=True)
            key = f"webhook:delivery:{delivery_id}"
            if r.setnx(key, str(time.time())):
                r.expire(key, _DELIVERY_TTL)
                return False
            return True
        except Exception:
            pass  # Fall through to in-memory

    # In-memory fallback (single-worker dev)
    if delivery_id in _PROCESSED_DELIVERIES:
        return True
    _PROCESSED_DELIVERIES.add(delivery_id)
    # Keep set bounded
    if len(_PROCESSED_DELIVERIES) > 10000:
        _PROCESSED_DELIVERIES.clear()
    return False


@csrf_exempt  # nosemgrep: webhook endpoint uses HMAC-SHA256 for auth, not CSRF tokens
@require_POST
def github_webhook(request: HttpRequest) -> HttpResponse:
    """Handle incoming GitHub webhook events with idempotency."""
    raw_body = request.body

    # Verify HMAC signature
    signature = request.META.get("HTTP_X_HUB_SIGNATURE_256")
    if not verify_signature(raw_body, signature):
        logger.warning("Webhook signature verification failed")
        return HttpResponse("Signature verification failed", status=401)

    # Parse event type and delivery ID
    event = request.META.get("HTTP_X_GITHUB_EVENT", "")
    delivery_id = request.META.get("HTTP_X_GITHUB_DELIVERY", "")

    logger.info("Received webhook: event=%s, delivery=%s", event, delivery_id)

    # Deduplicate by delivery_id (GitHub may redeliver)
    if _is_duplicate_delivery(delivery_id):
        logger.debug("Duplicate delivery %s for event %s — acknowledging", delivery_id, event)
        return HttpResponse("OK - duplicate", status=200)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON payload: %s", e)
        return HttpResponse("Invalid JSON", status=400)

    # Route by event type
    if event == "pull_request":
        return _handle_pull_request_event(payload, delivery_id)
    if event == "pull_request_review_comment":
        return _handle_review_comment_event(payload, delivery_id)
    if event == "pull_request_review" and payload.get("action") == "submitted":
        return _handle_review_submitted_event(payload, delivery_id)

    logger.debug("Ignoring event type: %s", event)
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

    logger.info("Enqueued review: %s#%d (delivery=%s)", repo_full_name, pr_number, delivery_id)
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
    return HttpResponse("OK")
