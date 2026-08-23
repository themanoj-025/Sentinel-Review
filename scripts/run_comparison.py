#!/usr/bin/env python3
"""
Sentinel Review — Multi-Model Comparison (run_comparison.py)

Runs the same evaluation fixtures through both supported LLM providers
and produces a side-by-side comparison table of precision, recall, F1,
latency, and token cost.

Two modes:
  mock    — Uses a built-in rule-based analyzer (no API keys needed).
  live    — Uses the actual LLM API for both providers.
            Requires both ANTHROPIC_API_KEY and OPENAI_API_KEY.

Usage:
    # Mock mode (default) — fast, no API keys needed
    python scripts/run_comparison.py

    # Live mode — requires both LLM API keys
    python scripts/run_comparison.py --mode live

    # Write results to the evaluation report
    python scripts/run_comparison.py --output docs/evaluation-report.md

    # Verbose — show per-fixture details for both providers
    python scripts/run_comparison.py -v

Environment variables:
    ANTHROPIC_API_KEY    — Required for live mode
    OPENAI_API_KEY       — Required for live mode
    ANTHROPIC_MODEL      — Claude model ID (default: claude-sonnet-4-20250514)
    OPENAI_MODEL         — OpenAI model ID (default: gpt-4o)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Add backend/ to path so we can import from sentinel_review if needed for live mode
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

# Import shared evaluation logic from run_evaluation.py
_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR))

# These functions are shared with run_evaluation.py to avoid code duplication.
# They must be kept in sync — if you change mock rules or matching logic,
# update both files or refactor into a shared module.
from run_evaluation import (  # type: ignore[import-untyped]  # noqa: E402
    Finding,
    _compute_metrics,
    _live_review_diff,
    _mock_review_diff,
)

# Paths

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_SET_PATH = PROJECT_ROOT / "data" / "eval_set.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "evaluation-report.md"

# Provider Configuration

PROVIDERS = [
    ("anthropic", os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")),
    ("openai", os.environ.get("OPENAI_MODEL", "gpt-4o")),
]

# Approximate cost per 1K tokens (USD) — source: provider pricing pages as of 2026-07
# For unknown models, we use a conservative default of 0.003/0.015 (Claude Sonnet rates).
_MODEL_COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
    "claude-haiku-4-20250514": {"input": 0.00025, "output": 0.00125},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
}


@dataclass
class ProviderResult:
    """Results of running one provider against one fixture."""

    fixture_id: str
    provider: str
    model: str
    findings: list[Finding] = field(default_factory=list)
    true_positives: list[dict] = field(default_factory=list)
    false_positives: list[Finding] = field(default_factory=list)
    false_negatives: list[dict] = field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    latency_ms: int = 0
    total_tokens: int = 0


# Cost Estimation


def _estimate_cost(provider: str, model: str, total_tokens: int) -> float | None:
    """Estimate API cost in USD for a given token count.

    Returns None if no token data is available (mock mode).
    """
    if total_tokens <= 0:
        return None
    rates = _MODEL_COST_PER_1K_TOKENS.get(model)
    if rates is None:
        # Unknown model — use a conservative fallback
        rates = {"input": 0.003, "output": 0.015}
    # Assume roughly 2:1 input:output ratio for code review prompts
    input_tokens = total_tokens * 2 // 3
    output_tokens = total_tokens - input_tokens
    return (input_tokens / 1000 * rates["input"]) + (output_tokens / 1000 * rates["output"])


# Output


def _generate_comparison_table(results: list[ProviderResult]) -> str:
    """Generate a Markdown comparison table from results."""
    lines = [
        "| Provider | Model | Precision | Recall | F1 | Avg Latency | Total Tokens | Est. Cost |",
        "|----------|:-----:|:---------:|:------:|:--:|:-----------:|:------------:|:---------:|",
    ]

    providers: dict[str, list[ProviderResult]] = {}
    for r in results:
        providers.setdefault(r.provider, []).append(r)

    for provider_name in ["anthropic", "openai"]:
        prov_results = providers.get(provider_name, [])
        if not prov_results:
            continue

        total_tp = sum(len(r.true_positives) for r in prov_results)
        total_fp = sum(len(r.false_positives) for r in prov_results)
        total_fn = sum(len(r.false_negatives) for r in prov_results)
        avg_latency = sum(r.latency_ms for r in prov_results) / max(len(prov_results), 1)
        total_tokens = sum(r.total_tokens for r in prov_results)
        model = prov_results[0].model if prov_results else "default"

        prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

        cost = _estimate_cost(provider_name, model, total_tokens)
        cost_str = f"${cost:.4f}" if cost is not None else "—"

        model_label = f"`{model}`"
        lines.append(
            f"| **{provider_name.title()}** | {model_label} | "
            f"{prec:.0%} | {rec:.0%} | {f1:.2f} | "
            f"{avg_latency:.0f}ms | {total_tokens:,} | {cost_str} |"
        )

    return "\n".join(lines)


# Main


def run_comparison(mode: str = "mock") -> tuple[list[ProviderResult], dict]:
    """Run the multi-model comparison.

    Args:
        mode: "mock" (default) or "live"

    Returns:
        (results, summary) — per-fixture results and aggregate summary.
    """
    if not EVAL_SET_PATH.exists():
        print(f"Error: Evaluation set not found at {EVAL_SET_PATH}")
        print("Run `python scripts/build_eval_set.py --sources fixtures` first.")
        sys.exit(1)

    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        entries: list[dict] = json.load(f)

    all_results: list[ProviderResult] = []
    grand_totals: dict[str, dict] = {}

    print("\n🔍 Sentinel Review — Multi-Model Comparison")
    print(f"{'=' * 60}")
    print(f"Mode:      {mode}")
    print(f"Fixtures:  {len(entries)} entries")
    print(f"{'=' * 60}\n")

    for provider_name, model_name in PROVIDERS:
        print(f"\n─── {provider_name.title()} ({model_name}) ───")

        provider_total_tp = 0
        provider_total_fp = 0
        provider_total_fn = 0
        provider_total_latency = 0

        for i, entry in enumerate(entries):
            fixture_id = entry.get("pr_number_or_fixture_id", f"fixture_{i}")
            diff = entry.get("diff", "")
            known = entry.get("known_issues", [])

            print(f"  [{i + 1}/{len(entries)}] {fixture_id}...", end=" ", flush=True)
            tick = time.time()

            if mode == "live":
                findings = _live_review_diff(diff, provider_name, model_name)
            else:
                findings = _mock_review_diff(diff)

            latency = int((time.time() - tick) * 1000)
            tp, fp, fn = _compute_metrics(findings, known)

            tp_count = len(tp)
            fp_count = len(fp)
            fn_count = len(fn)
            prec = tp_count / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 0.0
            rec = tp_count / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

            result = ProviderResult(
                fixture_id=fixture_id,
                provider=provider_name,
                model=model_name,
                findings=findings,
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                precision=prec,
                recall=rec,
                f1_score=f1,
                latency_ms=latency,
                total_tokens=0,  # Token tracking only available in live mode
            )
            all_results.append(result)

            provider_total_tp += tp_count
            provider_total_fp += fp_count
            provider_total_fn += fn_count
            provider_total_latency += latency

            print(
                f"  {len(findings)} findings, {tp_count}TP/{fp_count}FP/{fn_count}FN ({latency}ms)"
            )

        grand_prec = (
            provider_total_tp / (provider_total_tp + provider_total_fp)
            if (provider_total_tp + provider_total_fp) > 0
            else 0.0
        )
        grand_rec = (
            provider_total_tp / (provider_total_tp + provider_total_fn)
            if (provider_total_tp + provider_total_fn) > 0
            else 0.0
        )
        grand_f1 = (
            2 * grand_prec * grand_rec / (grand_prec + grand_rec)
            if (grand_prec + grand_rec) > 0
            else 0.0
        )

        grand_totals[provider_name] = {
            "tp": provider_total_tp,
            "fp": provider_total_fp,
            "fn": provider_total_fn,
            "precision": grand_prec,
            "recall": grand_rec,
            "f1": grand_f1,
            "latency": provider_total_latency / max(len(entries), 1),
        }

    return all_results, grand_totals


def update_evaluation_report(comparison_table: str, mode: str) -> None:
    """Update the Multi-Model Comparison section of docs/evaluation-report.md."""
    if not REPORT_PATH.exists():
        print(f"Report not found at {REPORT_PATH}, skipping update")
        return

    content = REPORT_PATH.read_text(encoding="utf-8")

    # Build the section content
    section_header = "## Multi-Model Comparison\n"
    notes = (
        "\n"
        f"> **Note:** These results are from **{mode}** mode. "
        "In mock mode, both providers use the same rule-based analyzer, "
        "so precision/recall are identical. The latency and cost figures "
        "reflect the mock pipeline overhead, not real API latency. "
        "Run with `--mode live` and valid API keys for real provider comparison.\n"
        "\n"
        "To run a live comparison:\n"
        "\n"
        "```bash\n"
        "# Requires both ANTHROPIC_API_KEY and OPENAI_API_KEY\n"
        "python scripts/run_comparison.py --mode live --output docs/evaluation-report.md\n"
        "```\n"
        "\n"
    )

    table_section = f"{section_header}{notes}{comparison_table}\n\n"

    if section_header in content:
        # Replace existing section — find the section and the next section boundary
        before, rest = content.split(section_header, 1)
        # Find the next ## heading (any section) or end of string
        next_section = rest.find("\n## ")
        after = rest[next_section:] if next_section >= 0 else ""
        content = before + table_section + after
    elif "\n## Limitations\n" in content:
        # Insert before Limitations section
        content = content.replace(
            "\n## Limitations\n",
            f"\n{table_section}## Limitations\n",
            1,
        )
    else:
        print("  ⚠ Could not find insertion point in report")
        return

    REPORT_PATH.write_text(content, encoding="utf-8")
    print(f"\n📄 Updated evaluation report: {REPORT_PATH}")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Multi-model comparison for Sentinel Review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "live"],
        default="mock",
        help="Evaluation mode (default: mock — no API keys needed)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write comparison table to docs/evaluation-report.md",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show per-fixture details for both providers",
    )
    args = parser.parse_args()

    results, _totals = run_comparison(mode=args.mode)

    print(f"\n{'=' * 60}")
    print("MULTI-MODEL COMPARISON")
    print(f"{'=' * 60}")
    print()
    print(_generate_comparison_table(results))

    if args.verbose:
        print(f"\n{'=' * 60}")
        print("PER-FIXTURE DETAILS")
        print(f"{'=' * 60}")
        for r in results:
            print(
                f"\n  {r.provider.title()} — {r.fixture_id}: {len(r.findings)} findings "
                f"({len(r.true_positives)}TP/{len(r.false_positives)}FP/{len(r.false_negatives)}FN)"
            )
            if r.true_positives:
                for tp in r.true_positives:
                    f = tp["finding"]
                    print(f"    ✅ {f['file_path']}:{f['line_number']} ({f['category']})")

    output_path = Path(args.output) if args.output else None
    if output_path:
        table = _generate_comparison_table(results)
        update_evaluation_report(table, args.mode)

    print(f"\n{'=' * 60}")
    print("NOTES")
    print(f"{'=' * 60}")
    if args.mode == "live":
        print("✓ Live mode — results reflect actual LLM API performance.")
    else:
        print("ℹ Mock mode — both providers use the same rule-based analyzer.")
        print("  Precision/recall are identical by design.")
        print("  Run with --mode live for real provider comparison.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
