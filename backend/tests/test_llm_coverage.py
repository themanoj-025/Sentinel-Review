"""Targeted tests for workers/llm.py to boost coverage above 75%.

Focuses on:
- _review_with_retry corrective retry logic
- _build_prompt with corrective_hint
- _validate_and_parse with TypeError and edge cases
- _call_api circuit breaker and error handling
- get_llm_provider factory edge cases
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from sentinel_review.workers.circuit_breaker import CircuitState, llm_circuit_breaker
from sentinel_review.workers.llm import (
    AnthropicProvider,
    LLMProvider,
    LLMResult,
    OpenAIProvider,
    get_llm_provider,
)


class TestLLMProviderCorrectiveRetry:
    """_review_with_retry — corrective retry on validation failure."""

    def test_first_attempt_succeeds(self) -> None:
        """When _call_api returns success on first try, return immediately."""
        provider = LLMProvider()

        def mock_call(
            diff, repo_context, file_contents, corrective_hint=None, custom_instructions=None
        ):
            return LLMResult(findings=[], validation_success=True)

        with patch.object(provider, "_call_api", mock_call):
            result = provider._review_with_retry(diff="test")
        assert result.validation_success is True

    def test_first_fails_retry_succeeds(self) -> None:
        """When first attempt fails, retry with corrective hint should succeed."""
        provider = LLMProvider()
        call_count = [0]

        def mock_call(
            diff, repo_context, file_contents, corrective_hint=None, custom_instructions=None
        ):
            call_count[0] += 1
            if call_count[0] == 1:
                return LLMResult(validation_success=False, error_message="Invalid JSON")
            return LLMResult(findings=[], validation_success=True)

        with patch.object(provider, "_call_api", mock_call):
            result = provider._review_with_retry(diff="test")
        assert result.validation_success is True
        assert call_count[0] == 2

    def test_both_attempts_fail(self) -> None:
        """When both attempts fail, return the failed result."""
        provider = LLMProvider()

        def mock_call(
            diff, repo_context, file_contents, corrective_hint=None, custom_instructions=None
        ):
            return LLMResult(validation_success=False, error_message="Still failing")

        with patch.object(provider, "_call_api", mock_call):
            result = provider._review_with_retry(diff="test")
        assert result.validation_success is False
        assert "Still failing" in result.error_message


class TestLLMProviderBuildPrompt:
    """_build_prompt — message construction."""

    def test_with_corrective_hint(self) -> None:
        """Corrective hint should be included in the prompt messages."""
        from sentinel_review.workers.prompt_builder import PromptBuilder

        messages = PromptBuilder().build(
            diff="test diff", corrective_hint="Missing field: line_number"
        )
        hint_found = any(
            "Your previous response failed validation" in m.get("content", "") for m in messages
        )
        assert hint_found

    def test_with_repo_context_and_files(self) -> None:
        """Both repo context and file contents should be included."""
        from sentinel_review.workers.prompt_builder import PromptBuilder

        messages = PromptBuilder().build(
            diff="diff --git a/a.py b/a.py",
            repo_context="Default branch: main",
            file_contents={"a.py": "print('hello')"},
        )
        context_found = any("Repository context" in m.get("content", "") for m in messages)
        files_found = any("Full file contents" in m.get("content", "") for m in messages)
        assert context_found
        assert files_found

    def test_with_all_three_options(self) -> None:
        """All optional params (hint, context, files) should combine correctly."""
        from sentinel_review.workers.prompt_builder import PromptBuilder

        messages = PromptBuilder().build(
            diff="test",
            repo_context="context",
            file_contents={"f.py": "code"},
            corrective_hint="error",
        )
        assert len(messages) >= 7  # system + hint + ack + context + ack + files + ack + diff


class TestLLMProviderValidateAndParse:
    """_validate_and_parse — edge cases."""

    def test_type_error_handled(self) -> None:
        """TypeError (e.g., from Pydantic v1) should be caught gracefully."""
        raw = json.dumps({"findings": "not_a_list"})
        _findings, success, error = LLMProvider._validate_and_parse(raw)
        assert success is False
        assert error != ""

    def test_codeblock_without_json_lang(self) -> None:
        """Code block without 'json' language tag should still parse."""
        raw = "```\n" + json.dumps({"findings": []}) + "\n```"
        _findings, success, _error = LLMProvider._validate_and_parse(raw)
        assert success is True

    def test_codeblock_with_junk_around(self) -> None:
        """Junk text around a code block should be handled."""
        raw = (
            "Let me review this diff...\n\n"
            + "```json\n"
            + json.dumps({"findings": []})
            + "\n```\n\nDone!"
        )
        findings, success, _error = LLMProvider._validate_and_parse(raw)
        assert success is True
        assert len(findings) == 0

    def test_extra_fields_in_output(self) -> None:
        """Extra fields beyond the schema should be ignored (not fail)."""
        raw = json.dumps({"findings": [], "extra_info": "this should be ignored"})
        _findings, success, _error = LLMProvider._validate_and_parse(raw)
        assert success is True

    def test_empty_string(self) -> None:
        """Empty string should fail gracefully."""
        _findings, success, error = LLMProvider._validate_and_parse("")
        assert success is False
        assert "Failed to parse JSON" in error

    def test_whitespace_only(self) -> None:
        """Whitespace-only input should fail gracefully."""
        _findings, success, error = LLMProvider._validate_and_parse("   \n\n  ")
        assert success is False
        assert "Failed to parse JSON" in error

    def test_none_instead_of_list(self) -> None:
        """None instead of findings list should fail."""
        raw = json.dumps({"findings": None})
        _findings, success, _error = LLMProvider._validate_and_parse(raw)
        assert success is False


class TestAnthropicProviderEdgeCases:
    """AnthropicProvider — circuit breaker and error handling."""

    @pytest.mark.django_db
    def test_circuit_breaker_protection(self, monkeypatch) -> None:
        """When circuit breaker is open, return error without calling API."""
        monkeypatch.setattr("django.conf.settings.ANTHROPIC_API_KEY", "sk-ant-test-key")

        llm_circuit_breaker.state = CircuitState.OPEN
        llm_circuit_breaker.last_failure_time = time.time()

        provider = AnthropicProvider()
        provider.api_key = "sk-ant-test-key"

        result = provider._call_api(diff="test diff", repo_context=None, file_contents=None)
        assert result.validation_success is False
        assert "is OPEN" in result.error_message

        llm_circuit_breaker.state = CircuitState.CLOSED
        llm_circuit_breaker.failure_count = 0

    @pytest.mark.django_db
    def test_missing_key_returns_error(self) -> None:
        """When API key is empty, return early error."""
        provider = AnthropicProvider()
        provider.api_key = ""
        result = provider._call_api(diff="test", repo_context=None, file_contents=None)
        assert result.validation_success is False
        assert "API key not configured" in result.error_message


class TestOpenAIProviderEdgeCases:
    """OpenAIProvider — circuit breaker and error handling."""

    @pytest.mark.django_db
    def test_circuit_breaker_protection(self, monkeypatch) -> None:
        """When circuit breaker is open, return error without calling API."""
        monkeypatch.setattr("django.conf.settings.OPENAI_API_KEY", "sk-test-key")

        llm_circuit_breaker.state = CircuitState.OPEN
        llm_circuit_breaker.last_failure_time = time.time()

        provider = OpenAIProvider()
        provider.api_key = "sk-test-key"

        result = provider._call_api(diff="test diff", repo_context=None, file_contents=None)
        assert result.validation_success is False
        assert "is OPEN" in result.error_message

        llm_circuit_breaker.state = CircuitState.CLOSED
        llm_circuit_breaker.failure_count = 0

    @pytest.mark.django_db
    def test_missing_key_returns_error(self) -> None:
        """When API key is empty, return early error."""
        provider = OpenAIProvider()
        provider.api_key = ""
        result = provider._call_api(diff="test", repo_context=None, file_contents=None)
        assert result.validation_success is False
        assert "API key not configured" in result.error_message


class TestGetLLMProvider:
    """get_llm_provider factory function."""

    @pytest.mark.django_db
    def test_default(self) -> None:
        """Default provider should be Anthropic."""
        provider = get_llm_provider()
        assert isinstance(provider, AnthropicProvider)

    @pytest.mark.django_db
    def test_openai(self, monkeypatch) -> None:
        """Setting provider to 'openai' should return OpenAIProvider."""
        monkeypatch.setattr("django.conf.settings.LLM_PROVIDER", "openai")
        provider = get_llm_provider()
        assert isinstance(provider, OpenAIProvider)

    @pytest.mark.django_db
    def test_unknown_defaults_to_anthropic(self, monkeypatch) -> None:
        """Unknown provider should default to Anthropic."""
        monkeypatch.setattr("django.conf.settings.LLM_PROVIDER", "unknown")
        provider = get_llm_provider()
        assert isinstance(provider, AnthropicProvider)

    @pytest.mark.django_db
    def test_empty_provider_defaults_to_anthropic(self, monkeypatch) -> None:
        """Empty provider should default to Anthropic."""
        monkeypatch.setattr("django.conf.settings.LLM_PROVIDER", "")
        provider = get_llm_provider()
        assert isinstance(provider, AnthropicProvider)
