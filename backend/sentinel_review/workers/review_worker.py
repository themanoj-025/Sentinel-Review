"""
Celery review worker — the core of Sentinel Review.

Fetches PR diffs, file contents, repo context; calls the LLM;
optionally runs Semgrep; deduplicates; posts inline comments.
"""

import logging
import time

from celery import shared_task

from sentinel_review.models.comment import Comment
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review

from .github_client import GitHubClient
from .llm import LLMResult, get_llm_provider

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="reviews",
    acks_late=True,
)
def review_pull_request(
    self,
    installation_id: int,
    repo_id: int,
    repo_full_name: str,
    pr_number: int,
    pr_title: str = "",
    pr_author: str = "",
    head_sha: str = "",
    base_sha: str = "",
    is_private: bool = False,
    account_login: str = "",
    action: str = "opened",
) -> dict:
    """
    Review a pull request: fetch diff, analyze with LLM, post comments.

    This is the main entry point for the review pipeline.
    """
    start_time = time.time()
    logger.info(f"Starting review: {repo_full_name}#{pr_number} ({action})")

    # --- 1. Upsert database records ---
    try:
        install, _ = Installation.objects.get_or_create(
            github_installation_id=installation_id,
            defaults={"account_login": account_login},
        )

        repo_obj, _ = Repo.objects.get_or_create(
            installation=install,
            github_repo_id=repo_id,
            defaults={
                "full_name": repo_full_name,
                "is_private": is_private,
            },
        )

        # Check private repo opt-in
        if is_private and not repo_obj.private_review_allowed:
            logger.info(f"Private repo {repo_full_name} not opted in — skipping review")
            return {"status": "skipped", "reason": "private_repo_not_opted_in"}

        pr_obj, _ = PullRequest.objects.get_or_create(
            repo=repo_obj,
            github_pr_number=pr_number,
            defaults={
                "title": pr_title,
                "author_login": pr_author,
                "head_sha": head_sha,
                "base_sha": base_sha,
                "status": PullRequest.Status.OPEN,
            },
        )

        review_obj = Review.objects.create(
            pull_request=pr_obj,
            triggered_by=action,
            status=Review.Status.PROCESSING,
        )
    except Exception as e:
        logger.error(f"Failed to upsert records for {repo_full_name}#{pr_number}: {e}")
        return {"status": "error", "error": str(e)}

    # --- 2. Fetch diff and context from GitHub ---
    try:
        client = GitHubClient()
        diff = client.get_diff(installation_id, repo_full_name, pr_number)

        # Get repo context (CONTRIBUTING.md, linter configs)
        repo_ctx = client.get_repo_context(installation_id, repo_full_name)

        # Get full file contents for changed files
        changed_files = _parse_changed_files(diff)
        file_contents = {}
        for file_path in changed_files:
            content = client.get_file_content(
                installation_id,
                repo_full_name,
                file_path,
                head_sha or "HEAD",
            )
            if content:
                file_contents[file_path] = content

    except Exception as e:
        error_msg = f"Failed to fetch data from GitHub: {e}"
        logger.error(error_msg)
        review_obj.status = Review.Status.FAILED
        review_obj.error_message = error_msg
        review_obj.save()
        return {"status": "error", "error": error_msg}

    # --- 3. Run LLM review ---
    try:
        provider = get_llm_provider()
        repo_context_str = _build_context_str(repo_ctx)

        llm_result: LLMResult = provider.review_diff(
            diff=diff,
            repo_context=repo_context_str,
            file_contents=file_contents,
        )
    except Exception as e:
        error_msg = f"LLM review failed: {e}"
        logger.error(error_msg)
        review_obj.status = Review.Status.FAILED
        review_obj.error_message = error_msg
        review_obj.save()
        return {"status": "error", "error": error_msg}

    # --- 4. Run Semgrep for independent signal (optional) ---
    semgrep_findings = []
    try:
        from .semgrep_integration import run_semgrep

        semgrep_findings = run_semgrep(file_contents)
        if semgrep_findings:
            logger.info(f"Semgrep found {len(semgrep_findings)} additional findings")
    except Exception as e:
        logger.warning(f"Semgrep integration error (non-fatal): {e}")

    # --- 5. Merge and filter ---
    try:
        from .semgrep_integration import merge_with_llm_findings

        merged = merge_with_llm_findings(llm_result.findings, semgrep_findings)

        # Filter by repo's enabled categories
        enabled_categories = set(repo_obj.enabled_categories)
        merged = [
            m for m in merged
            if m["category"] in enabled_categories
        ]

        # Deduplicate near-identical findings
        merged = _deduplicate(merged)

        # Enforce max comment limit
        max_comments = repo_obj.max_comments
        merged = merged[:max_comments]

    except Exception as e:
        logger.error(f"Post-processing failed: {e}")
        merged = []

    # --- 6. Post inline comments to GitHub ---
    posted_comments = []
    try:
        github_comments = []
        for finding in merged:
            comment_body = finding["comment"]
            if finding.get("high_confidence"):
                comment_body = "🔒 **High confidence** (LLM + Semgrep agreement)\n\n" + comment_body
            if finding.get("suggested_fix"):
                comment_body += f"\n\n**Suggested fix:**\n```\n{finding['suggested_fix']}\n```"

            github_comment = {
                "path": finding["file_path"],
                "line": finding["line_number"] or 1,
                "body": f"**{finding['severity'].upper()}** ({finding['category']})\n\n{comment_body}",
            }
            github_comments.append(github_comment)

        if github_comments:
            review_result = client.post_review(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                comments=github_comments,
                review_body=(
                    f"### 🔍 Sentinel Review Complete\n\n"
                    f"Found **{len(github_comments)}** issue(s) "
                    f"({sum(1 for m in merged if m['severity'] == 'blocking')} blocking, "
                    f"{sum(1 for m in merged if m['severity'] == 'warning')} warnings, "
                    f"{sum(1 for m in merged if m['severity'] == 'nit')} nits)\n\n"
                    f"| Category | Count |\n|----------|------|\n"
                    + "\n".join(
                        f"| {cat} | {sum(1 for m in merged if m['category'] == cat)} |"
                        for cat in sorted(set(m['category'] for m in merged))
                    )
                ),
            )

            # Store GitHub comment IDs
            for i, gh_comment in enumerate(
                review_result.get("comments", [])
            ):
                if i < len(merged):
                    finding = merged[i]
                    posted_comments.append(finding)
                    Comment.objects.create(
                        review=review_obj,
                        github_comment_id=gh_comment.get("id"),
                        file_path=finding["file_path"],
                        line_number=finding.get("line_number"),
                        category=finding["category"],
                        severity=finding["severity"],
                        content=finding["comment"],
                        suggested_fix=finding.get("suggested_fix"),
                    )
        else:
            # Post empty review with a note
            client.post_review(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                comments=[],
                review_body=(
                    "### ✅ Sentinel Review Complete\n\n"
                    "No issues found. The code looks clean! 🎉"
                ),
            )

    except Exception as e:
        error_msg = f"Failed to post review comments: {e}"
        logger.error(error_msg)
        review_obj.status = Review.Status.FAILED
        review_obj.error_message = error_msg
        review_obj.save()
        return {"status": "error", "error": error_msg}

    # --- 7. Finalize review record ---
    elapsed_ms = int((time.time() - start_time) * 1000)
    review_obj.status = Review.Status.COMPLETED
    review_obj.latency_ms = elapsed_ms
    review_obj.token_cost = llm_result.total_tokens
    review_obj.findings_count = len(posted_comments)
    review_obj.save()

    logger.info(
        f"Review complete: {repo_full_name}#{pr_number} — "
        f"{len(posted_comments)} findings in {elapsed_ms}ms "
        f"({llm_result.total_tokens} tokens)"
    )

    return {
        "status": "completed",
        "findings_count": len(posted_comments),
        "latency_ms": elapsed_ms,
        "token_cost": llm_result.total_tokens,
    }


def _parse_changed_files(diff: str) -> list[str]:
    """Parse diff to extract list of changed file paths.

    Standard unified diffs have lines like:
        +++ b/path/to/file.py
    We parse these to extract the file path.
    """
    files = []
    seen = set()
    for line in diff.split("\n"):
        if line.startswith("+++ b/") and not line.startswith("+++ b/dev/null"):
            file_path = line[6:].strip()
            if file_path and file_path not in seen:
                seen.add(file_path)
                files.append(file_path)
    return files


def _build_context_str(repo_ctx) -> str:
    """Build a context string from repo metadata."""
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


def _deduplicate(findings: list[dict]) -> list[dict]:
    """Deduplicate near-identical findings (same file, same line, similar message)."""
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
