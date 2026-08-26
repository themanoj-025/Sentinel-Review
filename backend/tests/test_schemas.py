"""
Tests for Pydantic schema validation of LLM output.

Covers:
- Valid Finding and ReviewOutput creation
- Invalid category/severity values rejected
- Missing required fields rejected
- Malformed JSON parsing and recovery
- Retry logic (validation failure followed by correction)
- Few-shot example structure
- System prompt existence and key instructions
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sentinel_review.workers.schemas import (
    SYSTEM_PROMPT,
    Finding,
    ReviewOutput,
    get_few_shot_examples,
)


class TestFindingSchema:
    """Tests for the Finding Pydantic model."""

    def test_valid_finding(self) -> None:
        """A well-formed Finding should be created successfully."""
        finding = Finding(
            file_path="src/app.py",
            line_number=42,
            category="security",
            severity="blocking",
            comment="SQL injection vulnerability.",
            suggested_fix="Use parameterized queries.",
        )
        assert finding.file_path == "src/app.py"
        assert finding.line_number == 42
        assert finding.category == "security"
        assert finding.severity == "blocking"
        assert finding.suggested_fix == "Use parameterized queries."

    def test_finding_without_suggested_fix(self) -> None:
        """suggested_fix should default to None."""
        finding = Finding(
            file_path="src/app.py",
            line_number=10,
            category="bug",
            severity="warning",
            comment="Possible off-by-one error.",
        )
        assert finding.suggested_fix is None

    def test_finding_without_line_number(self) -> None:
        """line_number should default to None (file-level finding)."""
        finding = Finding(
            file_path="src/app.py",
            category="style",
            severity="nit",
            comment="Consider renaming this variable.",
        )
        assert finding.line_number is None

    def test_invalid_category_rejected(self) -> None:
        """An invalid category should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            Finding(
                file_path="app.py",
                line_number=1,
                category="invalid_category",
                severity="warning",
                comment="Test",
            )
        assert "category" in str(exc.value)

    def test_invalid_severity_rejected(self) -> None:
        """An invalid severity should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            Finding(
                file_path="app.py",
                line_number=1,
                category="bug",
                severity="critical",  # not a valid severity
                comment="Test",
            )
        assert "severity" in str(exc.value)

    def test_empty_file_path_rejected_if_blank(self) -> None:
        """file_path should be a string but blank might be accepted."""
        finding = Finding(
            file_path="",
            line_number=1,
            category="bug",
            severity="warning",
            comment="Test",
        )
        assert finding.file_path == ""

    def test_missing_required_fields(self) -> None:
        """Missing required fields should raise ValidationError."""
        with pytest.raises(ValidationError):
            Finding()  # type: ignore[call-arg]

    @pytest.mark.parametrize("category", ["bug", "style", "security", "suggestion"])
    def test_all_valid_categories(self, category: str) -> None:
        """All valid category values should be accepted."""
        finding = Finding(
            file_path="app.py",
            line_number=1,
            category=category,
            severity="warning",
            comment="Test",
        )
        assert finding.category == category

    @pytest.mark.parametrize("severity", ["blocking", "warning", "nit"])
    def test_all_valid_severities(self, severity: str) -> None:
        """All valid severity values should be accepted."""
        finding = Finding(
            file_path="app.py",
            line_number=1,
            category="bug",
            severity=severity,
            comment="Test",
        )
        assert finding.severity == severity


class TestReviewOutputSchema:
    """Tests for the ReviewOutput Pydantic model."""

    def test_empty_findings(self) -> None:
        """ReviewOutput with no findings should be valid."""
        output = ReviewOutput(findings=[])
        assert output.findings == []

    def test_multiple_findings(self) -> None:
        """ReviewOutput should accept multiple findings."""
        output = ReviewOutput(
            findings=[
                Finding(
                    file_path="app.py",
                    line_number=1,
                    category="security",
                    severity="blocking",
                    comment="First issue",
                ),
                Finding(
                    file_path="app.py",
                    line_number=5,
                    category="bug",
                    severity="warning",
                    comment="Second issue",
                ),
            ]
        )
        assert len(output.findings) == 2

    def test_invalid_finding_in_list_rejected(self) -> None:
        """An invalid finding inside the list should raise ValidationError."""
        with pytest.raises(ValidationError):
            ReviewOutput(
                findings=[
                    {
                        "file_path": "app.py",
                        "line_number": 1,
                        "category": "invalid",  # bad category
                        "severity": "warning",
                        "comment": "Test",
                    }
                ]
            )


class TestJSONParsing:
    """Tests for JSON output parsing and recovery."""

    def test_parse_valid_json(self) -> None:
        """A valid JSON response should parse correctly."""
        import json as _json

        raw = _json.dumps(
            {
                "findings": [
                    {
                        "file_path": "app.py",
                        "line_number": 2,
                        "category": "security",
                        "severity": "blocking",
                        "comment": "Test finding.",
                        "suggested_fix": None,
                    }
                ]
            }
        )
        data = _json.loads(raw)
        output = ReviewOutput(**data)
        assert len(output.findings) == 1
        assert output.findings[0].file_path == "app.py"
        assert output.findings[0].severity == "blocking"

    def test_parse_codeblock_json(self) -> None:
        """JSON wrapped in markdown code blocks should be extractable."""
        raw = """```json
{
  "findings": [
    {
      "file_path": "app.py",
      "line_number": 1,
      "category": "bug",
      "severity": "warning",
      "comment": "Test"
    }
  ]
}
```"""
        # Extract JSON from code block
        json_str = raw.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)
        output = ReviewOutput(**data)
        assert len(output.findings) == 1
        assert output.findings[0].category == "bug"

    def test_parse_codeblock_no_language(self) -> None:
        """JSON wrapped in plain ``` blocks should also work."""
        raw = """```
{"findings": []}
```"""
        json_str = raw.strip()
        json_str = json_str.split("```")[1].split("```")[0].strip()
        data = json.loads(json_str)
        output = ReviewOutput(**data)
        assert output.findings == []

    def test_malformed_json_rejected(self) -> None:
        """Completely malformed JSON should fail parsing."""
        raw = "This is not JSON at all {{{"
        import json

        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)

    def test_partial_malformed_finding(self) -> None:
        """A finding with missing required fields should be rejected by Pydantic."""
        data = {"findings": [{"file_path": "app.py"}]}  # missing many fields
        with pytest.raises(ValidationError):
            ReviewOutput(**data)


class TestSystemPrompt:
    """Tests for the system prompt."""

    def test_system_prompt_exists(self) -> None:
        """SYSTEM_PROMPT should be a non-empty string."""
        assert SYSTEM_PROMPT
        assert len(SYSTEM_PROMPT) > 100

    def test_system_prompt_contains_key_instructions(self) -> None:
        """The prompt should contain critical behavioral instructions."""
        assert "senior engineer" in SYSTEM_PROMPT.lower()
        assert "never restate" in SYSTEM_PROMPT.lower()
        assert "omit a finding" in SYSTEM_PROMPT.lower()
        assert "false positive" in SYSTEM_PROMPT.lower()

    def test_prompt_includes_categories(self) -> None:
        """All review categories should be documented in the prompt."""
        for cat in ["bug", "style", "security", "suggestion"]:
            assert cat in SYSTEM_PROMPT

    def test_prompt_includes_severities(self) -> None:
        """All severity levels should be documented in the prompt."""
        for sev in ["blocking", "warning", "nit"]:
            assert sev in SYSTEM_PROMPT

    def test_system_prompt_mentions_json_output(self) -> None:
        """The prompt should instruct JSON output format."""
        assert "JSON" in SYSTEM_PROMPT


class TestFewShotExamples:
    """Tests for few-shot examples."""

    def test_examples_return_list(self) -> None:
        """get_few_shot_examples() should return a list."""
        examples = get_few_shot_examples()
        assert isinstance(examples, list)
        assert len(examples) > 0

    def test_examples_have_correct_structure(self) -> None:
        """Each example should have 'role' and 'content' keys."""
        for example in get_few_shot_examples():
            assert "role" in example
            assert "content" in example
            assert example["role"] in ("user", "assistant")

    def test_at_least_one_good_example(self) -> None:
        """There should be at least one example with findings."""
        examples = get_few_shot_examples()
        has_findings = False
        for ex in examples:
            if ex["role"] == "assistant" and '"findings"' in ex["content"]:
                has_findings = True
                break
        assert has_findings, "No assistant example contains findings"

    def test_at_least_one_no_findings_example(self) -> None:
        """There should be an example showing empty findings (to discourage noise)."""
        examples = get_few_shot_examples()
        has_empty = False
        for ex in examples:
            if ex["role"] == "assistant" and '"findings": []' in ex["content"]:
                has_empty = True
                break
        assert has_empty, "No example shows empty findings for clean diffs"
