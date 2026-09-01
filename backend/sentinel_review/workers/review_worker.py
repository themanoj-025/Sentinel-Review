"""
Celery review worker — the core of Sentinel Review.

Thin orchestration layer that delegates to the staged pipeline.
The pipeline (workers/pipeline.py) handles all business logic in
independently testable stages.
"""

import logging

from celery import shared_task

from .pipeline import ReviewContext, ReviewPipeline

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="reviews",
    acks_late=True,
    autoretry_for=(ConnectionError, TimeoutError),
)
def review_pull_request(
    self,
    installation_id: int,
    repo_id: int,
    repo_full_name: str,
    pr_number: int,
    pr_title: str = "",
    pr_author: str = "",
    head_sha: str = "",
    base_sha: str = "",
    is_private: bool = False,
    account_login: str = "",
    action: str = "opened",
) -> dict -> None:
    """
    Review a pull request: fetch diff, analyze with LLM, post comments.

    Thin wrapper around ReviewPipeline. All business logic is in pipeline stages.
    """
    logger.info("Starting review: %s#%d (%s)", repo_full_name, pr_number, action)

    ctx = ReviewContext(
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

    pipeline = ReviewPipeline()
    ctx = pipeline.run(ctx)

    # Convert result to serializable dict
    if ctx.skip_reason:
        return {"status": "skipped", "reason": ctx.skip_reason}

    if ctx.errors:
        return {"status": "error", "error": ctx.errors[0]}

    return {
        "status": "completed",
        "findings_count": len(ctx.posted_comments),
        "latency_ms": ctx.elapsed_ms,
        "token_cost": ctx.llm_result.total_tokens if ctx.llm_result else 0,
    }
