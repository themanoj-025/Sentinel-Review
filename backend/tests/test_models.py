"""
Tests for the Django ORM models.

Covers:
- All 6 models can be created and persisted
- Unique constraints work (duplicates rejected)
- Foreign key relationships and cascading
- Field defaults work correctly
- Model properties (enabled_categories, private_review_allowed, max_comments)
- String representations
- Schema round-trip (create → read → update)
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from sentinel_review.models.comment import Comment
from sentinel_review.models.feedback import Feedback
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review
from sentinel_review.workers.feedback_worker import compute_usefulness_rate


class TestInstallationModel:
    """Tests for the Installation model."""

    def test_create_installation(self, db):
        """A basic Installation should be creatable."""
        inst = Installation.objects.create(
            github_installation_id=1001,
            account_login="testowner",
        )
        assert inst.id is not None
        assert inst.github_installation_id == 1001
        assert inst.account_login == "testowner"
        assert inst.created_at is not None

    def test_unique_github_installation_id(self, db):
        """Duplicate github_installation_id should be rejected."""
        Installation.objects.create(github_installation_id=1001, account_login="owner1")
        with pytest.raises(IntegrityError):
            Installation.objects.create(github_installation_id=1001, account_login="owner2")

    def test_default_account_type(self, db):
        """Default account_type should be 'User'."""
        inst = Installation.objects.create(github_installation_id=2001, account_login="user")
        assert inst.account_type == "User"

    def test_str(self, db):
        """__str__ should show installation ID and login."""
        inst = Installation.objects.create(github_installation_id=3001, account_login="org")
        assert "3001" in str(inst)
        assert "org" in str(inst)

    def test_timestamps_auto(self, db):
        """created_at and updated_at should be set automatically."""
        inst = Installation.objects.create(github_installation_id=4001, account_login="test")
        assert inst.created_at is not None
        assert inst.updated_at is not None


class TestRepoModel:
    """Tests for the Repo model."""

    def test_create_repo(self, db_installation: Installation, db):
        """A basic Repo should be creatable."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=789,
            full_name="testowner/testrepo",
        )
        assert repo.id is not None
        assert repo.full_name == "testowner/testrepo"
        assert repo.is_private is False

    def test_unique_repo_per_installation(self, db_installation: Installation, db):
        """Duplicate (installation, github_repo_id) should be rejected."""
        Repo.objects.create(
            installation=db_installation,
            github_repo_id=789,
            full_name="testowner/testrepo",
        )
        with pytest.raises(IntegrityError):
            Repo.objects.create(
                installation=db_installation,
                github_repo_id=789,
                full_name="testowner/testrepo2",
            )

    def test_same_repo_id_different_installation(self, db, db_installation):
        """Different installations CAN have the same repo_id."""
        inst2 = Installation.objects.create(github_installation_id=2002, account_login="other")
        repo1 = Repo.objects.create(
            installation=db_installation, github_repo_id=789, full_name="a/repo"
        )
        repo2 = Repo.objects.create(installation=inst2, github_repo_id=789, full_name="b/repo")
        assert repo1.id != repo2.id

    def test_default_config(self, db_installation: Installation, db):
        """Default config should be an empty dict."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=101,
            full_name="owner/repo",
        )
        assert repo.config == {}

    def test_enabled_categories_property_default(self, db_installation: Installation, db):
        """enabled_categories should return all categories by default."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=102,
            full_name="owner/repo",
        )
        cats = repo.enabled_categories
        assert "bug" in cats
        assert "style" in cats
        assert "security" in cats
        assert "suggestion" in cats

    def test_enabled_categories_property_custom(self, db_installation: Installation, db):
        """enabled_categories should return configured categories."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=103,
            full_name="owner/repo",
            config={"enabled_categories": ["security", "bug"]},
        )
        assert repo.enabled_categories == ["security", "bug"]

    def test_private_review_allowed_default(self, db_installation: Installation, db):
        """private_review_allowed should default to False."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=104,
            full_name="owner/private-repo",
            is_private=True,
        )
        assert repo.private_review_allowed is False

    def test_private_review_allowed_opted_in(self, db_installation: Installation, db):
        """private_review_allowed should be True when opted in."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=105,
            full_name="owner/private-repo",
            is_private=True,
            config={"private_repo_opt_in": True},
        )
        assert repo.private_review_allowed is True

    def test_max_comments_default(self, db_installation: Installation, db):
        """max_comments should default to 25."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=106,
            full_name="owner/repo",
        )
        assert repo.max_comments == 25

    def test_str(self, db_installation: Installation, db):
        """__str__ should return the full_name."""
        repo = Repo.objects.create(
            installation=db_installation,
            github_repo_id=107,
            full_name="owner/repo",
        )
        assert str(repo) == "owner/repo"


