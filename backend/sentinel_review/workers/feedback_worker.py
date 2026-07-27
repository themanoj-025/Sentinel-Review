"""
Celery worker for feedback capture.

Listens for reaction events (👍/👎) on review comments and stores them
in the database for the usefulness dashboard.
"""

import logging

from celery import shared_task

from sentinel_review.models.comment import Comment
from sentinel_review.models.feedback import Feedback

from .github_client import GitHubClient

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    queue="feedback",
    acks_late=True,
)
def process_reaction(
    self,
    comment_id: int,
    repo_full_name: str,
) -> dict:
    """
    Process reactions on a review comment.

    Polls GitHub for reactions on the given comment and stores
    👍/👎 as Feedback entries.
    """
    logger.info("Processing reactions for comment %s on %s", comment_id, repo_full_name)

    try:
        # Find the comment in our database
        comment = Comment.objects.get(github_comment_id=comment_id)
    except Comment.DoesNotExist:
        logger.warning("Comment %s not found in database — skipping feedback", comment_id)
        return {"status": "skipped", "reason": "comment_not_found"}

    # Fetch reactions from GitHub (requires installation ID)
    # We need to get the installation from the comment's review chain
    try:
        installation_id = comment.review.pull_request.repo.installation.github_installation_id
    except AttributeError:
        logger.error("Could not determine installation ID for comment")
        return {"status": "error", "reason": "no_installation"}

    try:
        client = GitHubClient()
        reactions = client.get_comment_reactions(installation_id, repo_full_name, comment_id)
    except Exception as e:
        logger.error("Failed to fetch reactions: %s", e)
        return {"status": "error", "error": str(e)}

    # Process reactions
    created_count = 0
    for reaction in reactions:
        content = reaction.get("content", "")
        if content not in ("+1", "-1"):
            continue

        reaction_map = {"+1": Feedback.Reaction.THUMBS_UP, "-1": Feedback.Reaction.THUMBS_DOWN}
        reactor_login = reaction.get("user", {}).get("login", "")
        github_reaction_id = reaction.get("id")

        if not reactor_login:
            continue

        _, created = Feedback.objects.get_or_create(
            comment=comment,
            reactor_login=reactor_login,
            defaults={
                "reaction": reaction_map[content],
                "github_reaction_id": github_reaction_id,
            },
        )
        if created:
            created_count += 1

    logger.info("Processed %d new reactions for comment %s", created_count, comment_id)
    return {"status": "completed", "new_feedback_count": created_count}


def compute_usefulness_rate(repo_full_name: str | None = None) -> dict:
    """Backward-compatible wrapper around StatsService.get_usefulness_rate."""
    from sentinel_review.services.stats_service import StatsService

    return StatsService.get_usefulness_rate(repo_full_name)
