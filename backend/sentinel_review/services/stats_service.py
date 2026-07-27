"""
Stats service — shared business logic for computing review usefulness metrics.

Used by both the dashboard views and the REST API to avoid
duplicated aggregation/annotation logic.
"""

from __future__ import annotations

from sentinel_review.models.comment import Comment
from sentinel_review.models.feedback import Feedback


class StatsService:
    """Service for computing review usefulness and statistics."""

    @staticmethod
    def get_usefulness_rate(repo_full_name: str | None = None) -> dict:
        """Compute the usefulness rate of review comments.

        Args:
            repo_full_name: Optional repo filter ("owner/repo").

        Returns:
            Dict with overall stats and per-category breakdown.
        """
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

            category_stats.append({
                "category": cat_code,
                "label": cat_label,
                "total_comments": cat_count,
                "upvotes": cat_up,
                "downvotes": cat_down,
                "usefulness_rate": cat_rate,
            })

        return {
            "total_comments": total_comments,
            "comments_with_feedback": commented_on,
            "total_feedback_votes": total_feedback,
            "upvotes": up_count,
            "downvotes": down_count,
            "overall_usefulness_rate": usefulness_rate,
            "categories": category_stats,
        }
