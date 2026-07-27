"""
Semgrep integration for independent static analysis signal.

Runs Semgrep on file content and converts findings to the same
Finding schema used by LLM-based reviews for cross-referencing.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from celery import shared_task

from .schemas import Finding

logger = logging.getLogger(__name__)

# Default Semgrep rules focused on security and correctness
DEFAULT_RULES = [
    "p/python",
    "p/javascript",
    "p/typescript",
    "p/golang",
    "p/java",
    "p/ruby",
]


def run_semgrep(
    file_contents: dict[str, str],
    rules: list[str] | None = None,
) -> list[Finding]:
    """
    Run Semgrep on the provided file contents and return findings.

    Args:
        file_contents: Dict mapping file paths to their content.
        rules: List of Semgrep rule IDs or paths. Defaults to common language rules.

    Returns:
        List of Finding objects from Semgrep results.
    """
    if not file_contents:
        return []

    rules_to_use = rules or DEFAULT_RULES

    try:
        # Write files to a temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            file_map = {}

            for file_path, content in file_contents.items():
                # Create subdirectories as needed
                dest = tmp_path / file_path.lstrip("/")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                file_map[file_path] = str(dest)

            # Build the semgrep command
            cmd = [
                "semgrep",
                "--json",
                "--quiet",
                "--no-git-ignore",
                "--respect-gitignore=false",
            ]

            for rule in rules_to_use:
                cmd.extend(["--config", rule])

            cmd.append(str(tmp_path))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode not in (0, 1):  # 1 means findings found
                logger.error("Semgrep error: %s", result.stderr[:500])
                return []

            return _parse_semgrep_output(result.stdout, file_map)

    except FileNotFoundError:
        logger.warning("Semgrep not installed — skipping static analysis signal")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("Semgrep timed out — skipping")
        return []
    except Exception as e:
        logger.error("Semgrep execution error: %s", e)
        return []


def _parse_semgrep_output(
    output: str,
    file_map: dict[str, str],
) -> list[Finding]:
    """Parse Semgrep JSON output into Finding objects."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []

    findings: list[Finding] = []

    for result in data.get("results", []):
        path = result.get("path", "")
        # Map back to original file path
        original_path = None
        for orig, tmp in file_map.items():
            if tmp == path or path.endswith(orig):
                original_path = orig
                break
        if not original_path:
            original_path = path

        start_line = result.get("start", {}).get("line")
        message = result.get("extra", {}).get("message", "")
        severity = result.get("extra", {}).get("severity", "warning")

        # Map Semgrep severity to our severity
        mapped_severity = "warning"
        if severity == "ERROR":
            mapped_severity = "blocking"
        elif severity in ("WARNING",):
            mapped_severity = "warning"
        elif severity == "INFO":
            mapped_severity = "nit"

        # Add code snippet for context
        snippet = result.get("extra", {}).get("lines", "")
        content = message
        if snippet:
            content = f"{message}\n```\n{snippet}\n```"

        finding = Finding(
            file_path=original_path or path,
            line_number=start_line,
            category="security",  # Semgrep findings default to security
            severity=mapped_severity,  # type: ignore
            comment=content,
            suggested_fix=result.get("extra", {}).get("fix", None),
        )
        findings.append(finding)

    return findings


@shared_task(bind=True, max_retries=1, default_retry_delay=5, queue="default", acks_late=True)
def run_semgrep_async(self, file_contents: dict[str, str]) -> list[dict]:
    """
    Run Semgrep asynchronously in a Celery task (4.5).

    Returns serialized findings as dicts (Finding is not JSON-serializable).
    If Semgrep is not installed or times out, returns empty list.
    """
    logger.info("Async Semgrep: processing %d files", len(file_contents))
    findings = run_semgrep(file_contents)
    return [f.model_dump() for f in findings]


def merge_with_llm_findings(
    llm_findings: list[Finding],
    semgrep_findings: list[Finding],
) -> list[dict[str, Any]]:
    """
    Merge LLM and Semgrep findings, marking agreements as high-confidence.

    Returns a list of dicts with the Finding data plus a 'high_confidence' flag
    and 'source' field indicating which tool(s) found it.
    """
    merged: list[dict[str, Any]] = []

    # Track which semgrep findings have been matched
    used_indices = set()

    for lf in llm_findings:
        entry = lf.model_dump()
        entry["source"] = "llm"
        entry["high_confidence"] = False

        # Check if any semgrep finding matches
        for i, sf in enumerate(semgrep_findings):
            if i in used_indices:
                continue
            if (
                sf.file_path == lf.file_path
                and sf.line_number == lf.line_number
                and sf.category == lf.category
            ):
                entry["source"] = "llm+semgrep"
                entry["high_confidence"] = True
                used_indices.add(i)
                break

        merged.append(entry)

    # Add unmatched semgrep findings
    for i, sf in enumerate(semgrep_findings):
        if i not in used_indices:
            entry = sf.model_dump()
            entry["source"] = "semgrep"
            entry["high_confidence"] = False
            merged.append(entry)

    return merged
