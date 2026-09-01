"""Shared pipeline context — extracted to break circular imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentinel_review.models.installation import Installation
    from sentinel_review.models.pull_request import PullRequest
    from sentinel_review.models.repo import Repo
    from sentinel_review.models.review import Review

from .github_client import GitHubClient, GitHubRepoContext
from .llm import LLMResult


@dataclass
class ReviewContext:
    """Typed context object passed through pipeline stages."""

    # Input params
    installation_id: int = 0
    repo_id: int = 0
    repo_full_name: str = ""
    pr_number: int = 0
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
