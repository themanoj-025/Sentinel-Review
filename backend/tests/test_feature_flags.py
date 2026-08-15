"""Tests for the feature flag service."""

from __future__ import annotations

from sentinel_review.workers.feature_flags import FeatureFlags, FeatureFlagService


class TestFeatureFlags:
    """Tests for the FeatureFlags typed container."""

    def test_defaults_when_config_empty(self):
        """All flags should have safe defaults when config is None or empty."""
        flags = FeatureFlags({})
        assert flags.disable_style_nits is False
        assert flags.security_only_review is False
        assert flags.max_comments_per_file == 0
        assert flags.disable_semgrep is False
        assert flags.max_comments == 25

    def test_defaults_when_config_none(self):
        flags = FeatureFlags(None)
        assert flags.disable_style_nits is False
        assert flags.security_only_review is False

    def test_disable_style_nits_removes_style_from_categories(self):
        flags = FeatureFlags({"disable_style_nits": True})
        categories = flags.enabled_categories
        assert "style" not in categories
        assert "bug" in categories
        assert "security" in categories
        assert "suggestion" in categories

    def test_security_only_review_only_has_security(self):
        flags = FeatureFlags({"security_only_review": True})
        assert flags.enabled_categories == ["security"]

    def test_security_only_review_overrides_disable_style_nits(self):
        """security_only_review is stricter and overrides disable_style_nits."""
        flags = FeatureFlags({"security_only_review": True, "disable_style_nits": True})
        assert flags.enabled_categories == ["security"]

    def test_max_comments_per_file_parsed_from_config(self):
        flags = FeatureFlags({"max_comments_per_file": "5"})
        assert flags.max_comments_per_file == 5

    def test_disable_semgrep_flag(self):
        flags = FeatureFlags({"disable_semgrep": True})
        assert flags.disable_semgrep is True

    def test_max_comments_parsed(self):
        flags = FeatureFlags({"max_comments": 50})
        assert flags.max_comments == 50


class TestFeatureFlagService:
    """Tests for the FeatureFlagService static methods."""

    def test_from_repo_config_none(self):
        flags = FeatureFlagService.from_repo_config(None)
        assert flags.disable_style_nits is False
        assert flags.max_comments == 25

    def test_from_repo_config_empty_dict(self):
        flags = FeatureFlagService.from_repo_config({})
        assert flags.disable_style_nits is False

    def test_from_repo_config_with_flags(self):
        flags = FeatureFlagService.from_repo_config(
            {"disable_style_nits": True, "max_comments_per_file": 3}
        )
        assert flags.disable_style_nits is True
        assert flags.max_comments_per_file == 3


