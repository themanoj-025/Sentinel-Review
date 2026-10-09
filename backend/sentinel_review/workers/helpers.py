"""Shared helper functions — extracted to break circular imports."""

from __future__ import annotations

from typing import Any


def _parse_changed_files(diff: str) -> list[str]:
    """Parse diff to extract list of changed file paths."""
    files = []
    seen = set()
    for line in diff.split("\n"):
        if line.startswith("+++ b/") and not line.startswith("+++ b/dev/null"):
            file_path = line[6:].strip()
            if file_path and file_path not in seen:
                seen.add(file_path)
                files.append(file_path)
    return files


def _build_context_str(repo_ctx: Any) -> str:
    """Build a context string from repo metadata."""
    if not repo_ctx:
        return ""
    parts = []
    if repo_ctx.default_branch:
        parts.append(f"Default branch: {repo_ctx.default_branch}")
    if repo_ctx.has_contributing and repo_ctx.contributing_content:
        parts.append(f"\nCONTRIBUTING.md:\n{repo_ctx.contributing_content[:3000]}")
    if repo_ctx.has_linter_config and repo_ctx.linter_config_content:
        cfg_str = "\n".join(
            f"--- {path} ---\n{content[:1000]}"
            for path, content in repo_ctx.linter_config_content.items()
        )
        parts.append(f"\nLinter/Config files:\n{cfg_str[:2000]}")
    return "\n".join(parts)


# Default categories when no repo config is available
_DEFAULT_CATEGORIES = {"bug", "security", "style", "suggestion"}


def _deduplicate(findings: list[dict]) -> list[dict]:
    """Deduplicate near-identical findings (same file, same line, category)."""
    seen: set[tuple[str, int | None, str]] = set()
    unique: list[dict] = []

    for finding in findings:
        key = (
            finding.get("file_path", ""),
            finding.get("line_number"),
            finding.get("category", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique


def _build_review_body(findings: list[dict], total_comments: int) -> str:
    """Build the review summary body from findings."""
    blocking = sum(1 for m in findings if m.get("severity") == "blocking")
    warnings = sum(1 for m in findings if m.get("severity") == "warning")
    nits = sum(1 for m in findings if m.get("severity") == "nit")
    categories = sorted({m.get("category", "unknown") for m in findings})
    cat_rows = "\n".join(
        "| %s | %d |" % (cat, sum(1 for m in findings if m.get("category") == cat))
        for cat in categories
    )

    return (
        "### 🔍 Sentinel Review Complete\n\n"
        "Found **%d** issue(s) "
        "(%d blocking, %d warnings, %d nits)\n\n"
        "| Category | Count |\n|----------|------|\n%s"
    ) % (total_comments, blocking, warnings, nits, cat_rows)
