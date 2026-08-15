"""
Tests for the LLM provider abstraction layer.

Covers:
- AnthropicProvider initialization and configuration
- OpenAIProvider initialization and configuration
- Prompt building (with/without context)
- JSON validation and parsing
- Malformed output handling
- Error state handling
- get_llm_provider factory function
"""

from __future__ import annotations

import json

import pytest
from sentinel_review.workers.llm import (
    AnthropicProvider,
    LLMProvider,
    LLMResult,
    OpenAIProvider,
    get_llm_provider,
)


class TestLLMResult:
    """Tests for the LLMResult dataclass."""

    def test_default_values(self):
        """LLMResult should have sensible defaults."""
        result = LLMResult()
        assert result.findings == []
        assert result.raw_output == ""
        assert result.total_tokens == 0
        assert result.latency_ms == 0
        assert result.validation_success is True
        assert result.error_message == ""


class TestLLMProviderBase:
    """Tests for the base LLMProvider class."""

    def test_abstract_method_raises(self):
        """review_diff should raise NotImplementedError on the base class."""
        provider = LLMProvider()
        with pytest.raises(NotImplementedError):
            provider.review_diff(diff="test")

    def test_build_prompt_without_context(self):
        """PromptBuilder should create a minimal prompt without context."""
        from sentinel_review.workers.prompt_builder import PromptBuilder

        messages = PromptBuilder().build(diff="diff --git a/a.py b/a.py")
        assert len(messages) >= 2  # system + at least one user message
        assert messages[0]["role"] == "system"

    def test_build_prompt_with_repo_context(self):
        """PromptBuilder should include repo context when provided."""
        from sentinel_review.workers.prompt_builder import PromptBuilder

        messages = PromptBuilder().build(
            diff="diff --git a/a.py b/a.py",
            repo_context="Default branch: main\nCONTRIBUTING.md:\nPlease write tests.",
        )
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_build_prompt_with_file_contents(self):
        """PromptBuilder should include full file contents when provided."""
        from sentinel_review.workers.prompt_builder import PromptBuilder

        messages = PromptBuilder().build(
            diff="diff --git a/a.py b/a.py",
            file_contents={"app.py": "def foo():\n    pass"},
        )
        # Should have the file contents blob as a user message
        contents_found = any(
            "Full file contents for context" in m.get("content", "")
            for m in messages
            if m["role"] == "user"
        )
        assert contents_found

    def test_validate_and_parse_valid_json(self):
        """_validate_and_parse should accept valid ReviewOutput JSON."""
        raw = json.dumps(
            {
                "findings": [
                    {
                        "file_path": "app.py",
                        "line_number": 2,
                        "category": "security",
                        "severity": "blocking",
                        "comment": "SQL injection.",
                        "suggested_fix": None,
                    }
                ]
            }
        )
        findings, success, error = LLMProvider._validate_and_parse(raw)
        assert success is True
        assert error == ""
        assert len(findings) == 1
        assert findings[0].file_path == "app.py"

    def test_validate_and_parse_empty_findings(self):
        """An empty findings list should be valid."""
        raw = '{"findings": []}'
        findings, success, error = LLMProvider._validate_and_parse(raw)
        assert success is True
        assert len(findings) == 0

    def test_validate_and_parse_malformed_json(self):
        """Malformed JSON should fail validation."""
        raw = "This is not json"
        findings, success, error = LLMProvider._validate_and_parse(raw)
        assert success is False
        assert len(findings) == 0
        assert "Failed to parse JSON" in error

    def test_validate_and_parse_invalid_schema(self):
        """JSON that doesn't match ReviewOutput should fail."""
        raw = json.dumps({"wrong_key": "value"})
        findings, success, error = LLMProvider._validate_and_parse(raw)
        assert success is False
        assert "Pydantic validation failed" in error

    def test_validate_and_parse_codeblock(self):
        """JSON wrapped in markdown code blocks should be extractable."""
        raw = f"```json\n{json.dumps({'findings': []})}\n```"
        findings, success, error = LLMProvider._validate_and_parse(raw)
        assert success is True
        assert len(findings) == 0

    def test_validate_and_parse_partial_data(self):
        """Partially valid data (missing required fields) should fail."""
        raw = json.dumps({"findings": [{"file_path": "app.py"}]})
        findings, success, error = LLMProvider._validate_and_parse(raw)
        assert success is False


class TestAnthropicProvider:
    """Tests for the Anthropic provider."""

    def test_init_without_api_key(self):
        """Provider should initialize even without an API key."""
        provider = AnthropicProvider()
        assert provider.provider_name == "anthropic"
        assert provider.api_key is not None  # Set from env

    def test_review_diff_without_key(self, monkeypatch):
        """Without an API key, review_diff should return an error result."""
        monkeypatch.setattr("django.conf.settings.ANTHROPIC_API_KEY", "")
        provider = AnthropicProvider()
        # Re-init to pick up the patched setting
        provider.api_key = ""
        result = provider.review_diff(diff="test diff")
        assert result.validation_success is False
        assert "API key not configured" in result.error_message


class TestOpenAIProvider:
    """Tests for the OpenAI provider."""

    def test_init_without_api_key(self):
        """Provider should initialize even without an API key."""
        provider = OpenAIProvider()
        assert provider.provider_name == "openai"

    def test_review_diff_without_key(self, monkeypatch):
        """Without an API key, review_diff should return an error result."""
        monkeypatch.setattr("django.conf.settings.OPENAI_API_KEY", "")
        provider = OpenAIProvider()
        provider.api_key = ""
        result = provider.review_diff(diff="test diff")
        assert result.validation_success is False
        assert "API key not configured" in result.error_message


class TestGetLLMProvider:
    """Tests for the get_llm_provider factory."""

    def test_default_is_anthropic(self):
        """Default provider should be Anthropic."""
        provider = get_llm_provider()
        assert isinstance(provider, AnthropicProvider)

    def test_openai_provider(self, monkeypatch):
        """Setting LLM_PROVIDER to 'openai' should return OpenAIProvider."""
        monkeypatch.setattr("django.conf.settings.LLM_PROVIDER", "openai")
        provider = get_llm_provider()
        assert isinstance(provider, OpenAIProvider)

    def test_unknown_provider_defaults_to_anthropic(self, monkeypatch):
        """An unknown provider name should default to Anthropic."""
        monkeypatch.setattr("django.conf.settings.LLM_PROVIDER", "unknown")
        provider = get_llm_provider()
        assert isinstance(provider, AnthropicProvider)
