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
    logger.info(f"Processing reactions for comment {comment_id} on {repo_full_name}")

    try:
        # Find the comment in our database
        comment = Comment.objects.get(github_comment_id=comment_id)
    except Comment.DoesNotExist:
        logger.warning(f"Comment {comment_id} not found in database — skipping feedback")
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
        logger.error(f"Failed to fetch reactions: {e}")
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

    logger.info(f"Processed {created_count} new reactions for comment {comment_id}")
    return {"status": "completed", "new_feedback_count": created_count}


def compute_usefulness_rate(repo_full_name: str | None = None) -> dict:
    """
    Compute the usefulness rate of review comments.

    Args:
        repo_full_name: Optional repo filter.

    Returns:
        Dict with overall stats and per-category breakdown.
    """

    from sentinel_review.models.comment import Comment
    from sentinel_review.models.feedback import Feedback

    comments = Comment.objects.all()
    if repo_full_name:
        comments = comments.filter(review__pull_request__repo__full_name=repo_full_name)

    total_comments = comments.count()
    commented_on = comments.filter(feedback__isnull=False).distinct().count()

    # Get feedback counts
    upvotes = Feedback.objects.filter(
        reaction=Feedback.Reaction.THUMBS_UP,
    )
    downvotes = Feedback.objects.filter(
        reaction=Feedback.Reaction.THUMBS_DOWN,
    )

    if repo_full_name:
        upvotes = upvotes.filter(comment__review__pull_request__repo__full_name=repo_full_name)
        downvotes = downvotes.filter(comment__review__pull_request__repo__full_name=repo_full_name)

    up_count = upvotes.count()
    down_count = downvotes.count()
    total_feedback = up_count + down_count

    usefulness_rate = 0.0
    if total_feedback > 0:
        usefulness_rate = round(up_count / total_feedback * 100, 1)

    # Per-category breakdown
    category_stats = []
    for cat_code, cat_label in Comment.Category.choices:
        cat_comments = comments.filter(category=cat_code)
        cat_count = cat_comments.count()
        cat_up = upvotes.filter(comment__category=cat_code).count()
        cat_down = downvotes.filter(comment__category=cat_code).count()
        cat_total = cat_up + cat_down
        cat_rate = round(cat_up / cat_total * 100, 1) if cat_total > 0 else 0.0

        category_stats.append(
            {
                "category": cat_code,
                "label": cat_label,
                "total_comments": cat_count,
                "upvotes": cat_up,
                "downvotes": cat_down,
                "usefulness_rate": cat_rate,
            }
        )

    return {
        "total_comments": total_comments,
        "comments_with_feedback": commented_on,
        "total_feedback_votes": total_feedback,
        "upvotes": up_count,
        "downvotes": down_count,
        "overall_usefulness_rate": usefulness_rate,
        "categories": category_stats,
    }
