"""
Tests for .sentinel-ignore file support (workers/ignore_rules.py).

Covers parsing, pattern matching, and finding filtering.
"""

from __future__ import annotations

from sentinel_review.workers.ignore_rules import (
    filter_ignored_findings,
    is_ignored,
    parse_ignore_file,
)


class TestParsing:
    """Tests for parse_ignore_file."""

    def test_empty_content(self):
        """Empty content should return empty patterns."""
        assert parse_ignore_file("") == []

    def test_only_comments(self):
        """Only comments should return empty patterns."""
        content = "# This is a comment\n# Another comment\n"
        assert parse_ignore_file(content) == []

    def test_single_pattern(self):
        """Single pattern should be returned."""
        content = "*.generated.py\n"
        patterns = parse_ignore_file(content)
        assert patterns == ["*.generated.py"]

    def test_multiple_patterns(self):
        """Multiple patterns should be returned."""
        content = "*.generated.py\nnode_modules/\n*.test.js\n"
        patterns = parse_ignore_file(content)
        assert patterns == ["*.generated.py", "node_modules/", "*.test.js"]

    def test_inline_comment(self):
        """Inline comments after patterns should be stripped."""
        content = "*.generated.py  # Ignore generated files\nnode_modules/  # Node deps\n"
        patterns = parse_ignore_file(content)
        assert patterns == ["*.generated.py", "node_modules/"]

    def test_blank_lines_skipped(self):
        """Blank lines should be skipped."""
        content = "*.generated.py\n\nnode_modules/\n"
        patterns = parse_ignore_file(content)
        assert patterns == ["*.generated.py", "node_modules/"]

    def test_whitespace_handling(self):
        """Trailing whitespace should be stripped."""
        content = "  *.generated.py  \n"
        patterns = parse_ignore_file(content)
        assert patterns == ["*.generated.py"]


class TestMatching:
    """Tests for is_ignored."""

    def test_simple_filename_pattern(self):
        """Simple filename glob should match."""
        assert is_ignored("build/output.generated.py", ["*.generated.py"])
        assert is_ignored("src/data.generated.py", ["*.generated.py"])

    def test_directory_pattern(self):
        """Directory pattern (ending with /) should match files inside."""
        assert is_ignored("node_modules/foo/bar.js", ["node_modules/"])
        assert is_ignored("node_modules/foo.js", ["node_modules/"])

    def test_nested_path_pattern(self):
        """Nested path pattern with / should match correctly."""
        assert is_ignored("docs/api/readme.md", ["docs/*.md"])

    def test_specific_file_pattern(self):
        """Specific file pattern should match exact file."""
        assert is_ignored("src/secret.py", ["src/secret.py"])

    def test_no_match(self):
        """File not matching any pattern should return False."""
        assert not is_ignored("src/app.py", ["*.generated.py", "node_modules/"])

    def test_empty_patterns(self):
        """Empty patterns list should return False."""
        assert not is_ignored("src/app.py", [])

    def test_wildcard_directory(self):
        """Wildcard directory pattern should match."""
        patterns = ["*/generated/*"]
        assert is_ignored("src/generated/output.py", patterns)
        assert not is_ignored("src/app.py", patterns)

    def test_multiple_extensions(self):
        """Multiple extension patterns should work."""
        patterns = ["*.log", "*.tmp", "*.cache"]
        assert is_ignored("debug.log", patterns)
        assert is_ignored("data.tmp", patterns)
        assert not is_ignored("app.py", patterns)

    def test_path_normalization(self):
        """Backslash paths should be normalized."""
        patterns = ["src/ignored/*"]
        assert is_ignored("src\\ignored\\file.py", patterns)

    def test_filename_only_pattern(self):
        """Pattern without / should match filename anywhere in path."""
        assert is_ignored("src/foo/bar/test.log", ["*.log"])

    def test_no_false_positive_for_non_matching_directory(self):
        """Non-matching directory pattern should not match."""
        assert not is_ignored("src/app.py", ["build/"])

    def test_subdirectory_pattern(self):
        """Pattern with subdirectory should match nested paths."""
        assert is_ignored("vendor/lib/foo.py", ["vendor/*"])
        assert is_ignored("vendor/foo.py", ["vendor/*"])

    def test_empty_file_path(self):
        """Empty file path should not match anything."""
        assert not is_ignored("", ["*.py"])


class TestFiltering:
    """Tests for filter_ignored_findings."""

    def test_filter_single_finding(self):
        """A finding in an ignored file should be removed."""
        findings = [{"file_path": "src/foo.generated.py", "line_number": 1, "category": "bug"}]
        result = filter_ignored_findings(findings, ["*.generated.py"])
        assert len(result) == 0

    def test_keep_non_matching(self):
        """Findings not matching any pattern should be kept."""
        findings = [
            {"file_path": "src/app.py", "line_number": 1, "category": "bug"},
            {"file_path": "src/data.generated.py", "line_number": 2, "category": "security"},
        ]
        result = filter_ignored_findings(findings, ["*.generated.py"])
        assert len(result) == 1
        assert result[0]["file_path"] == "src/app.py"

    def test_no_patterns(self):
        """Empty patterns should keep all findings."""
        findings = [{"file_path": "src/app.py", "line_number": 1, "category": "bug"}]
        result = filter_ignored_findings(findings, [])
        assert len(result) == 1

    def test_empty_findings(self):
        """Empty findings list should return empty list."""
        assert filter_ignored_findings([], ["*.py"]) == []

    def test_multiple_ignored_files(self):
        """Multiple findings in ignored files should all be removed."""
        findings = [
            {"file_path": "node_modules/foo.js", "line_number": 1, "category": "bug"},
            {"file_path": "node_modules/bar.js", "line_number": 2, "category": "security"},
            {"file_path": "src/app.py", "line_number": 3, "category": "suggestion"},
        ]
        result = filter_ignored_findings(findings, ["node_modules/"])
        assert len(result) == 1
        assert result[0]["file_path"] == "src/app.py"

    def test_mixed_ignored_and_kept(self):
        """Mixed patterns should correctly filter."""
        findings = [
            {"file_path": "src/app.py", "line_number": 1, "category": "bug"},
            {"file_path": "build/output.py", "line_number": 2, "category": "security"},
            {"file_path": "src/test_app.py", "line_number": 3, "category": "style"},
        ]
        patterns = ["build/*", "*/test_*"]
        result = filter_ignored_findings(findings, patterns)
        assert len(result) == 1
        assert result[0]["file_path"] == "src/app.py"
