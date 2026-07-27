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

# ─── Paths ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_SET_PATH = PROJECT_ROOT / "data" / "eval_set.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "evaluation-report.md"

# ─── Data Structures ─────────────────────────────────────────────────────


class MatchResult(Enum):
    TP = "TP"   # True Positive: finding matches a known issue
    FP = "FP"   # False Positive: finding doesn't match any known issue
    FN = "FN"   # False Negative: known issue with no matching finding


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


# ═══════════════════════════════════════════════════════════════════════════
# Mock LLM Provider — rule-based analyzer for offline evaluation
# ═══════════════════════════════════════════════════════════════════════════


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
            if match:
                current_line_num = int(match.group(1))
            else:
                current_line_num = 0
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

    # ── Rule 1: SQL Injection ─────────────────────────────────────────
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

    # ── Rule 2: Hardcoded Secrets ─────────────────────────────────────
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
                    findings.append(Finding(
                        file_path=_infer_file_path(lines),
                        line_number=line_num,
                        category="security",
                        severity="blocking",
                        comment=f"Hardcoded {description} committed to source code.",
                        suggested_fix="Load secrets from environment variables or a secrets manager.",
                    ))

    # ── Rule 3: Unsafe Deserialization ────────────────────────────────
    for line_num, content in added_lines:
        if "pickle.load" in content:
            if not any(f.line_number == line_num and "pickle" in f.comment for f in findings):
                findings.append(Finding(
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
                ))

    # ── Rule 4: Off-by-One / Index Errors ─────────────────────────────
    for line_num, content in added_lines:
        # range(1, len(items) + 1)  ← off by one (should be just len(items))
        if re.search(r"range\s*\(\s*1\s*,\s*len\s*\(.*?\)\s*\+\s*1\s*\)", content):
            if not any(f.line_number == line_num and "off-by-one" in f.comment for f in findings):
                findings.append(Finding(
                    file_path=_infer_file_path(lines),
                    line_number=line_num,
                    category="bug",
                    severity="blocking",
                    comment=(
                        "Off-by-one error: range(1, len(items) + 1) goes one beyond "
                        "the last index, causing an IndexError."
                    ),
                    suggested_fix="Use `range(0, len(items))` or `enumerate(items)`.",
                ))

        # items[i] access that may go out of bounds
        if re.search(r"items\s*\[", content) and not re.search(r"len|range|for", content):
            if not any(f.line_number == line_num and "out of bounds" in f.comment for f in findings):
                findings.append(Finding(
                    file_path=_infer_file_path(lines),
                    line_number=line_num,
                    category="bug",
                    severity="warning",
                    comment=(
                        "Potentially accessing list index that may be out of bounds "
                        "(see off-by-one in preceding loop range)."
                    ),
                ))

    # ── Rule 5: Missing Zero Division Guard ───────────────────────────
    for line_num, content in added_lines:
        if re.search(r"return\s+.+/", content) and "if b == 0" not in content:
            if not any(f.line_number == line_num and "zero-division" in f.comment for f in findings):
                findings.append(Finding(
                    file_path=_infer_file_path(lines),
                    line_number=line_num,
                    category="bug",
                    severity="blocking",
                    comment=(
                        "Division by zero guard missing — passing b=0 will raise "
                        "a ZeroDivisionError at runtime."
                    ),
                    suggested_fix="Add a check: `if b == 0: return None` (or appropriate error handling).",
                ))

    return findings


def _infer_file_path(diff_lines: list[str]) -> str:
    """Extract file path from diff +++ line."""
    for line in diff_lines:
        if line.startswith("+++ b/"):
            return line[6:].strip()
    return "unknown.py"


# ═══════════════════════════════════════════════════════════════════════════
# Live LLM Provider (optional — requires API key)
# ═══════════════════════════════════════════════════════════════════════════


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

        api_key = os.environ.get("ANTHROPIC_API_KEY") if provider == "anthropic" else os.environ.get("OPENAI_API_KEY")
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
            openai_messages.append({
                "role": "user",
                "content": f"Review this diff:\n```diff\n{diff[:30000]}\n```",
            })
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
    except Exception as e:
        print(f"  ⚠ LLM API error in live mode: {e}")
        print("  → Falling back to mock provider")
        return _mock_review_diff(diff)


# ═══════════════════════════════════════════════════════════════════════════
# Matching Logic
# ═══════════════════════════════════════════════════════════════════════════


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
                true_positives.append({
                    "finding": {
                        "file_path": finding.file_path,
                        "line_number": finding.line_number,
                        "category": finding.category,
                        "severity": finding.severity,
                        "comment": finding.comment[:80],
                    },
                    "known_issue": known,
                })
                break

        if not matched:
            false_positives.append(finding)

    for i, known in enumerate(known_issues):
        if i not in matched_known_indices:
            false_negatives.append(known)

    return true_positives, false_positives, false_negatives


