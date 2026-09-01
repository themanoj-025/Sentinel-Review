"""
Review pipeline — modular, staged architecture for PR review.

Each stage is an independently testable unit that receives and returns
a typed ReviewContext. The ReviewPipeline orchestrates stage execution.
"""

import logging
import time
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
from .context import ReviewContext
from .github_client import GitHubClient, GitHubRepoContext
from .helpers import (
    _build_context_str,
    _build_review_body,
    _deduplicate,
    _parse_changed_files,
)
from .llm import LLMResult, get_llm_provider
from .pipeline_stages import (
    DedupeStage,
    FetchContextStage,
    FetchDiffStage,
    LLMReviewStage,
    PipelineError,
    PipelineStage,
    PostCommentsStage,
    SemgrepStage,
    UpsertStage,
)
from .schemas import Finding

logger = logging.getLogger(__name__)


def _get_notification_service():
    """Stub notification service — returns a no-op notifier."""
    class _NoopNotifier:
        is_enabled = False
        def notify_failure(self, **kwargs) -> None:
        def notify_blocking_findings(self, **kwargs) -> Any:
    return _NoopNotifier()


# Base Stage


class ReviewPipeline:
    """Orchestrates the execution of pipeline stages."""

    def __init__(self) -> None:
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
) -> float -> None:
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