class TestPullRequestModel:
    """Tests for the PullRequest model."""

    def test_create_pull_request(self, db_repo: Repo, db):
        """A basic PullRequest should be creatable."""
        pr = PullRequest.objects.create(
            repo=db_repo,
            github_pr_number=42,
            title="Fix bug",
            author_login="testuser",
        )
        assert pr.id is not None
        assert pr.github_pr_number == 42
        assert pr.status == PullRequest.Status.OPEN

    def test_unique_pr_per_repo(self, db_repo: Repo, db):
        """Duplicate (repo, github_pr_number) should be rejected."""
        PullRequest.objects.create(repo=db_repo, github_pr_number=42)
        with pytest.raises(IntegrityError):
            PullRequest.objects.create(repo=db_repo, github_pr_number=42)

    def test_default_status(self, db_repo: Repo, db):
        """Default status should be 'open'."""
        pr = PullRequest.objects.create(repo=db_repo, github_pr_number=100)
        assert pr.status == PullRequest.Status.OPEN

    def test_str(self, db_repo: Repo, db):
        """__str__ should show PR number and repo."""
        pr = PullRequest.objects.create(repo=db_repo, github_pr_number=42)
        assert "#42" in str(pr)
        assert "testowner/testrepo" in str(pr)


class TestReviewModel:
    """Tests for the Review model."""

    def test_create_review(self, db_pull_request: PullRequest, db):
        """A basic Review should be creatable."""
        review = Review.objects.create(
            pull_request=db_pull_request,
            triggered_by=Review.Trigger.OPENED,
        )
        assert review.id is not None
        assert review.status == Review.Status.QUEUED  # default
        assert review.triggered_by == Review.Trigger.OPENED

    def test_default_status(self, db_pull_request: PullRequest, db):
        """Default status should be 'queued'."""
        review = Review.objects.create(pull_request=db_pull_request)
        assert review.status == Review.Status.QUEUED

    def test_str(self, db_pull_request: PullRequest, db):
        """__str__ should show review and PR info."""
        review = Review.objects.create(pull_request=db_pull_request)
        assert str(review) is not None
        assert str(db_pull_request.github_pr_number) in str(review)

    def test_review_cascade(self, db_pull_request: PullRequest, db):
        """Deleting a PR should cascade to its reviews."""
        review = Review.objects.create(pull_request=db_pull_request)
        review_id = review.id
        db_pull_request.delete()
        assert Review.objects.filter(id=review_id).count() == 0


class TestCommentModel:
    """Tests for the Comment model."""

    def test_create_comment(self, db_review: Review, db):
        """A basic Comment should be creatable."""
        comment = Comment.objects.create(
            review=db_review,
            file_path="app.py",
            line_number=10,
            category=Comment.Category.BUG,
            severity=Comment.Severity.WARNING,
            content="Possible off-by-one error.",
        )
        assert comment.id is not None
        assert comment.file_path == "app.py"
        assert comment.line_number == 10
        assert comment.category == Comment.Category.BUG
        assert comment.severity == Comment.Severity.WARNING
        assert comment.suggested_fix is None

    def test_str(self, db_review: Review, db):
        """__str__ should show comment details."""
        comment = Comment.objects.create(
            review=db_review,
            file_path="app.py",
            line_number=5,
            category=Comment.Category.SECURITY,
            severity=Comment.Severity.BLOCKING,
            content="Test content",
        )
        assert "BLOCKING" in str(comment) or "blocking" in str(comment)
        assert "app.py" in str(comment)
        assert "5" in str(comment)

    def test_comment_cascade(self, db_review: Review, db):
        """Deleting a review should cascade to its comments."""
        comment = Comment.objects.create(
            review=db_review,
            file_path="test.py",
            line_number=1,
            category=Comment.Category.SUGGESTION,
            severity=Comment.Severity.NIT,
            content="Test",
        )
        comment_id = comment.id
        db_review.delete()
        assert Comment.objects.filter(id=comment_id).count() == 0