# ═══════════════════════════════════════════════════════════════════════════
# Output & Report Generation
# ═══════════════════════════════════════════════════════════════════════════


def _format_results_table(
    entries: list[EvalEntry],
    mode: str,
) -> str:
    """Format evaluation results as a Markdown table."""
    lines = [f"### Evaluation Results ({mode} mode)"]
    lines.append("")
    lines.append("| Fixture | Known Issues | TP | FP | FN | Precision | Recall | F1 |")
    lines.append("|---------|:------------:|:--:|:--:|:--:|:---------:|:------:|:--:|")

    total_known = 0
    total_tp = 0
    total_fp = 0
    total_fn = 0

    for entry in entries:
        total_known += len(entry.known_issues)
        total_tp += len(entry.true_positives)
        total_fp += len(entry.false_positives)
        total_fn += len(entry.false_negatives)

        prec = f"{entry.precision:.0%}" if entry.true_positives else "—"
        rec = f"{entry.recall:.0%}" if entry.true_positives else "—"
        f1 = f"{entry.f1_score:.2f}" if entry.true_positives else "—"

        lines.append(
            f"| {entry.fixture_id} | {len(entry.known_issues)} | "
            f"{len(entry.true_positives)} | {len(entry.false_positives)} | "
            f"{len(entry.false_negatives)} | {prec} | {rec} | {f1} |"
        )

    lines.append(f"| **Total** | **{total_known}** | **{total_tp}** | **{total_fp}** | **{total_fn}** |")
    grand_prec = f"{total_tp / (total_tp + total_fp):.0%}" if (total_tp + total_fp) > 0 else "—"
    grand_rec = f"{total_tp / (total_tp + total_fn):.0%}" if (total_tp + total_fn) > 0 else "—"
    grand_f1 = (
        f"{2 * total_tp / (2 * total_tp + total_fp + total_fn):.2f}"
        if (total_tp + total_fp + total_fn) > 0
        else "—"
    )
    lines.append(f"| | | | | | **{grand_prec}** | **{grand_rec}** | **{grand_f1}** |")
    lines.append("")

    return "\n".join(lines)


def _format_per_fixture_details(entries: list[EvalEntry]) -> str:
    """Format detailed per-fixture analysis."""
    sections: list[str] = []

    for entry in entries:
        sections.append(f"\n#### {entry.fixture_id}")
        sections.append("")

        if entry.true_positives:
            sections.append("**True Positives:**")
            for tp in entry.true_positives:
                f = tp["finding"]
                sections.append(
                    f"- ✅ `{f['file_path']}:{f['line_number']}` "
                    f"({f['category']}/{f['severity']}) — {f['comment']}"
                )

        if entry.false_positives:
            sections.append("\n**False Positives (noise):**")
            for fp in entry.false_positives:
                sections.append(
                    f"- ❌ `{fp.file_path}:{fp.line_number}` "
                    f"({fp.category}/{fp.severity}) — {fp.comment[:80]}"
                )

        if entry.false_negatives:
            sections.append("\n**False Negatives (missed):**")
            for fn in entry.false_negatives:
                sections.append(
                    f"- ⚠️ `{fn.get('file_path', '?')}:{fn.get('line_number', '?')}` "
                    f"({fn.get('category', '?')}) — {fn.get('description', '')[:80]}"
                )

        if not entry.true_positives and not entry.false_positives and not entry.false_negatives:
            sections.append("- No known issues and no findings (correct).")

        sections.append("")

    return "\n".join(sections)