class TestFilterFindings:
    """Tests for the filter_findings static method."""

    SAMPLE_FINDINGS = [
        {
            "file_path": "src/app.py",
            "line_number": 10,
            "category": "bug",
            "severity": "blocking",
            "comment": "Bug 1",
        },
        {
            "file_path": "src/app.py",
            "line_number": 20,
            "category": "security",
            "severity": "blocking",
            "comment": "Security 1",
        },
        {
            "file_path": "src/app.py",
            "line_number": 30,
            "category": "style",
            "severity": "nit",
            "comment": "Style 1",
        },
        {
            "file_path": "src/app.py",
            "line_number": 40,
            "category": "style",
            "severity": "nit",
            "comment": "Style 2",
        },
        {
            "file_path": "src/utils.py",
            "line_number": 5,
            "category": "suggestion",
            "severity": "warning",
            "comment": "Suggestion 1",
        },
        {
            "file_path": "src/utils.py",
            "line_number": 10,
            "category": "bug",
            "severity": "warning",
            "comment": "Bug 2",
        },
        {
            "file_path": "src/config.py",
            "line_number": 1,
            "category": "security",
            "severity": "blocking",
            "comment": "Hardcoded secret",
        },
    ]

    # disable_style_nits

    def test_disable_style_nits_filters_style_findings(self):
        """Setting disable_style_nits should remove style-category findings."""
        flags = FeatureFlags({"disable_style_nits": True})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        categories = {f.get("category") for f in result}
        assert "style" not in categories
        assert len(result) == 5  # 7 - 2 style = 5

    def test_disable_style_nits_false_keeps_style(self):
        """When disable_style_nits is False, style findings should remain."""
        flags = FeatureFlags({"disable_style_nits": False})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        categories = {f.get("category") for f in result}
        assert "style" in categories
        assert len(result) == 7

    # security_only_review

    def test_security_only_review_keeps_only_security(self):
        """security_only_review should only keep security-category findings."""
        flags = FeatureFlags({"security_only_review": True})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        categories = {f.get("category") for f in result}
        assert categories == {"security"}
        assert len(result) == 2  # Security 1 + Hardcoded secret

    # max_comments_per_file

    def test_max_comments_per_file_limits_per_file(self):
        """Setting max_comments_per_file should cap comments per file path."""
        flags = FeatureFlags({"max_comments_per_file": 2})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        # src/app.py has 4 findings → capped to 2
        # src/utils.py has 2 findings → stays at 2
        # src/config.py has 1 finding → stays at 1
        app_count = sum(1 for f in result if f.get("file_path") == "src/app.py")
        utils_count = sum(1 for f in result if f.get("file_path") == "src/utils.py")
        config_count = sum(1 for f in result if f.get("file_path") == "src/config.py")
        assert app_count == 2, f"Expected 2 for app.py, got {app_count}"
        assert utils_count == 2, f"Expected 2 for utils.py, got {utils_count}"
        assert config_count == 1, f"Expected 1 for config.py, got {config_count}"
        assert len(result) == 5  # 2 + 2 + 1 = 5

    def test_max_comments_per_file_zero_is_unlimited(self):
        """max_comments_per_file=0 should be unlimited."""
        flags = FeatureFlags({"max_comments_per_file": 0})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        assert len(result) == len(self.SAMPLE_FINDINGS)

    def test_max_comments_per_file_negative_is_unlimited(self):
        """max_comments_per_file negative should be unlimited."""
        flags = FeatureFlags({"max_comments_per_file": -1})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        assert len(result) == len(self.SAMPLE_FINDINGS)

    # max_comments (total limit)

    def test_max_comments_total_limit(self):
        """max_comments should cap total findings across all files."""
        flags = FeatureFlags({"max_comments": 3})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        assert len(result) == 3

    def test_max_comments_zero_is_unlimited(self):
        """max_comments=0 should be unlimited."""
        flags = FeatureFlags({"max_comments": 0})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        assert len(result) == len(self.SAMPLE_FINDINGS)

    # Combination scenarios

    def test_disable_style_nits_and_max_comments_per_file(self):
        """Both flags should apply together — style first, then per-file limit."""
        flags = FeatureFlags({"disable_style_nits": True, "max_comments_per_file": 2})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        # After style filter: 5 findings
        # src/app.py has 2 (Bug 1, Security 1) → capped to 2 (same)
        # src/utils.py has 2 (Suggestion 1, Bug 2) → stays at 2
        # src/config.py has 1 → stays at 1
        assert len(result) == 5
        assert "style" not in {f.get("category") for f in result}

    def test_security_only_and_max_comments_per_file(self):
        """security_only_review + per-file limit should compose correctly."""
        flags = FeatureFlags({"security_only_review": True, "max_comments_per_file": 1})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        # After security filter: 2 findings (Security 1, Hardcoded secret) — different files
        # Per-file limit of 1 doesn't affect them
        assert len(result) == 2
        assert all(f.get("category") == "security" for f in result)

    def test_unset_flags_dont_crash(self):
        """When feature flags are not set in config, filtering should work fine."""
        flags = FeatureFlagService.from_repo_config({})
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        assert len(result) == len(self.SAMPLE_FINDINGS)  # All pass through

    def test_empty_findings_list(self):
        """An empty findings list should return empty."""
        flags = FeatureFlags({"disable_style_nits": True})
        result = FeatureFlagService.filter_findings([], flags)
        assert result == []

    def test_findings_without_category_are_filtered_out(self):
        """Findings missing a 'category' key should be filtered out (empty string not in defaults)."""
        flags = FeatureFlags({})
        weird_findings = [
            {"file_path": "foo.py", "comment": "No category"},
        ]
        result = FeatureFlagService.filter_findings(weird_findings, flags)
        # Empty string category is not in default categories, so it's filtered
        assert len(result) == 0

    def test_security_only_filters_findings_without_category(self):
        """security_only_review should filter out findings without a category."""
        flags = FeatureFlags({"security_only_review": True})
        weird_findings = [
            {"file_path": "foo.py", "comment": "No category"},
            {"file_path": "bar.py", "category": "security", "comment": "Real finding"},
        ]
        result = FeatureFlagService.filter_findings(weird_findings, flags)
        assert len(result) == 1
        assert result[0].get("file_path") == "bar.py"

    def test_filter_findings_does_not_mutate_input(self):
        """filter_findings should return a new list, not mutate the input."""
        flags = FeatureFlags({"disable_style_nits": True})
        original_len = len(self.SAMPLE_FINDINGS)
        result = FeatureFlagService.filter_findings(self.SAMPLE_FINDINGS, flags)
        assert len(self.SAMPLE_FINDINGS) == original_len  # Unchanged
        assert result is not self.SAMPLE_FINDINGS  # Different object

    def test_multiple_files_with_max_comments_per_file(self):
        """More complex scenario: many files each with multiple comments."""
        findings = [
            {"file_path": f"src/{chr(97 + i)}.py", "category": "bug", "comment": f"Bug {i}"}
            for i in range(10)
            for _ in range(3)  # 3 per file, 10 files = 30 findings
        ]
        flags = FeatureFlags({"max_comments_per_file": 2})
        result = FeatureFlagService.filter_findings(findings, flags)
        assert len(result) == 20  # 2 per file × 10 files
