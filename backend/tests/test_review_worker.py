"""
Tests for the review worker pipeline.

Covers:
- _parse_changed_files extracts file paths from diffs
- _deduplicate removes near-duplicate findings
- _build_context_str builds context from repo metadata
- review_pull_request task flow (with mocked GitHub + LLM)
- Private repo opt-out skip
- Error handling at each stage
- Completion and failure state recording
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import override_settings
from sentinel_review.models.comment import Comment
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review
from sentinel_review.workers.github_client import GitHubRepoContext
from sentinel_review.workers.pipeline import (
    _build_context_str,
    _deduplicate,
    _parse_changed_files,
)
from sentinel_review.workers.review_worker import review_pull_request

# Unit Tests: Helper Functions


class TestParseChangedFiles:
    """Tests for _parse_changed_files()."""

    def test_parse_single_file(self, sample_diff: str) -> None:
        """A diff with one file should return one path."""
        files = _parse_changed_files(sample_diff)
        assert "app.py" in files

    def test_parse_multiple_files(self) -> None:
        """A diff with multiple files should return all paths."""
        diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-foo
+bar
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1 +1 @@
-old
+new
"""
        files = _parse_changed_files(diff)
        assert "a.py" in files
        assert "b.py" in files

    def test_empty_diff(self) -> None:
        """An empty diff should return an empty list."""
        assert _parse_changed_files("") == []

    def test_no_changes_diff(self) -> None:
        """A diff with no file changes should return empty."""
        diff = "diff --git a/a.py b/a.py\\n"
        # No +++ b/ line
        assert _parse_changed_files(diff) == []

    def test_skip_dev_null(self) -> None:
        """+++ b/dev/null should be skipped (deleted files)."""
        diff = """diff --git a/deleted.py b/deleted.py
deleted file mode 100644
--- a/deleted.py
+++ b/dev/null
@@ -1 +0,0 @@
-old_content
"""
        files = _parse_changed_files(diff)
        assert "dev/null" not in files
        assert files == []

    def test_duplicate_paths_deduplicated(self) -> None:
        """The same file appearing twice should be deduplicated."""
        diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10 +10 @@
