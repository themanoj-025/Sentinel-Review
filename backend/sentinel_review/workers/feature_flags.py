"""
Feature flag service for per-repo configuration.

Reads feature flags from the Repo.config JSONField and provides
safe defaults for all flags. Used by the pipeline stages to gate
behaviors like category filtering, per-file comment limits, and
Semgrep invocation.

Supported flags (in Repo.config):
    disable_style_nits (bool):
        When True, filters out all findings with category="style"
        or severity="nit". Default: False.

    security_only_review (bool):
        When True, filters out all non-security findings.
        Overrides disable_style_nits if both are True. Default: False.

    max_comments_per_file (int):
        Maximum number of comments allowed per file path.
        0 or negative means unlimited. Default: 0 (unlimited).

    disable_semgrep (bool):
        When True, skips the Semgrep analysis stage entirely.
        Default: False.

    max_comments (int):
        Maximum total comments across all files.
        (Already exists in DedupeStage; exposed here for consistency.)
        Default: 25.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Flag definitions with defaults


class FeatureFlags:
    """Typed container for resolved feature flag values."""

    # Default categories when nothing is specified in config
    _DEFAULT_CATEGORIES = ["bug", "security", "style", "suggestion"]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}

        self.disable_style_nits: bool = bool(cfg.get("disable_style_nits", False))
        self.security_only_review: bool = bool(cfg.get("security_only_review", False))
        self.max_comments_per_file: int = int(cfg.get("max_comments_per_file", 0))
        self.disable_semgrep: bool = bool(cfg.get("disable_semgrep", False))
        self.max_comments: int = int(cfg.get("max_comments", 25))

        # Preserve the raw enabled_categories from config (may be customized
        # via Repo.enabled_categories setter, dashboard, or API)
        self._raw_enabled_categories: list[str] | None = cfg.get("enabled_categories")

    @property
    def enabled_categories(self) -> list[str]:
        """Resolve effective enabled categories based on feature flags.

        Starts with the repo's configured enabled_categories (if any),
        then applies feature flag overrides on top.
        """
        if self.security_only_review:
            return ["security"]

        # Use the repo's configured categories as the base
        if self._raw_enabled_categories is not None:
            all_categories = list(self._raw_enabled_categories)
        else:
            all_categories = list(self._DEFAULT_CATEGORIES)

        if self.disable_style_nits:
            all_categories = [c for c in all_categories if c != "style"]

        return all_categories

    def is_enabled(self, category: str) -> bool:
        """Check if a specific category is enabled."""
        return category in self.enabled_categories


class FeatureFlagService:
    """Reads and resolves feature flags from a Repo object or raw config dict."""

    @staticmethod
    def from_repo_config(config: dict[str, Any] | None) -> FeatureFlags:
        """Build FeatureFlags from a Repo.config JSONField value."""
        return FeatureFlags(config or {})

    @staticmethod
    def filter_findings(
        findings: list[dict[str, Any]],
        flags: FeatureFlags,
    ) -> list[dict[str, Any]]:
        """Filter a list of findings based on active feature flags.

        Applies:
        1. Category filtering (security_only_review, disable_style_nits)
        2. Per-file comment limits (max_comments_per_file)
        3. Total comment limit (max_comments)

        Returns filtered copy; does not mutate input.
        """
        filtered = list(findings)

        # 1. Category filtering
        filtered = [f for f in filtered if flags.is_enabled(f.get("category", ""))]

        # 2. Per-file comment limit
        if flags.max_comments_per_file > 0:
            per_file: dict[str, int] = {}
            capped: list[dict[str, Any]] = []
            for f in filtered:
                file_path = f.get("file_path", "__unknown__")
                count = per_file.get(file_path, 0)
                if count < flags.max_comments_per_file:
                    per_file[file_path] = count + 1
                    capped.append(f)
                else:
                    logger.debug(
                        "Dropped finding (file %s exceeds %d/limit): %s",
                        file_path,
                        flags.max_comments_per_file,
                        f.get("comment", "")[:60],
                    )
            filtered = capped

        # 3. Total comment limit
        if flags.max_comments > 0 and len(filtered) > flags.max_comments:
            filtered = filtered[: flags.max_comments]

        return filtered
