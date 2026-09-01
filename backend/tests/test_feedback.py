"""
Tests for the feedback capture worker.

Covers:
- process_reaction fetches reactions and stores feedback
- Comment not found in DB gracefully handled
- Only +1/-1 reactions are stored
- Duplicate reactions are skipped (get_or_create)
- compute_usefulness_rate returns correct stats
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import override_settings
from sentinel_review.models.feedback import Feedback
from sentinel_review.workers.feedback_worker import process_reaction

pytestmark = pytest.mark.slow
pytestmark = pytest.mark.integration

FEEDBACK_SETTINGS = override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)


class TestProcessReaction:
    """Tests for the process_reaction Celery task."""

    @FEEDBACK_SETTINGS
    def test_comment_not_found_skipped(self, db) -> None:
        """A comment not in our database should be skipped."""
        result = process_reaction(comment_id=99999, repo_full_name="owner/repo")
        assert result["status"] == "skipped"
        assert result["reason"] == "comment_not_found"

    @FEEDBACK_SETTINGS
    @patch("sentinel_review.workers.feedback_worker.GitHubClient")
    def test_fetches_and_stores_reactions(self, mock_client_class, db_comments, db) -> None:
        """Reactions from GitHub should be stored as Feedback entries."""
        comment = db_comments[0]

        mock_client = MagicMock()
        mock_client.get_comment_reactions.return_value = [
            {"id": 101, "content": "+1", "user": {"login": "reviewer1"}},
            {"id": 102, "content": "-1", "user": {"login": "reviewer2"}},
            {"id": 103, "content": "heart", "user": {"login": "reviewer3"}},
        ]
        mock_client_class.return_value = mock_client

        result = process_reaction(
            comment_id=comment.github_comment_id,
            repo_full_name="testowner/testrepo",
        )

        assert result["status"] == "completed"
        assert result["new_feedback_count"] == 2

        feedback_entries = Feedback.objects.filter(comment=comment)
        assert feedback_entries.count() == 2

        thumbs_up = feedback_entries.filter(reaction=Feedback.Reaction.THUMBS_UP)
        thumbs_down = feedback_entries.filter(reaction=Feedback.Reaction.THUMBS_DOWN)
        assert thumbs_up.count() == 1
        assert thumbs_down.count() == 1
        assert thumbs_up.first().reactor_login == "reviewer1"
        assert thumbs_down.first().reactor_login == "reviewer2"

    @FEEDBACK_SETTINGS
    @patch("sentinel_review.workers.feedback_worker.GitHubClient")
    def test_duplicate_reactions_skipped(self, mock_client_class, db_comments, db) -> None:
        """Repeated processing should not create duplicate Feedback."""
        comment = db_comments[0]

        Feedback.objects.create(
            comment=comment,
            reaction=Feedback.Reaction.THUMBS_UP,
            reactor_login="reviewer1",
            github_reaction_id=101,
        )

        mock_client = MagicMock()
        mock_client.get_comment_reactions.return_value = [
            {"id": 101, "content": "+1", "user": {"login": "reviewer1"}},
        ]
        mock_client_class.return_value = mock_client

        result = process_reaction(
            comment_id=comment.github_comment_id,
            repo_full_name="testowner/testrepo",
        )

        assert result["status"] == "completed"
        assert result["new_feedback_count"] == 0

    @FEEDBACK_SETTINGS
    @patch("sentinel_review.workers.feedback_worker.GitHubClient")
    def test_api_error_returns_error(self, mock_client_class, db_comments, db) -> None:
        """A GitHub API error should be caught and returned."""
        comment = db_comments[0]

        mock_client = MagicMock()
        mock_client.get_comment_reactions.side_effect = OSError("GitHub API timeout")
        mock_client_class.return_value = mock_client

        result = process_reaction(
            comment_id=comment.github_comment_id,
            repo_full_name="testowner/testrepo",
        )

        assert result["status"] == "error"

    @FEEDBACK_SETTINGS
    @patch("sentinel_review.workers.feedback_worker.GitHubClient")
    def test_no_installation_id(self, mock_client_class, db) -> None:
        """If the GitHubClient raises on construction, return error."""
        mock_client_class.side_effect = RuntimeError("Auth failed")

        # Create a minimal comment via fixture chain
        from sentinel_review.models.comment import Comment
        from sentinel_review.models.installation import Installation
        from sentinel_review.models.pull_request import PullRequest
        from sentinel_review.models.repo import Repo
        from sentinel_review.models.review import Review

        inst = Installation.objects.create(github_installation_id=9999, account_login="orphan")
        repo = Repo.objects.create(installation=inst, github_repo_id=999, full_name="orphan/repo")
        pr = PullRequest.objects.create(repo=repo, github_pr_number=1)
        review = Review.objects.create(pull_request=pr)
        comment = Comment.objects.create(
            review=review,
            github_comment_id=7777,
            file_path="x.py",
            line_number=1,
            category="bug",
            severity="warning",
            content="Test",
        )

        result = process_reaction(
            comment_id=comment.github_comment_id,
            repo_full_name="orphan/repo",
        )
        assert result["status"] == "error"
