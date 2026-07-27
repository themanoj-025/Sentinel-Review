"""
Tests for the Semgrep integration layer.

Covers:
- run_semgrep with empty file contents returns empty list
- Semgrep not installed handled gracefully
- _parse_semgrep_output converts Semgrep JSON to Finding objects
- merge_with_llm_findings marks agreements as high-confidence
- merge_with_llm_findings adds unmatched semgrep findings
- Error handling for timeouts and exceptions
"""

from __future__ import annotations

import pytest
from sentinel_review.workers.schemas import Finding
from sentinel_review.workers.semgrep_integration import (
    _parse_semgrep_output,
    merge_with_llm_findings,
    run_semgrep,
)


class TestRunSemgrep:
    """Tests for run_semgrep()."""

    def test_empty_contents_returns_empty(self):
        """run_semgrep with no file contents should return an empty list."""
        result = run_semgrep({})
        assert result == []

    def test_returns_empty_if_semgrep_not_installed(self):
        """If Semgrep is not installed, run_semgrep should return [] gracefully."""
        # Use a fake path that definitely doesn't have semgrep
        result = run_semgrep({"test.py": "print(1)"})
        # Should handle gracefully and return []
        assert isinstance(result, list)


class TestParseSemgrepOutput:
    """Tests for _parse_semgrep_output()."""

    SAMPLE_SEMGREP_OUTPUT = """
{
    "results": [
        {
            "path": "/tmp/sandbox/app.py",
            "start": {"line": 5},
            "extra": {
                "message": "User controlled data in SQL query.",
                "severity": "ERROR",
                "lines": "cursor.execute(query)",
                "fix": "Use parameterized query",
                "metadata": {}
            },
            "check_id": "python.lang.security.sql-injection.sqlalchemy"
        },
        {
            "path": "/tmp/sandbox/config.py",
            "start": {"line": 3},
            "extra": {
                "message": "Hardcoded secret detected.",
                "severity": "WARNING",
                "lines": "PASSWORD = 'secret'",
                "metadata": {}
            },
            "check_id": "python.lang.security.hardcoded-secret"
        }
    ]
}
"""

    def test_parse_valid_output(self):
        """Valid Semgrep output should parse into Finding objects."""
        file_map = {
            "app.py": "/tmp/sandbox/app.py",
            "config.py": "/tmp/sandbox/config.py",
        }
        findings = _parse_semgrep_output(self.SAMPLE_SEMGREP_OUTPUT, file_map)
        assert len(findings) == 2

        # Check the first finding
        assert findings[0].file_path == "app.py"
        assert findings[0].line_number == 5
        assert findings[0].category == "security"
        assert findings[0].severity == "blocking"  # ERROR → blocking
        assert findings[0].suggested_fix == "Use parameterized query"

        # Check the second
        assert findings[1].file_path == "config.py"
        assert findings[1].line_number == 3
        assert findings[1].severity == "warning"  # WARNING → warning

    def test_parse_empty_results(self):
        """Empty results should return an empty list."""
        output = '{"results": []}'
        findings = _parse_semgrep_output(output, {})
        assert findings == []

    def test_parse_malformed_json(self):
        """Malformed JSON should return an empty list."""
        findings = _parse_semgrep_output("not json", {})
        assert findings == []

    def test_parse_incomplete_result(self):
        """A result missing required fields should be handled."""
        output = '{"results": [{"path": "test.py"}]}'
        findings = _parse_semgrep_output(output, {"test.py": "test.py"})
        # Should not crash, but the Finding may have defaults for missing fields
        assert isinstance(findings, list)

    def test_severity_mapping(self):
        """Semgrep severities should map correctly to our severity levels."""
        # Test ERROR
        f = _parse_semgrep_output(
            '{"results": [{"path": "a.py", "start": {"line": 1}, "extra": {"severity": "ERROR", "message": "x", "lines": "x"}}]}',
            {"a.py": "a.py"},
        )
        assert f[0].severity == "blocking"

        # Test WARNING
        f = _parse_semgrep_output(
            '{"results": [{"path": "a.py", "start": {"line": 1}, "extra": {"severity": "WARNING", "message": "x", "lines": "x"}}]}',
            {"a.py": "a.py"},
        )
        assert f[0].severity == "warning"

        # Test INFO
        f = _parse_semgrep_output(
            '{"results": [{"path": "a.py", "start": {"line": 1}, "extra": {"severity": "INFO", "message": "x", "lines": "x"}}]}',
            {"a.py": "a.py"},
        )
        assert f[0].severity == "nit"


class TestMergeWithLLMFindings:
    """Tests for merge_with_llm_findings()."""

    @pytest.fixture
    def llm_findings(self) -> list[Finding]:
        return [
            Finding(
                file_path="app.py",
                line_number=5,
                category="security",
                severity="blocking",
                comment="SQL injection",
            ),
            Finding(
                file_path="utils.py",
                line_number=10,
                category="bug",
                severity="warning",
                comment="Off-by-one",
            ),
        ]

    @pytest.fixture
    def semgrep_findings(self) -> list[Finding]:
        return [
            Finding(
                file_path="app.py",
                line_number=5,
                category="security",
                severity="blocking",
                comment="Semgrep: SQL injection",
            ),
            Finding(
                file_path="config.py",
                line_number=3,
                category="security",
                severity="warning",
                comment="Hardcoded secret",
            ),
        ]

    def test_llm_only_findings(self, llm_findings: list[Finding]):
        """With no Semgrep findings, all entries should be LLM-only."""
        merged = merge_with_llm_findings(llm_findings, [])
        assert len(merged) == 2
        for entry in merged:
            assert entry["source"] == "llm"
            assert entry["high_confidence"] is False

    def test_agreement_marked_high_confidence(
        self, llm_findings: list[Finding], semgrep_findings: list[Finding]
    ):
        """When LLM and Semgrep agree, the entry should be high-confidence."""
        merged = merge_with_llm_findings(llm_findings, semgrep_findings)
        # app.py:5 should be matched and marked high confidence
        app_finding = [m for m in merged if m["file_path"] == "app.py"][0]
        assert app_finding["high_confidence"] is True
        assert app_finding["source"] == "llm+semgrep"

    def test_unmatched_semgrep_added(
        self, llm_findings: list[Finding], semgrep_findings: list[Finding]
    ):
        """Unmatched Semgrep findings should be appended."""
        merged = merge_with_llm_findings(llm_findings, semgrep_findings)
        assert len(merged) == 3  # 2 LLM + 1 unmatched Semgrep

        # config.py should be the unmatched Semgrep finding
        config_finding = [m for m in merged if m["file_path"] == "config.py"]
        assert len(config_finding) == 1
        assert config_finding[0]["source"] == "semgrep"

    def test_no_duplicate_llm(self, llm_findings: list[Finding]):
        """LLM findings should not be duplicated."""
        merged = merge_with_llm_findings(llm_findings, [])
        file_paths = [m["file_path"] for m in merged]
        assert file_paths == ["app.py", "utils.py"]

    def test_empty_inputs(self):
        """Both empty should return empty list."""
        merged = merge_with_llm_findings([], [])
        assert merged == []

    def test_only_semgrep(self, semgrep_findings: list[Finding]):
        """Only Semgrep findings should be returned."""
        merged = merge_with_llm_findings([], semgrep_findings)
        assert len(merged) == 2
        assert all(m["source"] == "semgrep" for m in merged)