class TestFeedbackModel:
    """Tests for the Feedback model."""

    def test_create_feedback(self, db_comments: list[Comment], db):
        """A basic Feedback entry should be creatable."""
        feedback = Feedback.objects.create(
            comment=db_comments[0],
            reaction=Feedback.Reaction.THUMBS_UP,
            reactor_login="reviewer1",
        )
        assert feedback.id is not None
        assert feedback.reaction == Feedback.Reaction.THUMBS_UP

    def test_unique_feedback_constraint(self, db_comments: list[Comment], db):
        """Duplicate (comment, reactor_login, reaction) should be rejected."""
        Feedback.objects.create(
            comment=db_comments[0],
            reaction=Feedback.Reaction.THUMBS_UP,
            reactor_login="reviewer1",
        )
        with pytest.raises(IntegrityError):
            Feedback.objects.create(
                comment=db_comments[0],
                reaction=Feedback.Reaction.THUMBS_UP,
                reactor_login="reviewer1",
            )

    def test_different_reaction_same_user(self, db_comments: list[Comment], db):
        """Same user can have both thumbs_up and thumbs_down on the same comment."""
        Feedback.objects.create(
            comment=db_comments[0],
            reaction=Feedback.Reaction.THUMBS_UP,
            reactor_login="reviewer1",
        )
        # This should work because (comment, reactor_login, reaction) = (c1, r1, thumbs_down) is unique
        feedback = Feedback.objects.create(
            comment=db_comments[0],
            reaction=Feedback.Reaction.THUMBS_DOWN,
            reactor_login="reviewer1",
        )
        assert feedback.id is not None

    def test_str(self, db_comments: list[Comment], db):
        """__str__ should show reaction and login."""
        feedback = Feedback.objects.create(
            comment=db_comments[0],
            reaction=Feedback.Reaction.THUMBS_UP,
            reactor_login="reviewer1",
        )
        assert "thumbs_up" in str(feedback) or "👍" in str(feedback)
        assert "reviewer1" in str(feedback)


class TestSchemaRoundTrip:
    """Integration test: full schema round-trip with all models."""

    def test_full_create_read_update(self, db):
        """Create, read, and update objects across the full model chain."""
        # Create
        inst = Installation.objects.create(github_installation_id=5001, account_login="org")
        repo = Repo.objects.create(
            installation=inst,
            github_repo_id=5001,
            full_name="org/repo",
            config={"enabled_categories": ["security"]},
        )
        pr = PullRequest.objects.create(repo=repo, github_pr_number=1, title="Test PR")
        review = Review.objects.create(pull_request=pr, triggered_by=Review.Trigger.OPENED)
        comment = Comment.objects.create(
            review=review,
            file_path="test.py",
            line_number=1,
            category=Comment.Category.SECURITY,
            severity=Comment.Severity.BLOCKING,
            content="Issue found",
        )
        Feedback.objects.create(
            comment=comment,
            reaction=Feedback.Reaction.THUMBS_UP,
            reactor_login="testuser",
        )

        # Read back
        assert Installation.objects.count() == 1
        assert Repo.objects.count() == 1
        assert PullRequest.objects.count() == 1
        assert Review.objects.count() == 1
        assert Comment.objects.count() == 1
        assert Feedback.objects.count() == 1

        # Update
        repo.config["max_comments"] = 10
        repo.save()
        repo.refresh_from_db()
        assert repo.max_comments == 10

        # Verify relationships
        assert comment.review == review
        assert review.pull_request == pr
        assert pr.repo == repo
        assert repo.installation == inst
        assert comment.feedback.count() == 1


class TestUsefulnessRate:
    """Tests for compute_usefulness_rate."""

    def test_no_feedback(self, db_review: Review, db):
        """With no feedback, rate should be 0 and counts zero."""
        Comment.objects.create(
            review=db_review,
            file_path="test.py",
            line_number=1,
            category=Comment.Category.BUG,
            severity=Comment.Severity.WARNING,
            content="Test",
        )
        result = compute_usefulness_rate()
        assert result["overall_usefulness_rate"] == 0.0
        assert result["total_comments"] == 1
        assert result["total_feedback_votes"] == 0

    def test_with_feedback(self, db_feedback: list[Feedback], db):
        """With feedback, rate should be computed correctly."""
        result = compute_usefulness_rate()
        # 2 upvotes + 1 downvote = 3 total, rate = 2/3 * 100 = 66.7
        assert result["total_feedback_votes"] == 3
        assert result["upvotes"] == 2
        assert result["downvotes"] == 1
        assert result["overall_usefulness_rate"] == 66.7

    def test_per_repo_filter(self, db_feedback: list[Feedback], db, db_repo: Repo):
        """Filtering by repo should only count that repo's data."""
        result = compute_usefulness_rate("testowner/testrepo")
        assert result["total_comments"] == 2
        assert result["total_feedback_votes"] == 3

    def test_per_repo_nonexistent(self, db):
        """A non-existent repo should return zeros."""
        result = compute_usefulness_rate("nonexistent/repo")
        assert result["total_comments"] == 0
        assert result["total_feedback_votes"] == 0

    def test_category_breakdown(self, db_feedback: list[Feedback], db):
        """Category breakdown should be returned correctly."""
        result = compute_usefulness_rate()
        categories = result["categories"]
        assert len(categories) == 4  # bug, style, security, suggestion
        security_cat = [c for c in categories if c["category"] == "security"][0]
        assert security_cat["total_comments"] == 2  # both comments are security
        assert security_cat["upvotes"] == 2
        assert security_cat["downvotes"] == 1
