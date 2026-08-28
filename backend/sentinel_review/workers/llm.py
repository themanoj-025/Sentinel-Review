"""
LLM provider abstraction.

Supports Anthropic Claude and OpenAI-compatible APIs behind a common interface.
Handles structured output with Pydantic validation, retries, and cost tracking.
"""

import json
import logging
import time
from dataclasses import dataclass, field

from django.conf import settings
from pydantic import ValidationError

from sentinel_review.api.metrics import llm_errors, token_cost

from .circuit_breaker import CircuitBreakerOpenError, llm_circuit_breaker
from .prompt_builder import PromptBuilder
from .schemas import Finding, ReviewOutput

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    """Result from an LLM review call."""

    findings: list[Finding] = field(default_factory=list)
    raw_output: str = ""
    total_tokens: int = 0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    validation_success: bool = True
    error_message: str = ""


class LLMProvider:
    """Abstract base for LLM providers."""

    def __init__(self) -> Any:
        self.provider_name = "unknown"

    def review_diff(
        self,
        diff: str,
        repo_context: str | None = None,
        file_contents: dict[str, str] | None = None,
        custom_instructions: str | None = None,
    ) -> LLMResult:
        """Review a diff and return structured findings."""
        raise NotImplementedError

    def _review_with_retry(
        self,
        diff: str,
        repo_context: str | None = None,
        file_contents: dict[str, str] | None = None,
        custom_instructions: str | None = None,
    ) -> LLMResult:
        """Call review_diff with automatic retry on validation failures.

        On a malformed JSON or Pydantic validation error, retries once with
        a corrective follow-up message showing the validation error.
        """
        # First attempt
        result = self._call_api(
            diff,
            repo_context,
            file_contents,
            corrective_hint=None,
            custom_instructions=custom_instructions,
        )
        if result.validation_success:
            return result

        # Retry with corrective hint
        logger.warning(
            "LLM validation failed (attempt 1/2): %s. Retrying with corrective hint.",
            result.error_message,
        )
        result = self._call_api(
            diff,
            repo_context,
            file_contents,
            corrective_hint=result.error_message,
            custom_instructions=custom_instructions,
        )
        if result.validation_success:
            logger.info("LLM retry succeeded after corrective hint.")
            return result

        logger.error("LLM validation failed after retry: %s", result.error_message)
        return result

    def _call_api(
        self, diff, repo_context, file_contents, corrective_hint=None, custom_instructions=None
    ) -> LLMResult:
        """Subclasses implement this - sends the actual API request."""
        raise NotImplementedError

    @staticmethod
    def _validate_and_parse(raw_output: str) -> tuple[list[Finding], bool, str]:
        """Validate and parse the LLM's JSON output against the ReviewOutput schema.

        Returns: (findings, success, error_message)
        """
        json_str = raw_output.strip()

        # Handle code-block wrapped JSON
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return [], False, f"Failed to parse JSON from LLM output: {e}"

        try:
            review_output = ReviewOutput(**data)
        except ValidationError as e:
            return [], False, f"Pydantic validation failed: {e}"
        except TypeError as e:
            return [], False, f"Type error in LLM output: {e}"

        return review_output.findings, True, ""


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider using structured output (tool use)."""

    def __init__(self) -> Any:
        super().__init__()
        self.provider_name = "anthropic"
        self.api_key = settings.ANTHROPIC_API_KEY
        self.model = settings.ANTHROPIC_MODEL

    def review_diff(
        self, diff, repo_context=None, file_contents=None, custom_instructions=None
    ) -> LLMResult:
        """Review a diff with automatic retry on validation failures."""
        return self._review_with_retry(
            diff, repo_context, file_contents, custom_instructions=custom_instructions
        )

    def _call_api(
        self, diff, repo_context, file_contents, corrective_hint=None, custom_instructions=None
    ) -> LLMResult:
        if not self.api_key:
            return LLMResult(
                error_message="Anthropic API key not configured", validation_success=False
            )

        prompt_builder = PromptBuilder()
        messages = prompt_builder.build(
            diff, repo_context, file_contents, corrective_hint, custom_instructions
        )
        system_content = messages[0]["content"]
        user_assistant_messages = messages[1:]

        start_time = time.time()

        try:
            # Use circuit breaker to protect against LLM provider outages
            response = llm_circuit_breaker.call(
                lambda: self._do_anthropic_call(system_content, user_assistant_messages, start_time)
            )
            return response

        except CircuitBreakerOpenError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error("Circuit breaker open for Anthropic: %s", e)
            llm_errors.labels(provider=self.provider_name).inc()
            return LLMResult(error_message=str(e), latency_ms=latency_ms, validation_success=False)
        except (ConnectionError, TimeoutError) as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error("Anthropic API connection error: %s", e)
            llm_errors.labels(provider=self.provider_name).inc()
            return LLMResult(error_message=str(e), latency_ms=latency_ms, validation_success=False)
        except (RuntimeError, ValueError) as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error("Anthropic API error: %s", e)
            llm_errors.labels(provider=self.provider_name).inc()
            return LLMResult(error_message=str(e), latency_ms=latency_ms, validation_success=False)

    def _do_anthropic_call(self, system_content, user_assistant_messages, start_time) -> LLMResult:
        """Actual Anthropic API call — separated for circuit breaker wrapping."""
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_content,
            messages=user_assistant_messages,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        raw_text = response.content[0].text
        total_tokens = response.usage.input_tokens + response.usage.output_tokens

        token_cost.labels(provider=self.provider_name, model=self.model).inc(total_tokens)

        findings, success, error_msg = self._validate_and_parse(raw_text)

        return LLMResult(
            findings=findings,
            raw_output=raw_text,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=self.model,
            validation_success=success,
            error_message=error_msg,
        )


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider with structured output."""

    def __init__(self) -> Any:
        super().__init__()
        self.provider_name = "openai"
        self.api_key = settings.OPENAI_API_KEY
        self.model = settings.OPENAI_MODEL

    def review_diff(
        self, diff, repo_context=None, file_contents=None, custom_instructions=None
    ) -> LLMResult:
        """Review a diff with automatic retry on validation failures."""
        return self._review_with_retry(
            diff, repo_context, file_contents, custom_instructions=custom_instructions
        )

    def _call_api(
        self, diff, repo_context, file_contents, corrective_hint=None, custom_instructions=None
    ) -> LLMResult:
        if not self.api_key:
            return LLMResult(
                error_message="OpenAI API key not configured", validation_success=False
            )

        prompt_builder = PromptBuilder()
        build_messages = prompt_builder.build(
            diff, repo_context, file_contents, corrective_hint, custom_instructions
        )
        openai_messages = [{"role": "system", "content": build_messages[0]["content"]}]
        for msg in build_messages[1:]:
            openai_messages.append({"role": msg["role"], "content": msg["content"]})

        start_time = time.time()

        try:
            # Use circuit breaker to protect against LLM provider outages
            response = llm_circuit_breaker.call(
                lambda: self._do_openai_call(openai_messages, start_time)
            )
            return response

        except CircuitBreakerOpenError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error("Circuit breaker open for OpenAI: %s", e)
            llm_errors.labels(provider=self.provider_name).inc()
            return LLMResult(error_message=str(e), latency_ms=latency_ms, validation_success=False)
        except (ConnectionError, TimeoutError) as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error("OpenAI API connection error: %s", e)
            llm_errors.labels(provider=self.provider_name).inc()
            return LLMResult(error_message=str(e), latency_ms=latency_ms, validation_success=False)
        except (RuntimeError, ValueError) as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error("OpenAI API error: %s", e)
            llm_errors.labels(provider=self.provider_name).inc()
            return LLMResult(error_message=str(e), latency_ms=latency_ms, validation_success=False)

    def _do_openai_call(self, openai_messages, start_time) -> LLMResult:
        """Actual OpenAI API call — separated for circuit breaker wrapping."""
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            max_tokens=4096,
            temperature=0.1,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        raw_text = response.choices[0].message.content or ""
        usage = response.usage
        total_tokens = (usage.input_tokens + usage.output_tokens) if usage else 0

        token_cost.labels(provider=self.provider_name, model=self.model).inc(total_tokens)

        findings, success, error_msg = self._validate_and_parse(raw_text)

        return LLMResult(
            findings=findings,
            raw_output=raw_text,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=self.model,
            validation_success=success,
            error_message=error_msg,
        )


def get_llm_provider() -> LLMProvider:
    """Factory function to get the configured LLM provider."""
    provider_type = settings.LLM_PROVIDER.lower()
    if provider_type == "openai":
        return OpenAIProvider()
    return AnthropicProvider()
