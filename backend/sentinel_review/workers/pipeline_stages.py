"""Pipeline stage classes — extracted from pipeline.py."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.db import IntegrityError

from sentinel_review.api.metrics import (
    llm_cache_hits,
    llm_cache_misses,
    review_latency,
    reviews_total,
)
from sentinel_review.models.comment import Comment
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review

from .cache import cache_get, cache_set
from .github_client import GitHubClient, GitHubRepoContext
from .context import ReviewContext
from .helpers import _build_context_str, _build_review_body, _deduplicate, _parse_changed_files
from .llm import LLMResult, get_llm_provider
from .schemas import Finding

logger = logging.getLogger(__name__)


def _get_notification_service():
    """Stub notification service — returns a no-op notifier."""
    class _NoopNotifier:
        is_enabled = False
        def notify_failure(self, **kwargs): pass
        def notify_blocking_findings(self, **kwargs): pass
    return _NoopNotifier()


class PipelineStage:
    """Base class for pipeline stages."""

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        """Execute this stage. Returns the (possibly mutated) context."""
        raise NotImplementedError


# Exception


class PipelineError(Exception):
    """Raised when a pipeline stage fails catastrophically."""

    def __init__(self, message: str, context: ReviewContext | None = None) -> None:
        super().__init__(message)
        self.context = context


# Stage 1: Upsert database records


class UpsertStage(PipelineStage):
    """Upsert Installation, Repo, PullRequest, and create Review record."""

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        try:
            install, _ = Installation.objects.get_or_create(
                github_installation_id=ctx.installation_id,
                defaults={"account_login": ctx.account_login},
            )
            ctx.install = install

            repo_obj, _ = Repo.objects.get_or_create(
                installation=install,
                github_repo_id=ctx.repo_id,
                defaults={
                    "full_name": ctx.repo_full_name,
                    "is_private": ctx.is_private,
                },
            )
            ctx.repo_obj = repo_obj

            # Check private repo opt-in
            if ctx.is_private and not repo_obj.private_review_allowed:
                ctx.skip_reason = "private_repo_not_opted_in"
                logger.info("Private repo %s not opted in — skipping review", ctx.repo_full_name)
                return ctx

            pr_obj, _ = PullRequest.objects.get_or_create(
                repo=repo_obj,
                github_pr_number=ctx.pr_number,
                defaults={
                    "title": ctx.pr_title,
                    "author_login": ctx.pr_author,
                    "head_sha": ctx.head_sha,
                    "base_sha": ctx.base_sha,
                    "status": PullRequest.Status.OPEN,
                },
            )
            ctx.pr_obj = pr_obj

            review_obj = Review.objects.create(
                pull_request=pr_obj,
                triggered_by=ctx.action,
                status=Review.Status.PROCESSING,
            )
            ctx.review_obj = review_obj

        except (IntegrityError, KeyError, ValueError) as e:
            raise PipelineError(
                f"Failed to upsert records: {e}",
                context=ctx,
            )

        return ctx


# Stage 2: Fetch diff from GitHub


class FetchDiffStage(PipelineStage):
    """Fetch PR diff and changed file contents from GitHub."""

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        client = ctx.client or GitHubClient()
        ctx.client = client

        try:
            ctx.diff = client.get_diff(ctx.installation_id, ctx.repo_full_name, ctx.pr_number)

            changed_files = _parse_changed_files(ctx.diff)
            file_contents = {}
            for file_path in changed_files:
                content = client.get_file_content(
                    ctx.installation_id,
                    ctx.repo_full_name,
                    file_path,
                    ctx.head_sha or "HEAD",
                )
                if content:
                    file_contents[file_path] = content
            ctx.file_contents = file_contents

        except (ConnectionError, TimeoutError) as e:
            raise PipelineError(f"Failed to fetch data from GitHub: {e}", context=ctx)

        return ctx


# Stage 3: Fetch repo context


class FetchContextStage(PipelineStage):
    """Fetch repository metadata (default branch, CONTRIBUTING.md, linter configs, .sentinel-ignore)."""

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        client = ctx.client or GitHubClient()
        ctx.client = client

        try:
            ctx.repo_ctx = client.get_repo_context(ctx.installation_id, ctx.repo_full_name)

            # Fetch .sentinel-ignore from the repository (if it exists)
            # This is independent of whether it's in the current PR diff
            if ctx.repo_ctx and ctx.repo_ctx.default_branch:
                try:
                    ignore_content = client.get_file_content(
                        ctx.installation_id,
                        ctx.repo_full_name,
                        ".sentinel-ignore",
                        ctx.repo_ctx.default_branch,
                    )
                    if ignore_content:
                        ctx.file_contents[".sentinel-ignore"] = ignore_content
                        logger.info(
                            "Fetched .sentinel-ignore from %s (on %s)",
                            ctx.repo_full_name,
                            ctx.repo_ctx.default_branch,
                        )
                except (OSError, KeyError, ValueError):
                    logger.debug(".sentinel-ignore not found in %s (non-fatal)", ctx.repo_full_name)

        except (ConnectionError, TimeoutError) as e:
            logger.warning("Failed to fetch repo context (non-fatal): %s", e)
            ctx.repo_ctx = GitHubRepoContext(full_name=ctx.repo_full_name)

        return ctx


# Stage 4: Run LLM review


class LLMReviewStage(PipelineStage):
    """Run the LLM review on the diff with repo context.

    Checks the LLM response cache before calling the provider.
    On a cache hit, skips the API call entirely.
    On a cache miss, stores the result for future requests.
    """

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        try:
            repo_context_str = _build_context_str(ctx.repo_ctx) if ctx.repo_ctx else ""

            # Extract custom instructions from repo config (4.1)
            custom_instructions = None
            if ctx.repo_obj and ctx.repo_obj.config:
                custom_instructions = ctx.repo_obj.config.get("custom_instructions")

            # Check cache first
            cached = cache_get(ctx.diff, repo_context_str)
            if cached is not None:
                logger.info(
                    "LLM cache HIT for %s#%d — skipping API call",
                    ctx.repo_full_name,
                    ctx.pr_number,
                )
                ctx.llm_result = cached
                ctx.llm_findings = cached.findings
                llm_cache_hits.inc()
                return ctx

            llm_cache_misses.inc()

            # Cache miss — call the LLM provider
            provider = get_llm_provider()
            ctx.llm_result = provider.review_diff(
                diff=ctx.diff,
                repo_context=repo_context_str,
                file_contents=ctx.file_contents,
                custom_instructions=custom_instructions,
            )
            ctx.llm_findings = ctx.llm_result.findings

            # Store in cache (only cache successful results)
            if ctx.llm_result.validation_success:
                cache_set(ctx.diff, ctx.llm_result, repo_context_str)

        except (RuntimeError, ValueError, OSError) as e:
            raise PipelineError(f"LLM review failed: {e}", context=ctx)

        return ctx


# Stage 5: Run Semgrep (optional)


class SemgrepStage(PipelineStage):
    """Run Semgrep static analysis — dispatched asynchronously (4.5).

    Dispatches Semgrep to a separate Celery task that runs in parallel
    with the LLM call. The DedupeStage merges results after both complete.
    If Semgrep is disabled or fails, continues with LLM-only findings.
    """

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        # Check feature flag: disable_semgrep
        if ctx.repo_obj:
            from .feature_flags import FeatureFlagService

            flags = FeatureFlagService.from_repo_config(ctx.repo_obj.config)
            if flags.disable_semgrep:
                logger.info(
                    "Semgrep disabled by feature flag for %s",
                    ctx.repo_full_name,
                )
                return ctx

        if not ctx.file_contents:
            return ctx

        try:
            from .semgrep_integration import run_semgrep_async

            # Dispatch Semgrep to a Celery task — runs in parallel with LLM
            task = run_semgrep_async.delay(ctx.file_contents)
            ctx._semgrep_task = task
            logger.info(
                "Dispatched async Semgrep for %s (task_id=%s)",
                ctx.repo_full_name,
                task.id,
            )
        except (OSError, RuntimeError) as e:
            logger.warning("Failed to dispatch async Semgrep (non-fatal): %s", e)

        return ctx


# Stage 6: Deduplicate and filter findings


class DedupeStage(PipelineStage):
    """Merge LLM and Semgrep findings, deduplicate, filter by category, enforce limit.

    Also applies .sentinel-ignore patterns if the file exists in the repo.
    Feature flags (disable_style_nits, security_only_review, max_comments_per_file)
    are applied here.
    """

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        try:
            # Retrieve async Semgrep results if a task was dispatched (4.5)
            if ctx._semgrep_task is not None:
                try:
                    semgrep_result = ctx._semgrep_task.get(timeout=30, disable_sync_subtasks=False)
                    if semgrep_result:
                        ctx.semgrep_findings = [Finding(**f) for f in semgrep_result]
                        logger.info(
                            "Async Semgrep returned %d findings",
                            len(ctx.semgrep_findings),
                        )
                    else:
                        ctx.semgrep_findings = []
                except (TimeoutError, OSError, RuntimeError) as e:
                    logger.warning("Async Semgrep timed out or failed (non-fatal): %s", e)
                    ctx.semgrep_findings = []

            from .semgrep_integration import merge_with_llm_findings

            merged = merge_with_llm_findings(ctx.llm_findings, ctx.semgrep_findings)

            if ctx.repo_obj:
                from .feature_flags import FeatureFlagService

                flags = FeatureFlagService.from_repo_config(ctx.repo_obj.config)

                # Apply feature flag filtering (category, per-file limits, total limits)
                merged = FeatureFlagService.filter_findings(merged, flags)
            else:
                # Fallback: no repo config, use traditional category filtering
                merged = [m for m in merged if m.get("category") in _DEFAULT_CATEGORIES]

            # Apply .sentinel-ignore patterns (if file is available in repo)
            try:
                ignore_content = ctx.file_contents.get(".sentinel-ignore")
                if ignore_content:
                    from .ignore_rules import filter_ignored_findings, parse_ignore_file

                    patterns = parse_ignore_file(ignore_content)
                    merged = filter_ignored_findings(merged, patterns)
            except (KeyError, ValueError, TypeError, ImportError):
                logger.debug("Failed to apply .sentinel-ignore patterns (non-fatal)")

            # Deduplicate
            merged = _deduplicate(merged)

            ctx.merged_findings = merged

        except (KeyError, ValueError) as e:
            logger.error("Post-processing failed: %s", e)
            ctx.merged_findings = []

        return ctx


# Stage 7: Post comments to GitHub


class PostCommentsStage(PipelineStage):
    """Post inline review comments to GitHub and store in database."""

    def execute(self, ctx: ReviewContext) -> ReviewContext:
        client = ctx.client or GitHubClient()
        ctx.client = client
        posted_comments = []

        try:
            if not ctx.review_obj:
                raise PipelineError("Review object not created", context=ctx)

            github_comments = []
            for finding in ctx.merged_findings:
                comment_body = finding.get("comment", "")
                if finding.get("high_confidence"):
                    comment_body = (
                        "🔒 **High confidence** (LLM + Semgrep agreement)\n\n" + comment_body
                    )
                if finding.get("suggested_fix"):
                    comment_body += "\n\n**Suggested fix:**\n```\n{}\n```".format(
                        finding["suggested_fix"]
                    )

                github_comment = {
                    "path": finding.get("file_path", ""),
                    "line": finding.get("line_number") or 1,
                    "body": "**{}** ({})\n\n{}".format(
                        finding.get("severity", "UNKNOWN").upper(),
                        finding.get("category", "unknown"),
                        comment_body,
                    ),
                }
                github_comments.append(github_comment)

            if github_comments:
                review_result = client.post_review(
                    installation_id=ctx.installation_id,
                    repo_full_name=ctx.repo_full_name,
                    pr_number=ctx.pr_number,
                    comments=github_comments,
                    review_body=_build_review_body(ctx.merged_findings, len(github_comments)),
                )

                # Post a PR-level summary comment (4.4)
                self._post_summary_comment(ctx, client, len(github_comments))

                # Store GitHub comment IDs
                for i, gh_comment in enumerate(review_result.get("comments", [])):
                    if i < len(ctx.merged_findings):
                        finding = ctx.merged_findings[i]
                        posted_comments.append(finding)
                        Comment.objects.create(
                            review=ctx.review_obj,
                            github_comment_id=gh_comment.get("id"),
                            file_path=finding.get("file_path", ""),
                            line_number=finding.get("line_number"),
                            category=finding.get("category", "suggestion"),
                            severity=finding.get("severity", "warning"),
                            content=finding.get("comment", ""),
                            suggested_fix=finding.get("suggested_fix"),
                        )
            else:
                client.post_review(
                    installation_id=ctx.installation_id,
                    repo_full_name=ctx.repo_full_name,
                    pr_number=ctx.pr_number,
                    comments=[],
                    review_body="### ✅ Sentinel Review Complete\n\nNo issues found. The code looks clean! 🎉",
                )

            ctx.posted_comments = posted_comments

            # Notify on blocking findings
            blocking_findings = [f for f in ctx.merged_findings if f.get("severity") == "blocking"]
            if blocking_findings:
                preview_lines = [
                    f"`{f.get('file_path', '?')}:{f.get('line_number', '?')}` — "
                    f"{f.get('comment', '')[:80]}"
                    for f in blocking_findings
                ]
                notifier = _get_notification_service()
                if notifier.is_enabled:
                    notifier.notify_blocking_findings(
                        repo_full_name=ctx.repo_full_name,
                        pr_number=ctx.pr_number,
                        pr_title=ctx.pr_title,
                        blocking_count=len(blocking_findings),
                        findings_preview=preview_lines,
                    )

        except (ConnectionError, TimeoutError, KeyError, ValueError) as e:
            raise PipelineError(f"Failed to post review comments: {e}", context=ctx)

        return ctx

    def _post_summary_comment(
        self,
        ctx: ReviewContext,
        client: GitHubClient,
        inline_count: int,
    ) -> None:
        """Post a top-level PR summary comment alongside inline comments (4.4)."""
        blocking = sum(1 for f in ctx.merged_findings if f.get("severity") == "blocking")
        warnings = sum(1 for f in ctx.merged_findings if f.get("severity") == "warning")
        nits = sum(1 for f in ctx.merged_findings if f.get("severity") == "nit")
        categories = sorted({f.get("category", "unknown") for f in ctx.merged_findings})
        cat_rows = "\n".join(
            "| %s | %d |" % (cat, sum(1 for f in ctx.merged_findings if f.get("category") == cat))
            for cat in categories
        )

        summary_body = (
            f"### 🛡️ Sentinel Review — Summary\n\n"
            f"Found **{inline_count}** issue(s) "
            f"({blocking} blocking, {warnings} warnings, {nits} nits)\n\n"
            f"| Category | Count |\n|----------|------|\n{cat_rows}\n\n"
        )

        if blocking > 0:
            summary_body += (
                "🔴 **Action required:** %d blocking issue(s) found. "
                "These should be resolved before merging.\n\n"
            ) % blocking

        if inline_count > 0:
            summary_body += (
                "📝 See inline comments on the diff for exact locations and suggested fixes.\n\n"
            )

        if ctx.llm_result:
            summary_body += (
                f"*Model:* `{ctx.llm_result.provider}/{ctx.llm_result.model}` | "
                f"*Tokens:* {ctx.llm_result.total_tokens} | "
                f"*Latency:* {ctx.elapsed_ms}ms"
            )

        try:
            client._request(
                "POST",
                f"/repos/{ctx.repo_full_name}/issues/{ctx.pr_number}/comments",
                installation_id=ctx.installation_id,
                json={"body": summary_body},
            )
            logger.info("Posted summary comment to %s#%d", ctx.repo_full_name, ctx.pr_number)
        except (OSError, RuntimeError) as e:
            logger.warning("Failed to post summary comment (non-fatal): %s", e)


# Pipeline Orchestrator