-func1
+func2
"""
        files = _parse_changed_files(diff)
        assert len(files) == 1
        assert files == ["app.py"]


class TestDeduplicate:
    """Tests for _deduplicate()."""

    def test_exact_duplicate_removed(self) -> None:
        """Entries with same (file, line, category) should be deduplicated."""
        findings = [
            {"file_path": "app.py", "line_number": 2, "category": "security", "comment": "A"},
            {"file_path": "app.py", "line_number": 2, "category": "security", "comment": "B"},
        ]
        result = _deduplicate(findings)
        assert len(result) == 1

    def test_different_files_kept(self) -> None:
        """Different files should both be kept."""
        findings = [
            {"file_path": "a.py", "line_number": 2, "category": "bug", "comment": "A"},
            {"file_path": "b.py", "line_number": 2, "category": "bug", "comment": "B"},
        ]
        result = _deduplicate(findings)
        assert len(result) == 2

    def test_different_lines_kept(self) -> None:
        """Different line numbers should both be kept."""
        findings = [
            {"file_path": "a.py", "line_number": 2, "category": "bug", "comment": "A"},
            {"file_path": "a.py", "line_number": 5, "category": "bug", "comment": "B"},
        ]
        result = _deduplicate(findings)
        assert len(result) == 2

    def test_different_categories_kept(self) -> None:
        """Different categories on same file/line should both be kept."""
        findings = [
            {"file_path": "a.py", "line_number": 2, "category": "bug", "comment": "A"},
            {"file_path": "a.py", "line_number": 2, "category": "security", "comment": "B"},
        ]
        result = _deduplicate(findings)
        assert len(result) == 2

    def test_empty_list(self) -> None:
        """An empty list should return empty."""
        assert _deduplicate([]) == []

    def test_none_line_number(self) -> None:
        """Findings with None line numbers should be handled."""
        findings = [
            {"file_path": "a.py", "line_number": None, "category": "style", "comment": "A"},
            {"file_path": "a.py", "line_number": None, "category": "style", "comment": "B"},
        ]
        result = _deduplicate(findings)
        assert len(result) == 1


class TestBuildContextStr:
    """Tests for _build_context_str()."""

    def test_basic_context(self) -> None:
        """Basic repo context should be built."""
        ctx = GitHubRepoContext(
            full_name="owner/repo",
            default_branch="main",
        )
        result = _build_context_str(ctx)
        assert "main" in result

    def test_with_contributing(self) -> None:
        """CONTRIBUTING.md content should be included."""
        ctx = GitHubRepoContext(
            full_name="owner/repo",
            default_branch="main",
            has_contributing=True,
            contributing_content="# Contributing\nPlease write tests.",
        )
        result = _build_context_str(ctx)
        assert "Contributing" in result
        assert "write tests" in result

    def test_with_linter_config(self) -> None:
        """Linter config content should be included."""
        ctx = GitHubRepoContext(
            full_name="owner/repo",
            default_branch="main",
            has_linter_config=True,
            linter_config_content={".eslintrc": '{"rules": {"no-unused-vars": "error"}}'},
        )
        result = _build_context_str(ctx)
        assert ".eslintrc" in result

    def test_default_branch_only(self) -> None:
        """Minimal context with only default_branch."""
        ctx = GitHubRepoContext(full_name="owner/repo", default_branch="develop")
        result = _build_context_str(ctx)
        assert "develop" in result


# Integration Tests: review_pull_request task


SETTINGS = override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)


class TestReviewPullRequestTask:
    """Tests for the full review_pull_request Celery task with mocked deps."""

    @SETTINGS
    @patch("sentinel_review.workers.pipeline.GitHubClient")
    def test_private_repo_skipped(self, mock_github_client, db_installation, db) -> None:
        """Private repos without opt-in should be skipped."""
        Repo.objects.create(
            installation=db_installation,
            github_repo_id=999,
            full_name="testowner/private-repo",
            is_private=True,
            config={"private_repo_opt_in": False},
        )

        result = review_pull_request(
            installation_id=1001,
            repo_id=789,
            repo_full_name="testowner/testrepo",
            pr_number=42,
            is_private=True,
        )
        assert result["status"] == "skipped"
        assert "private_repo_not_opted_in" in result["reason"]

    @SETTINGS
    @patch("sentinel_review.workers.pipeline.GitHubClient")
    @patch("sentinel_review.workers.pipeline.get_llm_provider")
    def test_github_error_propagates(self, mock_get_llm, mock_github_client, db) -> None:
        """An error in the review pipeline should be caught."""
        # Setup: mock GitHub client to succeed, mock LLM to fail
        mock_client = MagicMock()
        mock_client.get_diff.return_value = "diff --git a/a.py b/a.py"
        mock_client.get_repo_context.return_value = GitHubRepoContext(
            full_name="test/error", default_branch="main"
        )
        mock_client.get_file_content.return_value = None
        mock_github_client.return_value = mock_client

        mock_provider = MagicMock()
        mock_provider.review_diff.side_effect = Exception("LLM API unavailable")
        mock_get_llm.return_value = mock_provider

        result = review_pull_request(
            installation_id=999999,
            repo_id=0,
            repo_full_name="test/error",
            pr_number=1,
            is_private=False,
        )
        assert result["status"] == "error"

    @SETTINGS
    @patch("sentinel_review.workers.pipeline.GitHubClient")
    @patch("sentinel_review.workers.pipeline.get_llm_provider")
    def test_full_pipeline(
        self,
        mock_get_llm,
        mock_github_client,
        db_installation,
        db,
        sample_diff: str,
    ) -> None:
        """The full pipeline should complete and produce comments."""
        mock_client = MagicMock()
        mock_client.get_diff.return_value = sample_diff
        mock_client.get_repo_context.return_value = GitHubRepoContext(
            full_name="testowner/testrepo",
            default_branch="main",
        )
        mock_client.get_file_content.return_value = "def foo():\n    pass"
        mock_client.post_review.return_value = {
            "id": 5001,
            "comments": [{"id": 3001}, {"id": 3002}],
        }
        mock_github_client.return_value = mock_client

        from sentinel_review.workers.llm import LLMResult
        from sentinel_review.workers.schemas import Finding

        mock_provider = MagicMock()
        mock_provider.review_diff.return_value = LLMResult(
            findings=[
                Finding(
                    file_path="app.py",
                    line_number=2,
                    category="security",
                    severity="blocking",
                    comment="SQL injection",
                    suggested_fix="Use parameterized queries.",
                ),
                Finding(
                    file_path="app.py",
                    line_number=8,
                    category="security",
                    severity="blocking",
                    comment="Another injection",
                ),
            ],
            total_tokens=500,
            latency_ms=1500,
        )
        mock_get_llm.return_value = mock_provider

        result = review_pull_request(
            installation_id=1001,
            repo_id=789,
            repo_full_name="testowner/testrepo",
            pr_number=42,
            pr_title="Test PR",
            pr_author="testuser",
            head_sha="abc123",
            base_sha="def456",
            is_private=False,
            account_login="testowner",
            action="opened",
        )

        assert result["status"] == "completed"
        assert result["findings_count"] == 2
        assert result["latency_ms"] > 0
        assert result["token_cost"] == 500

        assert Comment.objects.count() == 2
        comments = Comment.objects.all()
        assert comments[0].file_path == "app.py"
        assert comments[0].category == "security"
        assert comments[0].severity == "blocking"

        review = Review.objects.first()
        assert review is not None
        assert review.status == Review.Status.COMPLETED
        assert review.findings_count == 2
        assert review.latency_ms > 0
        assert review.token_cost == 500

    @SETTINGS
    @patch("sentinel_review.workers.pipeline.GitHubClient")
    @patch("sentinel_review.workers.pipeline.get_llm_provider")
    def test_no_findings_posts_clean_review(
        self, mock_get_llm, mock_github_client, db_installation, db, sample_diff_safe: str
    ) -> None:
        """When no issues are found, a clean review should be posted."""
        mock_client = MagicMock()
        mock_client.get_diff.return_value = sample_diff_safe
        mock_client.get_repo_context.return_value = GitHubRepoContext(
            full_name="testowner/testrepo", default_branch="main"
        )
        mock_client.get_file_content.return_value = "def foo(): pass"
        mock_client.post_review.return_value = {"id": 5002, "comments": []}
        mock_github_client.return_value = mock_client

        from sentinel_review.workers.llm import LLMResult

        mock_provider = MagicMock()
        mock_provider.review_diff.return_value = LLMResult(
            findings=[], total_tokens=100, latency_ms=500
        )
        mock_get_llm.return_value = mock_provider

        result = review_pull_request(
            installation_id=1001,
            repo_id=789,
            repo_full_name="testowner/testrepo",
            pr_number=43,
            is_private=False,
        )

        assert result["status"] == "completed"
        assert result["findings_count"] == 0
        mock_client.post_review.assert_called()
        call_kwargs = mock_client.post_review.call_args[1]
        assert call_kwargs["comments"] == []
        assert "No issues found" in call_kwargs.get("review_body", "")

    @SETTINGS
    @patch("sentinel_review.workers.pipeline.GitHubClient")
    def test_github_error_handled(self, mock_github_client, db_installation, db) -> None:
        """A GitHub API error should be recorded as failed."""
        mock_client = MagicMock()
        mock_client.get_diff.side_effect = Exception("GitHub API timeout")
        mock_github_client.return_value = mock_client

        result = review_pull_request(
            installation_id=1001,
            repo_id=789,
            repo_full_name="testowner/testrepo",
            pr_number=44,
            is_private=False,
        )

        assert result["status"] == "error"
        assert "GitHub" in result["error"]
        review = Review.objects.first()
        if review:
            assert review.status == Review.Status.FAILED
