"""
Review pipeline — modular, staged architecture for PR review.

Each stage is an independently testable unit that receives and returns
a typed ReviewContext. The ReviewPipeline orchestrates stage execution.
"""

import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
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
from .llm import LLMResult, get_llm_provider
from .pipeline_stages import (
    DedupeStage,
    FetchContextStage,
    FetchDiffStage,
    LLMReviewStage,
    PipelineStage,
    PostCommentsStage,
    SemgrepStage,
    UpsertStage,
)
from .schemas import Finding

logger = logging.getLogger(__name__)

class ReviewContext:
    """Typed context object passed through pipeline stages."""

    # Input params
    installation_id: int
    repo_id: int
    repo_full_name: str
    pr_number: int
    pr_title: str = ""
    pr_author: str = ""
    head_sha: str = ""
    base_sha: str = ""
    is_private: bool = False
    account_login: str = ""
    action: str = "opened"

    # DB objects (populated by UpsertStage)
    review_obj: Review | None = None
    repo_obj: Repo | None = None
    pr_obj: PullRequest | None = None
    install: Installation | None = None

    # Fetched data (populated by FetchDiffStage, FetchContextStage)
    diff: str = ""
    repo_ctx: GitHubRepoContext | None = None
    file_contents: dict[str, str] = field(default_factory=dict)

    # Results (populated by LLMReviewStage, SemgrepStage, DedupeStage)
    llm_result: LLMResult | None = None
    llm_findings: list = field(default_factory=list)
    semgrep_findings: list = field(default_factory=list)
    merged_findings: list[dict[str, Any]] = field(default_factory=list)
    posted_comments: list[dict[str, Any]] = field(default_factory=list)

    # Metrics
    start_time: float = 0.0
    elapsed_ms: int = 0
    errors: list[str] = field(default_factory=list)
    skip_reason: str = ""

    # GitHub client (shared across stages)
    client: GitHubClient | None = None

    # Async Semgrep task reference (populated by SemgrepStage)
    _semgrep_task: Any | None = None


# Base Stage


class ReviewPipeline:
    """Orchestrates the execution of pipeline stages."""

    def __init__(self) -> Any:
        self.stages: list[PipelineStage] = [
            UpsertStage(),
            FetchDiffStage(),
            FetchContextStage(),
            LLMReviewStage(),
            SemgrepStage(),
            DedupeStage(),
            PostCommentsStage(),
        ]

    def run(self, ctx: ReviewContext) -> ReviewContext:
        """Execute all stages in order. Returns the final context."""
        ctx.start_time = time.time()

        for stage in self.stages:
            # Check for skip condition (private repo opt-out)
            if ctx.skip_reason:
                break

            try:
                ctx = stage.execute(ctx)
            except PipelineError as e:
                ctx = self._handle_stage_failure(ctx, stage, e)
                return ctx
            except (RuntimeError, OSError, ValueError, TypeError) as e:
                error_msg = f"Unexpected error in {stage.__class__.__name__}: {e}"
                ctx = self._handle_stage_failure(ctx, stage, e, error_msg)
                return ctx

        # Finalize review record
        ctx.elapsed_ms = int((time.time() - ctx.start_time) * 1000)
        if ctx.review_obj and not ctx.skip_reason:
            ctx.review_obj.status = Review.Status.COMPLETED
            ctx.review_obj.latency_ms = ctx.elapsed_ms
            ctx.review_obj.token_cost = ctx.llm_result.total_tokens if ctx.llm_result else 0
            ctx.review_obj.findings_count = len(ctx.posted_comments)
            # Estimate USD cost from token count and model pricing (4.3)
            if ctx.llm_result:
                ctx.review_obj.estimated_cost_usd = estimate_cost_usd(
                    ctx.llm_result.provider,
                    ctx.llm_result.model,
                    ctx.llm_result.total_tokens,
                )
            ctx.review_obj.save()

            # Record metrics
            review_latency.labels(status="completed").observe(ctx.elapsed_ms)
            reviews_total.labels(status="completed").inc()

            logger.info(
                "Review complete: %s#%d — %d findings in %dms (%d tokens)",
                ctx.repo_full_name,
                ctx.pr_number,
                len(ctx.posted_comments),
                ctx.elapsed_ms,
                ctx.llm_result.total_tokens if ctx.llm_result else 0,
            )
        elif ctx.errors:
            reviews_total.labels(status="failed").inc()
        elif ctx.skip_reason:
            reviews_total.labels(status="skipped").inc()

        return ctx

    def _handle_stage_failure(
        self,
        ctx: ReviewContext,
        stage: PipelineStage,
        error: Exception,
        error_msg: str | None = None,
    ) -> ReviewContext:
        """Handle a pipeline stage failure — mark review as failed, log, and notify."""
        if error_msg is None:
            error_msg = str(error)
        ctx.errors.append(error_msg)

        # Mark review as failed if it was created
        if ctx.review_obj:
            ctx.review_obj.status = Review.Status.FAILED
            ctx.review_obj.error_message = error_msg
            ctx.review_obj.save()

        logger.error("Pipeline stage %s failed: %s", stage.__class__.__name__, error_msg)

        # Notify on pipeline failure
        notifier = _get_notification_service()
        if notifier.is_enabled:
            notifier.notify_failure(
                repo_full_name=ctx.repo_full_name,
                pr_number=ctx.pr_number,
                error_message=error_msg,
                stage_name=stage.__class__.__name__,
            )

        return ctx


# Approximate per-model pricing per 1K tokens (USD) — updated 2026-07
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
#         https://openai.com/pricing
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-20250514": (3.0, 15.0),  # input, output per 1K tokens ($)
    "claude-sonnet-4": (3.0, 15.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-2024-08-06": (2.5, 10.0),
}


def estimate_cost_usd(
    provider: str, model: str, total_tokens: int, input_tokens: int | None = None
) -> float:
    """Estimate the USD cost of an LLM call based on token count and model pricing.

    Uses a rough 3:1 input-to-output ratio if input_tokens is not provided.
    """
    pricing = _MODEL_PRICING.get(model)
    if not pricing:
        # Fallback: assume 50/50 split at a conservative $5/$15 per 1K
        return round((total_tokens / 1000) * 5.0, 2)

    input_price, output_price = pricing
    if input_tokens:
        output_tokens = total_tokens - input_tokens
    else:
        # Assume roughly 3:1 input:output ratio
        input_tokens = int(total_tokens * 0.75)
        output_tokens = total_tokens - input_tokens

    cost = (input_tokens / 1000 * input_price) + (output_tokens / 1000 * output_price)
    return round(cost, 4)


# Helper Functions


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


def _build_context_str(repo_ctx) -> str:
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
