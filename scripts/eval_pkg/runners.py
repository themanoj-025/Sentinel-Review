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

    lines.append(
        f"| **Total** | **{total_known}** | **{total_tp}** | **{total_fp}** | **{total_fn}** |"
    )
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
        for _fp in entry.false_positives:
            cat_fp[cat] = cat_fp.get(cat, 0) + 1

    report = f"""# Sentinel Review — Evaluation Report

> *Generated: {time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}*
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
        cat_prec = (
            f"{cat_tp_count / (cat_tp_count + cat_fp_count):.0%}"
            if (cat_tp_count + cat_fp_count) > 0
            else "—"
        )
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


# Main


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
        "-v",
        "--verbose",
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

    # Load evaluation set
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

    mode_label = (
        f"Mock ({args.mode})"
        if args.mode == "mock"
        else f"Live ({args.provider}/{args.model or 'default'})"
    )

    # Run evaluation
    entries: list[EvalEntry] = []
    start_time = time.time()

    for i, entry_data in enumerate(entries_data):
        fixture_id = entry_data.get("pr_number_or_fixture_id", f"fixture_{i}")
        diff = entry_data.get("diff", "")
        known_issues = entry_data.get("known_issues", [])

        print(f"  [{i + 1}/{len(entries_data)}] {fixture_id}...", end=" ", flush=True)

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
        print(
            f"  {len(findings)} findings, "
            f"{tp_count} TP / {fp_count} FP / {fn_count} FN "
            f"({latency}ms)"
        )

    elapsed = time.time() - start_time

    # Print results
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

    # Write report
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
