"""
Tests for GitHub Actions execution mode (gha_runner.py).

Covers diff parsing, file content reading, finding parsing, deduplication,
review body generation, report output, and the main entry point.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sentinel_review.workers.gha_runner import (
    build_review_body,
    deduplicate,
    get_file_contents,
    main,
    parse_changed_files,
    parse_findings,
    run,
    save_report,
)

pytestmark = pytest.mark.slow
pytestmark = pytest.mark.integration

SAMPLE_DIFF = """diff --git a/app.py b/app.py
index abc123..def456 100644
--- a/app.py
+++ b/app.py
@@ -1,5 +1,7 @@
 def get_user(email):
-    query = "SELECT * FROM users WHERE email = %s" % email
+    query = f"SELECT * FROM users WHERE email = '{email}'"
     cursor.execute(query)
     return cursor.fetchone()

+def delete_user(user_id):
+    db.execute("DELETE FROM users WHERE id = " + str(user_id))
"""

SAMPLE_LLM_OUTPUT = """{
  "findings": [
    {
      "file_path": "app.py",
      "line_number": 2,
      "category": "security",
      "severity": "blocking",
      "comment": "SQL injection vulnerability",
      "suggested_fix": "Use parameterized queries"
    }
  ]
}"""

SAMPLE_EMPTY_FINDINGS = """{
  "findings": []
}"""


class TestDiffParsing:
    """Tests for parse_changed_files and get_diff."""

    def test_parse_changed_files(self) -> None:
        """Should extract changed file paths from diff."""
        files = parse_changed_files(SAMPLE_DIFF)
        assert "app.py" in files
        assert len(files) == 1

    def test_parse_changed_files_empty(self) -> None:
        """Empty diff should return empty list."""
        assert parse_changed_files("") == []

    def test_parse_changed_files_skips_dev_null(self) -> None:
        """DEV/NULL entries should be excluded."""
        diff = "+++ b/dev/null\n+++ b/real.py\n"
        files = parse_changed_files(diff)
        assert "real.py" in files
        assert len(files) == 1


class TestFileReading:
    """Tests for get_file_contents."""

    def test_get_file_contents_existing(self) -> None:
        """Existing files should be read."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                file_path = Path(tmpdir) / "test.py"
                file_path.write_text("print('hello')")

                diff = "+++ b/test.py\n"
                contents = get_file_contents(diff)
                assert "test.py" in contents
                assert contents["test.py"] == "print('hello')"
            finally:
                os.chdir(orig_cwd)

    def test_get_file_contents_missing(self) -> None:
        """Missing files should not be in the result."""
        diff = "+++ b/nonexistent.py\n"
        contents = get_file_contents(diff)
        assert contents == {}

    def test_get_file_contents_empty(self) -> None:
        """Empty diff should return empty dict."""
        assert get_file_contents("") == {}


class TestFindingParsing:
    """Tests for parse_findings."""

    def test_parse_valid(self) -> None:
        """Valid LLM JSON output should parse correctly."""
        findings = parse_findings(SAMPLE_LLM_OUTPUT)
        assert len(findings) == 1
        assert findings[0]["file_path"] == "app.py"
        assert findings[0]["line_number"] == 2
        assert findings[0]["category"] == "security"
        assert findings[0]["suggested_fix"] == "Use parameterized queries"

    def test_parse_empty(self) -> None:
        """Empty findings array should work."""
        findings = parse_findings(SAMPLE_EMPTY_FINDINGS)
        assert findings == []

    def test_parse_malformed(self) -> None:
        """Malformed JSON should return empty list."""
        assert parse_findings("not json at all") == []

    def test_parse_code_block_json(self) -> None:
        """JSON wrapped in ```json code blocks should be parsed."""
        output = "```json\n" + SAMPLE_LLM_OUTPUT + "\n```"
        findings = parse_findings(output)
        assert len(findings) == 1

    def test_parse_code_block_bare(self) -> None:
        """JSON wrapped in bare ``` (no prefix) should be parsed."""
        output = "```\n" + SAMPLE_LLM_OUTPUT + "\n```"
        findings = parse_findings(output)
        assert len(findings) == 1

    def test_parse_invalid_schema(self) -> None:
        """JSON that doesn't match the schema should return empty list."""
        assert parse_findings('{"wrong": "structure"}') == []


