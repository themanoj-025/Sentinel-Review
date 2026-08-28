#!/usr/bin/env python3
"""
Sentinel Review — Evaluation Runner (run_evaluation.py)

Loads data/eval_set.json, runs the review pipeline against each fixture,
computes precision/recall/F1 against known_issues, and optionally writes
an updated evaluation report to docs/evaluation-report.md.

Two modes:
  mock    — Uses a built-in rule-based analyzer (no API keys needed).
            Demonstrates the evaluation harness works end-to-end.
  live    — Uses the actual LLM provider (Anthropic or OpenAI).
            Requires ANTHROPIC_API_KEY or OPENAI_API_KEY in env.

Usage:
    # Mock mode (default) — fast, no API keys needed
    python scripts/run_evaluation.py

    # Live mode — requires LLM API key
    python scripts/run_evaluation.py --mode live --model claude-sonnet-4-20250514

    # Write results back to the evaluation report
    python scripts/run_evaluation.py --output docs/evaluation-report.md

    # Verbose — show per-fixture details
    python scripts/run_evaluation.py -v
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# Paths

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_SET_PATH = PROJECT_ROOT / "data" / "eval_set.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "evaluation-report.md"

# Data Structures


class MatchResult(Enum):
    TP = "TP"  # True Positive: finding matches a known issue
    FP = "FP"  # False Positive: finding doesn't match any known issue
    FN = "FN"  # False Negative: known issue with no matching finding


@dataclass
class Finding:
    """Mirrors Finding from schemas.py for standalone evaluation."""

    file_path: str
    line_number: int | None
    category: str
    severity: str
    comment: str
    suggested_fix: str | None = None
    source: str = "mock"


@dataclass
class EvalEntry:
    """A single evaluation entry with its findings and scores."""

    fixture_id: str
    known_issues: list[dict[str, Any]]
    mock_findings: list[Finding] = field(default_factory=list)
    live_findings: list[Finding] | None = None
    true_positives: list[dict] = field(default_factory=list)
    false_positives: list[Finding] = field(default_factory=list)
    false_negatives: list[dict] = field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    latency_ms: int = 0


# Mock LLM Provider — rule-based analyzer for offline evaluation


def _mock_review_diff(diff: str) -> list[Finding]:
    """Run a rule-based analysis on the diff to produce simulated findings.

    This mimics what the LLM would produce, using pattern matching for:
    - SQL injection (f-strings with SQL, string concatenation)
    - Hardcoded secrets (API keys, passwords, SECRET_KEY)
    - Unsafe deserialization (pickle.loads)
    - Off-by-one errors (range(1, len+1))
    - Missing zero-division checks (a/b without b==0 guard)
    """
    findings: list[Finding] = []
    lines = diff.split("\n")

    # Track '+' lines (additions in the diff) with their line numbers
    added_lines: list[tuple[int, str]] = []
    current_line_num = 0
    in_hunk = False

    for line in lines:
        # Parse hunk headers to track line numbers
        if line.startswith("@@"):
            in_hunk = True
            # @@ -old_start,old_count +new_start,new_count @@
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            current_line_num = int(match.group(1)) if match else 0
            continue

        if not in_hunk:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append((current_line_num, line[1:]))  # strip the '+'
            current_line_num += 1
        elif line.startswith("-"):
            pass  # removed lines don't exist in the new file — don't increment
        elif not line.startswith("+"):
            current_line_num += 1

    # SQL Injection detection
    sql_keywords = ["select", "insert", "update", "delete", "exec", "execute"]
    for line_num, content in added_lines:
        lower = content.lower().strip()
        # f-string with SQL
        has_sql = any(kw in lower for kw in sql_keywords)
        has_fstring = 'f"' in content or "f'" in content
        has_concat = "+" in content and ("str(" in content or '"' in content or "'" in content)
        if has_sql and (has_fstring or has_concat):
            # Check if already added a finding for this line/file
            if not any(f.line_number == line_num and f.category == "security" for f in findings):
                finding = Finding(
                    file_path=_infer_file_path(lines),
                    line_number=line_num,
                    category="security",
                    severity="blocking",
                    comment=(
                        "SQL injection vulnerability — user input is interpolated "
                        "directly into the query string rather than parameterized."
                    ),
                    suggested_fix=(
                        "Use parameterized queries: "
                        "`cursor.execute('SELECT ... WHERE col = %s', (value,))`"
                    ),
                )
                findings.append(finding)

    # Hardcoded Secret detection
    secret_patterns = [
        (r"(?i)(api[_-]?secret|api[_-]?key)\s*=\s*['\"](sk-|ghp_)", "API secret key"),
        (r"(?i)(password|passwd)\s*=\s*['\"][^'\"]{6,}['\"]", "hardcoded password"),
        (r"(?i)(secret_key|secretkey)\s*=\s*['\"][^'\"]{8,}['\"]", "Django SECRET_KEY"),
    ]
    for line_num, content in added_lines:
        for pattern, description in secret_patterns:
            if re.search(pattern, content):
                if not any(
                    f.line_number == line_num
                    and f.category == "security"
                    and description in f.comment
                    for f in findings
                ):
                    findings.append(
                        Finding(
                            file_path=_infer_file_path(lines),
                            line_number=line_num,
                            category="security",
                            severity="blocking",
                            comment=f"Hardcoded {description} committed to source code.",
                            suggested_fix="Load secrets from environment variables or a secrets manager.",
                        )
                    )

    # Unsafe Deserialization detection
    for line_num, content in added_lines:
        if "pickle.load" in content:
            if not any(f.line_number == line_num and "pickle" in f.comment for f in findings):
                findings.append(
                    Finding(
                        file_path=_infer_file_path(lines),
                        line_number=line_num,
                        category="security",
                        severity="blocking",
                        comment=(
                            "Unsafe deserialization with pickle.loads on untrusted input — "
                            "can lead to remote code execution (CWE-502)."
                        ),
                        suggested_fix=(
                            "Replace pickle with a safer serialization format such as JSON, "
                            "or sign the pickle data with HMAC before deserializing."
                        ),
                    )
                )

    # Off-by-One / Index Error detection
    for line_num, content in added_lines:
        # range(1, len(items) + 1)  ← off by one (should be just len(items))
        if re.search(r"range\s*\(\s*1\s*,\s*len\s*\(.*?\)\s*\+\s*1\s*\)", content):
            if not any(f.line_number == line_num and "off-by-one" in f.comment for f in findings):
                findings.append(
                    Finding(
                        file_path=_infer_file_path(lines),
                        line_number=line_num,
                        category="bug",
                        severity="blocking",
                        comment=(
                            "Off-by-one error: range(1, len(items) + 1) goes one beyond "
                            "the last index, causing an IndexError."
                        ),
                        suggested_fix="Use `range(0, len(items))` or `enumerate(items)`.",
                    )
                )

        # items[i] access that may go out of bounds
        if re.search(r"items\s*\[", content) and not re.search(r"len|range|for", content):
            if not any(
                f.line_number == line_num and "out of bounds" in f.comment for f in findings
            ):
                findings.append(
                    Finding(
                        file_path=_infer_file_path(lines),
                        line_number=line_num,
                        category="bug",
                        severity="warning",
                        comment=(
                            "Potentially accessing list index that may be out of bounds "
                            "(see off-by-one in preceding loop range)."
                        ),
                    )
                )

    # Missing Zero Division Guard detection
    for line_num, content in added_lines:
        if re.search(r"return\s+.+/", content) and "if b == 0" not in content:
            if not any(
                f.line_number == line_num and "zero-division" in f.comment for f in findings
            ):
                findings.append(
                    Finding(
                        file_path=_infer_file_path(lines),
                        line_number=line_num,
                        category="bug",
                        severity="blocking",
                        comment=(
                            "Division by zero guard missing — passing b=0 will raise "
                            "a ZeroDivisionError at runtime."
                        ),
                        suggested_fix="Add a check: `if b == 0: return None` (or appropriate error handling).",
                    )
                )

    return findings


def _infer_file_path(diff_lines: list[str]) -> str:
    """Extract file path from diff +++ line."""
    for line in diff_lines:
        if line.startswith("+++ b/"):
            return line[6:].strip()
    return "unknown.py"


# Live LLM Provider (optional — requires API key)


def _live_review_diff(
    diff: str,
    provider: str = "anthropic",
    model: str | None = None,
) -> list[Finding]:
    """Run the actual LLM review pipeline against a diff.

    Requires ANTHROPIC_API_KEY or OPENAI_API_KEY to be set.
    Falls back gracefully if not configured.
    """
    try:
        # Attempt to use the actual review pipeline

        api_key = (
            os.environ.get("ANTHROPIC_API_KEY")
            if provider == "anthropic"
            else os.environ.get("OPENAI_API_KEY")
        )
        if not api_key:
            print(f"  ⚠ No API key configured for {provider}, falling back to mock")
            return _mock_review_diff(diff)

        from sentinel_review.workers.schemas import (
            SYSTEM_PROMPT,
            ReviewOutput,
            get_few_shot_examples,
        )

        if provider == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            msgs = [{"role": "user", "content": f"Review this diff:\n```diff\n{diff[:30000]}\n```"}]
            response = client.messages.create(
                model=model or "claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=msgs,
            )
            raw_text = response.content[0].text
        else:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for ex in get_few_shot_examples():
                openai_messages.append(ex)
            openai_messages.append(
                {
                    "role": "user",
                    "content": f"Review this diff:\n```diff\n{diff[:30000]}\n```",
                }
            )
            response = client.chat.completions.create(
                model=model or "gpt-4o",
                messages=openai_messages,
                max_tokens=4096,
            )
            raw_text = response.choices[0].message.content or ""

        # Parse JSON from response
        json_str = raw_text.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)
        review_output = ReviewOutput(**data)

        return [
            Finding(
                file_path=f.file_path,
                line_number=f.line_number,
                category=f.category,
                severity=f.severity,
                comment=f.comment,
                suggested_fix=f.suggested_fix,
                source="llm",
            )
            for f in review_output.findings
        ]

    except ImportError as e:
        print(f"  ⚠ Missing dependency for live mode: {e}")
        print("  → Falling back to mock provider")
        return _mock_review_diff(diff)
    except (OSError, ValueError) as e:
        print(f"  ⚠ LLM API error in live mode: {e}")
        print("  → Falling back to mock provider")
        return _mock_review_diff(diff)


# Matching Logic


def _finding_matches_known(finding: Finding, known: dict[str, Any]) -> bool:
    """Check if a finding matches a known issue.

    A match requires same file_path, same line_number (or both null),
    and same category.
    """
    if finding.file_path != known.get("file_path", ""):
        return False
    # Line number matching: both null or both equal
    f_line = finding.line_number
    k_line = known.get("line_number")
    if f_line is not None and k_line is not None:
        if f_line != k_line:
            return False
    elif f_line is not None or k_line is not None:
        # One is None, the other isn't — no match
        return False
    return finding.category == known.get("category", "")


def _compute_metrics(
    findings: list[Finding],
    known_issues: list[dict[str, Any]],
) -> tuple[list[dict], list[Finding], list[dict]]:
    """Compare findings against known issues.

    Returns:
        (true_positives, false_positives, false_negatives)
    """
    true_positives: list[dict] = []
    false_positives: list[Finding] = []
    false_negatives: list[dict] = []

    matched_known_indices: set[int] = set()

    for finding in findings:
        matched = False
        for i, known in enumerate(known_issues):
            if i in matched_known_indices:
                continue
            if _finding_matches_known(finding, known):
                matched = True
                matched_known_indices.add(i)
                true_positives.append(
                    {
                        "finding": {
                            "file_path": finding.file_path,
                            "line_number": finding.line_number,
                            "category": finding.category,
                            "severity": finding.severity,
                            "comment": finding.comment[:80],
                        },
                        "known_issue": known,
                    }
                )
                break

        if not matched:
            false_positives.append(finding)

    for i, known in enumerate(known_issues):
        if i not in matched_known_indices:
            false_negatives.append(known)

    return true_positives, false_positives, false_negatives


# Output & Report Generation