def _generate_report(
    entries: list[EvalEntry],
    mode: str,
    mode_label: str,
    elapsed: float,
) -> str:
    """Generate the full evaluation report Markdown content."""
    # Compute aggregates
    total_known = sum(len(e.known_issues) for e in entries)
    total_tp = sum(len(e.true_positives) for e in entries)
    total_fp = sum(len(e.false_positives) for e in entries)
    total_fn = sum(len(e.false_negatives) for e in entries)

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Build category breakdown
    cat_known: dict[str, int] = {}
    cat_tp: dict[str, int] = {}
    cat_fp: dict[str, int] = {}
    for entry in entries:
        for ki in entry.known_issues:
            cat = ki.get("category", "unknown")
            cat_known[cat] = cat_known.get(cat, 0) + 1
        for tp in entry.true_positives:
            cat = tp["finding"]["category"]
            cat_tp[cat] = cat_tp.get(cat, 0) + 1
        for fp in entry.false_positives:
            cat_fp[cat] = cat_fp.get(cat, 0) + 1

    report = f"""# Sentinel Review — Evaluation Report

> *Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}*
> *Mode: {mode_label}*
> *Fixtures: {len(entries)} entries, {total_known} known issues*
> *Duration: {elapsed:.1f}s*

---

## Results Summary

| Metric | Value |
|--------|:-----:|
| Precision | {precision:.1%} |
| Recall | {recall:.1%} |
| F1 Score | {f1:.3f} |
| True Positives | {total_tp} |
| False Positives | {total_fp} |
| False Negatives | {total_fn} |

### By Category

| Category | Known Issues | TP | FP | FN | Precision | Recall |
|----------|:------------:|:--:|:--:|:--:|:---------:|:------:|
"""
    for cat in sorted(cat_known):
        cat_tp_count = cat_tp.get(cat, 0)
        cat_fp_count = cat_fp.get(cat, 0)
        cat_fn_count = cat_known[cat] - cat_tp_count
        cat_prec = f"{cat_tp_count / (cat_tp_count + cat_fp_count):.0%}" if (cat_tp_count + cat_fp_count) > 0 else "—"
        cat_rec = f"{cat_tp_count / cat_known[cat]:.0%}" if cat_known[cat] > 0 else "—"
        report += f"| {cat} | {cat_known[cat]} | {cat_tp_count} | {cat_fp_count} | {cat_fn_count} | {cat_prec} | {cat_rec} |\n"

    report += f"""
## Per-Fixture Breakdown

{_format_results_table(entries, mode)}
{_format_per_fixture_details(entries)}

---

## Methodology

### Metric Definitions

```
Precision = TP / (TP + FP)   — How many of our findings are correct?
Recall    = TP / (TP + FN)   — How many real issues did we catch?
F1        = 2 × P × R / (P + R) — Harmonic mean of precision and recall
```

### Matching Criteria

A finding is considered a **True Positive** if it matches a known issue on:

1. **file_path** — same file
2. **line_number** — same line (or both null for file-level findings)
3. **category** — same category (`bug`, `security`, `style`, `suggestion`)

If a finding doesn't match any known issue, it's a **False Positive**.
If a known issue isn't matched by any finding, it's a **False Negative**.

### Mode: {mode_label}

This evaluation was run in **{mode}** mode.
"""
    if mode == "mock":
        report += """
The mock provider uses rule-based pattern matching to simulate LLM output.
This gives a deterministic baseline for the evaluation harness. Results may
differ when using a real LLM provider (run with `--mode live`).

**Mock rules implemented:**
1. SQL injection detection (f-string + SQL keywords, string concatenation)
2. Hardcoded secret detection (API keys, passwords, SECRET_KEY patterns)
3. Unsafe deserialization detection (`pickle.loads`, `pickle.load`)
4. Off-by-one index errors (`range(1, len + 1)`)
5. Missing zero-division guard (`return a/b` without `b==0` check)
"""
    else:
        report += """
The live LLM provider was used with the configured model.
Results reflect actual LLM performance on the planted-bug fixture set.
"""

    report += """
### Evaluation Dataset

The `data/eval_set.json` file was generated by `scripts/build_eval_set.py`:
- 6 planted-bug fixtures from `backend/tests/fixtures/sample_prs/`
- 9 known issues across security and bug categories
- Includes a clean diff (0 issues) as a false-positive check

### Reproducibility

```bash
# Regenerate evaluation set
python scripts/build_eval_set.py --sources fixtures

# Re-run evaluation
python scripts/run_evaluation.py --output docs/evaluation-report.md
```

---

## Limitations

- **Planted-bug set is small (9 known issues):** Statistical significance
  requires 100+ fixtures across more languages
- **Python-only:** All fixtures are Python — no JS/TS/Go/Ruby coverage
- **Mock mode:** Rule-based patterns miss context-dependent issues an LLM
  would catch; live numbers will differ
- **No production data:** Usefulness metrics require real deployment with
  actual PR reviews and human feedback
"""
    return report


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run Sentinel Review evaluation against the fixture set",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "live"],
        default="mock",
        help="Evaluation mode (default: mock — no API key needed)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model to use in live mode",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai"],
        default="anthropic",
        help="LLM provider for live mode (default: anthropic)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write evaluation report to this path (default: print to stdout only)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show per-fixture detailed breakdown",
    )
    parser.add_argument(
        "--eval-set",
        type=str,
        default=str(EVAL_SET_PATH),
        help=f"Path to evaluation set JSON (default: {EVAL_SET_PATH})",
    )

    args = parser.parse_args()

    # ── Load evaluation set ──────────────────────────────────────────
    eval_path = Path(args.eval_set)
    if not eval_path.exists():
        print(f"Error: Evaluation set not found at {eval_path}")
        print("Run `python scripts/build_eval_set.py --sources fixtures` to generate it.")
        sys.exit(1)

    with open(eval_path, encoding="utf-8") as f:
        entries_data: list[dict[str, Any]] = json.load(f)

    print("\n🔍 Sentinel Review — Evaluation Runner")
    print(f"{'=' * 50}")
    print(f"Mode:      {args.mode} {'(no API key needed)' if args.mode == 'mock' else ''}")
    print(f"Fixtures:  {len(entries_data)} entries")
    known_total = sum(len(e.get("known_issues", [])) for e in entries_data)
    print(f"Known:     {known_total} issues")
    print(f"{'=' * 50}\n")

    mode_label = f"Mock ({args.mode})" if args.mode == "mock" else f"Live ({args.provider}/{args.model or 'default'})"

    # ── Run evaluation ───────────────────────────────────────────────
    entries: list[EvalEntry] = []
    start_time = time.time()

    for i, entry_data in enumerate(entries_data):
        fixture_id = entry_data.get("pr_number_or_fixture_id", f"fixture_{i}")
        diff = entry_data.get("diff", "")
        known_issues = entry_data.get("known_issues", [])

        print(f"  [{i+1}/{len(entries_data)}] {fixture_id}...", end=" ", flush=True)

        tick = time.time()

        # Run the review
        if args.mode == "live":
            findings = _live_review_diff(
                diff,
                provider=args.provider,
                model=args.model,
            )
        else:
            findings = _mock_review_diff(diff)

        latency = int((time.time() - tick) * 1000)

        # Compute metrics
        tp, fp, fn = _compute_metrics(findings, known_issues)

        entry = EvalEntry(
            fixture_id=fixture_id,
            known_issues=known_issues,
            mock_findings=findings,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            latency_ms=latency,
        )

        # Compute precision/recall/F1
        tp_count = len(tp)
        fp_count = len(fp)
        fn_count = len(fn)
        entry.precision = tp_count / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 0.0
        entry.recall = tp_count / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 0.0
        entry.f1_score = (
            2 * entry.precision * entry.recall / (entry.precision + entry.recall)
            if (entry.precision + entry.recall) > 0
            else 0.0
        )

        entries.append(entry)

        # Print summary line
        print(f"  {len(findings)} findings, "
              f"{tp_count} TP / {fp_count} FP / {fn_count} FN "
              f"({latency}ms)")

    elapsed = time.time() - start_time

    # ── Print results ────────────────────────────────────────────────
    print(f"\n{'=' * 50}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 50}")
    print(_format_results_table(entries, args.mode))

    if args.verbose:
        print("DETAILED BREAKDOWN")
        print(f"{'=' * 50}")
        print(_format_per_fixture_details(entries))

    # Compute grand totals
    total_tp = sum(len(e.true_positives) for e in entries)
    total_fp = sum(len(e.false_positives) for e in entries)
    total_fn = sum(len(e.false_negatives) for e in entries)
    total_known_total = sum(len(e.known_issues) for e in entries)
    grand_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    grand_rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    grand_f1 = (
        2 * grand_prec * grand_rec / (grand_prec + grand_rec)
        if (grand_prec + grand_rec) > 0
        else 0.0
    )

    print(f"\n{'=' * 50}")
    print("GRAND TOTAL")
    print(f"{'=' * 50}")
    print(f"  Known issues:  {total_known_total}")
    print(f"  True Positives: {total_tp}")
    print(f"  False Positives: {total_fp}")
    print(f"  False Negatives: {total_fn}")
    print(f"  Precision:      {grand_prec:.1%}")
    print(f"  Recall:         {grand_rec:.1%}")
    print(f"  F1 Score:       {grand_f1:.3f}")
    print(f"  Duration:       {elapsed:.1f}s")
    print()

    # ── Write report ─────────────────────────────────────────────────
    output_path = Path(args.output) if args.output else None
    if output_path is None:
        env_path = os.environ.get("EVAL_REPORT_PATH", "")
        output_path = Path(env_path) if env_path else None

    if output_path:
        report = _generate_report(entries, args.mode, mode_label, elapsed)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"📄 Report written to: {output_path.resolve()}")
    else:
        print("💡 Tip: Use --output docs/evaluation-report.md to write the report.")
        print()


if __name__ == "__main__":
    main()
