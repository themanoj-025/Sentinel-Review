"""
Standalone review runner for GitHub Actions execution mode.

This module runs the Sentinel Review pipeline as a CI step, independent of the
Django/Celery/PostgreSQL stack. It reuses the LLM prompt schemas and finding
models from the main codebase but communicates with GitHub using GITHUB_TOKEN
and reads the diff from the local git checkout.

The scripts/gha_review.py entry point is a thin wrapper that calls main() here.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from sentinel_review.workers.schemas import SYSTEM_PROMPT, ReviewOutput, get_few_shot_examples

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────

_GITHUB_API_BASE = "https://api.github.com"
_REPORT_DIR = Path("/tmp/sentinel-review-reports")


def _setup_logging() -> None:
    """Configure basic logging for CI output."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


# ─── GitHub API Client (uses GITHUB_TOKEN) ────────────────────────────


class GHAClient:
    """Simple GitHub API client using GITHUB_TOKEN for Actions mode."""

    def __init__(self) -> None:
        self.token = os.environ.get("GITHUB_TOKEN", "")
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN environment variable is required")

        self._client = httpx.Client(
            base_url=_GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "sentinel-review-gha",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    def close(self) -> None:
        self._client.close()

    def post_review(
        self,
        repo: str,
        pr_number: int,
        comments: list[dict[str, Any]],
        review_body: str = "### 🔍 Sentinel Review\n\nAutomated review complete. See inline comments for details.",
    ) -> dict[str, Any]:
        """Post a review with inline comments to a pull request."""
        payload = {
            "body": review_body,
            "event": "COMMENT",
            "comments": comments,
        }
        resp = self._client.post(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ─── Diff & File Reading ──────────────────────────────────────────────


def get_diff() -> str:
    """Get the diff of the current PR by comparing HEAD to the merge base.

    In GitHub Actions, the checkout action fetches the PR merge commit.
    First tries base SHA from the event payload, then falls back to HEAD~1.
    """
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    base_sha = None

    if event_path and Path(event_path).exists():
        try:
            with open(event_path) as f:
                event = json.load(f)
            pr_data = event.get("pull_request", {})
            base_sha = pr_data.get("base", {}).get("sha")
        except (json.JSONDecodeError, KeyError):
            pass

    if base_sha:
        result = subprocess.run(
            ["git", "diff", base_sha, "HEAD", "--", "."],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.info("Fetched diff against base SHA: %d lines", len(result.stdout.splitlines()))
            return result.stdout
        logger.warning("git diff against base SHA failed, falling back to HEAD~1")

    # Fallback: diff against HEAD~1
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD", "--", "."],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        logger.warning("git diff HEAD~1 failed: %s", result.stderr[:200])
        return ""

    diff = result.stdout
    logger.info("Fetched diff: %d lines", len(diff.splitlines()))
    return diff


def get_file_contents(diff: str) -> dict[str, str]:
    """Read changed file contents from the working directory."""
    files = parse_changed_files(diff)
    contents: dict[str, str] = {}
    for file_path in files:
        full_path = Path.cwd() / file_path
        if full_path.exists() and full_path.is_file():
            try:
                contents[file_path] = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.warning("Failed to read %s: %s", file_path, e)
    logger.info("Read %d file contents", len(contents))
    return contents


def parse_changed_files(diff: str) -> list[str]:
    """Parse diff to extract list of changed file paths."""
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/") and "dev/null" not in line:
            file_path = line[6:].strip()
            if file_path and file_path not in seen:
                seen.add(file_path)
                files.append(file_path)
    return files


# ─── LLM Integration (standalone, no Django) ──────────────────────────


def _call_anthropic(diff: str, file_contents: dict[str, str], api_key: str) -> dict[str, Any]:
    """Call Anthropic Claude API for review."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    messages = _build_prompt_messages(diff, file_contents)

    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    raw_text = response.content[0].text
    total_tokens = response.usage.input_tokens + response.usage.output_tokens

    return {
        "raw_output": raw_text,
        "total_tokens": total_tokens,
        "provider": "anthropic",
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
    }


def _call_openai(diff: str, file_contents: dict[str, str], api_key: str) -> dict[str, Any]:
    """Call OpenAI API for review."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_build_prompt_messages(diff, file_contents))

    response = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=messages,
        max_tokens=4096,
        temperature=0.1,
    )

    raw_text = response.choices[0].message.content or ""
    usage = response.usage
    total_tokens = (usage.input_tokens + usage.output_tokens) if usage else 0

    return {
        "raw_output": raw_text,
        "total_tokens": total_tokens,
        "provider": "openai",
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
    }


def _build_prompt_messages(diff: str, file_contents: dict[str, str]) -> list[dict[str, str]]:
    """Build user/assistant message pairs for the LLM prompt."""
    messages: list[dict[str, str]] = []

    if file_contents:
        file_blob = "\n\n".join(
            f"### {path}\n```\n{content[:5000]}\n```" for path, content in file_contents.items()
        )
        messages.append(
            {"role": "user", "content": f"Full file contents for context:\n{file_blob[:10000]}"}
        )
        messages.append(
            {
                "role": "assistant",
                "content": "Thanks, I have the full context of the changed files.",
            }
        )

    for example in get_few_shot_examples():
        messages.append({"role": example["role"], "content": example["content"]})

    messages.append(
        {
            "role": "user",
            "content": (
                f"Review this pull request diff:\n\n```diff\n{diff[:30000]}\n```\n\n"
                "Return your findings as a JSON object with a 'findings' array."
            ),
        }
    )

    return messages


def parse_findings(raw_output: str) -> list[dict[str, Any]]:
    """Parse the LLM output into structured findings."""
    json_str = raw_output.strip()

    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0].strip()
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON output: %s", e)
        return []

    try:
        review_output = ReviewOutput(**data)
    except Exception as e:
        logger.error("Pydantic validation failed: %s", e)
        return []

    return [
        {
            "file_path": f.file_path,
            "line_number": f.line_number,
            "category": f.category,
            "severity": f.severity,
            "comment": f.comment,
            "suggested_fix": f.suggested_fix,
        }
        for f in review_output.findings
    ]


# ─── Deduplication ────────────────────────────────────────────────────


def deduplicate(findings: list[dict]) -> list[dict]:
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


def build_review_body(findings: list[dict], total_comments: int) -> str:
    """Build the review summary body from findings."""
    blocking = sum(1 for m in findings if m.get("severity") == "blocking")
    warnings = sum(1 for m in findings if m.get("severity") == "warning")
    nits = sum(1 for m in findings if m.get("severity") == "nit")
    categories = sorted(set(m.get("category", "unknown") for m in findings))
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


# ─── Report Output ────────────────────────────────────────────────────


def save_report(report: dict[str, Any], repo: str, pr_number: int) -> Path:
    """Save the review report as a JSON file (uploaded as artifact)."""
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"sentinel-review-{repo.replace('/', '-')}-pr{pr_number}.json"
    report_path = _REPORT_DIR / filename
    report_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Report saved to %s", report_path)
    return report_path


# ─── Main Entry Point ─────────────────────────────────────────────────


def run(repo: str, event: dict[str, Any]) -> int:
    """Run the Sentinel Review pipeline in GitHub Actions mode.

    Args:
        repo: The GitHub repository (owner/repo).
        event: The parsed GitHub webhook event payload.

    Returns 0 on success, 1 on failure.
    """
    pr_action = event.get("action", "opened")
    if pr_action not in ("opened", "synchronize"):
        logger.info("Ignoring event action: %s", pr_action)
        return 0

    pr_data = event.get("pull_request", {})
    pr_number = pr_data.get("number")
    pr_title = pr_data.get("title", "")

    if not pr_number:
        logger.error("No pull_request number in event payload")
        return 1

    start_time = time.time()
    report: dict[str, Any] = {
        "repo": repo,
        "pr_number": pr_number,
        "pr_title": pr_title,
        "action": pr_action,
        "status": "processing",
        "findings": [],
        "errors": [],
    }

    try:
        # Step 1: Get the diff
        logger.info("Fetching diff for %s#%d", repo, pr_number)
        diff = get_diff()
        if not diff:
            logger.warning("Empty diff — nothing to review")
            report["status"] = "completed"
            report["summary"] = "No changes to review (empty diff)."
            save_report(report, repo, pr_number)
            return 0

        # Step 2: Get file contents
        file_contents = get_file_contents(diff)

        # Also try reading .sentinel-ignore from the working directory (repo root)
        # since it may not be in the diff if it wasn't changed
        if ".sentinel-ignore" not in file_contents:
            ignore_path = Path.cwd() / ".sentinel-ignore"
            if ignore_path.exists():
                try:
                    file_contents[".sentinel-ignore"] = ignore_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    logger.info("Read .sentinel-ignore from working directory")
                except Exception as e:
                    logger.warning("Failed to read .sentinel-ignore: %s", e)

        # Step 3: Run LLM review
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

        llm_response: dict[str, Any] = {}

        if provider == "openai" and openai_key:
            logger.info("Calling OpenAI for review")
            llm_response = _call_openai(diff, file_contents, openai_key)
        elif anthropic_key or provider == "anthropic":
            if not anthropic_key:
                logger.error("ANTHROPIC_API_KEY not set")
                report["errors"].append("ANTHROPIC_API_KEY not set")
                report["status"] = "failed"
                save_report(report, repo, pr_number)
                return 1
            logger.info("Calling Anthropic for review")
            llm_response = _call_anthropic(diff, file_contents, anthropic_key)
        else:
            logger.error("No LLM API key configured")
            report["errors"].append("No LLM API key configured")
            report["status"] = "failed"
            save_report(report, repo, pr_number)
            return 1

        # Step 4: Parse findings
        raw_output = llm_response.get("raw_output", "")
        findings = parse_findings(raw_output)
        logger.info("LLM returned %d findings", len(findings))

        # Step 5: Deduplicate
        findings = deduplicate(findings)
        logger.info("After dedup: %d findings", len(findings))

        # Step 5b: Apply .sentinel-ignore patterns
        ignore_content = file_contents.get(".sentinel-ignore")
        if ignore_content:
            from sentinel_review.workers.ignore_rules import (  # noqa: E402
                filter_ignored_findings,
                parse_ignore_file,
            )

            patterns = parse_ignore_file(ignore_content)
            findings = filter_ignored_findings(findings, patterns)
            logger.info("After .sentinel-ignore: %d findings", len(findings))

        # Step 6: Post review to GitHub
        client = GHAClient()
        try:
            github_comments = [
                {
                    "path": finding.get("file_path", ""),
                    "line": finding.get("line_number") or 1,
                    "body": "**{}** ({})\n\n{}{}".format(
                        finding.get("severity", "UNKNOWN").upper(),
                        finding.get("category", "unknown"),
                        finding.get("comment", ""),
                        "\n\n**Suggested fix:**\n```\n{}\n```".format(finding["suggested_fix"])
                        if finding.get("suggested_fix")
                        else "",
                    ),
                }
                for finding in findings
            ]

            if github_comments:
                review_body = build_review_body(findings, len(github_comments))
                result = client.post_review(repo, pr_number, github_comments, review_body)
                logger.info(
                    "Posted review: %d comments (review_id=%s)",
                    len(github_comments),
                    result.get("id"),
                )
            else:
                client.post_review(
                    repo,
                    pr_number,
                    [],
                    "### ✅ Sentinel Review Complete\n\nNo issues found. The code looks clean! 🎉",
                )
                logger.info("No issues found — posted clean review")
        finally:
            client.close()

        # Step 7: Build report
        elapsed_ms = int((time.time() - start_time) * 1000)
        report["status"] = "completed"
        report["findings"] = findings
        report["total_tokens"] = llm_response.get("total_tokens", 0)
        report["provider"] = llm_response.get("provider", "")
        report["model"] = llm_response.get("model", "")
        report["elapsed_ms"] = elapsed_ms
        report["findings_count"] = len(findings)
        report["summary"] = build_review_body(findings, len(findings))

        save_report(report, repo, pr_number)
        logger.info("Review complete: %d findings in %dms", len(findings), elapsed_ms)
        return 0

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error("Review failed: %s", e)
        report["status"] = "failed"
        report["errors"].append(str(e))
        report["elapsed_ms"] = elapsed_ms
        save_report(report, repo, pr_number)
        return 1


def main() -> int:
    """Entry point for scripts/gha_review.py.

    Reads environment variables, loads the event payload, and calls run().
    """
    _setup_logging()
    logger.info("Sentinel Review starting (GitHub Actions mode)")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        logger.error("GITHUB_REPOSITORY not set")
        return 1

    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path or not Path(event_path).exists():
        logger.error("GITHUB_EVENT_PATH not set or file not found: %s", event_path)
        return 1

    try:
        with open(event_path) as f:
            event = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read event payload: %s", e)
        return 1

    return run(repo, event)