class TestDeduplication:
    """Tests for deduplicate."""

    def test_deduplicate_identical(self) -> None:
        """Identical findings should be collapsed."""
        findings = [
            {"file_path": "a.py", "line_number": 1, "category": "bug"},
            {"file_path": "a.py", "line_number": 1, "category": "bug"},
        ]
        result = deduplicate(findings)
        assert len(result) == 1

    def test_deduplicate_different_file(self) -> None:
        """Same line, different file → keep both."""
        findings = [
            {"file_path": "a.py", "line_number": 1, "category": "bug"},
            {"file_path": "b.py", "line_number": 1, "category": "bug"},
        ]
        result = deduplicate(findings)
        assert len(result) == 2

    def test_deduplicate_different_category(self) -> None:
        """Same file/line, different category → keep both."""
        findings = [
            {"file_path": "a.py", "line_number": 1, "category": "bug"},
            {"file_path": "a.py", "line_number": 1, "category": "security"},
        ]
        result = deduplicate(findings)
        assert len(result) == 2

    def test_deduplicate_empty(self) -> None:
        """Empty list should return empty list."""
        assert deduplicate([]) == []


class TestReviewBody:
    """Tests for build_review_body."""

    def test_build_body_with_findings(self) -> None:
        """Review body should include severity and category counts."""
        findings = [
            {"severity": "blocking", "category": "security"},
            {"severity": "warning", "category": "bug"},
        ]
        body = build_review_body(findings, 2)
        assert "Sentinel Review Complete" in body
        assert "1 blocking" in body
        assert "1 warnings" in body

    def test_build_body_empty(self) -> None:
        """Empty findings should produce a minimal body."""
        body = build_review_body([], 0)
        assert "0" in body


class TestReportSaving:
    """Tests for save_report."""

    def test_save_report_creates_file(self) -> None:
        """Report should be saved as JSON."""
        report = {"status": "completed", "findings": []}
        path = save_report(report, "owner/repo", 42)
        assert path.exists()
        assert "owner-repo" in path.name
        assert "pr42" in path.name
        saved = json.loads(path.read_text())
        assert saved["status"] == "completed"
        path.unlink()


class TestMainEntryPoint:
    """Tests for the main() and run() entry points."""

    def test_main_missing_repo(self) -> None:
        """Should fail fast when GITHUB_REPOSITORY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = main()
            assert result == 1

    def test_main_missing_event(self) -> None:
        """Should fail fast when GITHUB_EVENT_PATH is not set."""
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}, clear=True):
            result = main()
            assert result == 1

    def test_run_non_pr_event(self) -> None:
        """Non-PR actions (push, issues) should be skipped."""
        result = run("owner/repo", {"action": "push"})
        assert result == 0

    def test_run_no_pr_number(self) -> None:
        """Event without PR number should fail gracefully."""
        result = run("owner/repo", {"action": "opened", "pull_request": {}})
        assert result == 1

    @patch("sentinel_review.workers.gha_runner.get_diff")
    @patch("sentinel_review.workers.gha_runner.get_file_contents")
    @patch("sentinel_review.workers.gha_runner._call_anthropic")
    @patch("sentinel_review.workers.gha_runner.GHAClient")
    def test_run_full_happy_path_anthropic(
        self, mock_client_cls, mock_anthropic, mock_contents, mock_diff
    ) -> None:
        """Full pipeline with Anthropic should complete successfully."""
        mock_diff.return_value = SAMPLE_DIFF
        mock_contents.return_value = {"app.py": "def foo(): pass"}
        mock_anthropic.return_value = {
            "raw_output": SAMPLE_LLM_OUTPUT,
            "total_tokens": 500,
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
        }
        mock_client = MagicMock()
        mock_client.post_review.return_value = {"id": 123, "comments": [{"id": 456}]}
        mock_client_cls.return_value = mock_client

        # Set API key
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            result = run(
                "owner/repo",
                {
                    "action": "opened",
                    "pull_request": {"number": 42, "title": "Test PR"},
                },
            )

        assert result == 0
        mock_client.post_review.assert_called_once()
        args = mock_client.post_review.call_args[0]
        assert args[0] == "owner/repo"
        assert args[1] == 42
        assert len(args[2]) == 1  # 1 comment
