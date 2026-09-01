"""
Prompt builder for LLM code review.

Assembles the full prompt from diff, repo context, file contents,
few-shot examples, and optional corrective hints. Decoupled from
the provider-calling logic for independent testability.
"""

import logging
from typing import Any

from sentinel_review.workers.schemas import SYSTEM_PROMPT, get_few_shot_examples

logger = logging.getLogger(__name__)

TRUNCATION_WARNING = "# NOTE: diff truncated from %d to %d characters"


class PromptBuilder:
    """Builds prompts for LLM code review.

    Handles prompt assembly, truncation limits, corrective retry hints,
    context injection, and few-shot example inclusion.
    """

    def __init__(
        self,
        max_diff_chars: int = 30000,
        max_context_chars: int = 4000,
        max_file_content_chars: int = 10000,
    ) -> None:
        self.max_diff_chars = max_diff_chars
        self.max_context_chars = max_context_chars
        self.max_file_content_chars = max_file_content_chars

    def build(
        self,
        diff: str,
        repo_context: str | None = None,
        file_contents: dict[str, str] | None = None,
        corrective_hint: str | None = None,
        custom_instructions: str | None = None,
    ) -> list[dict[str, Any]] -> None:
        """Build the full prompt with system prompt, few-shot examples, and diff.

        Args:
            diff: The PR diff text
            repo_context: Optional repository context string
            file_contents: Optional mapping of file paths to full file contents
            corrective_hint: Optional validation error from a previous attempt
            custom_instructions: Optional repo-specific custom instructions

        Returns:
            List of message dicts suitable for Anthropic/OpenAI API.
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add corrective hint if this is a retry
        if corrective_hint:
            messages.append(self._build_corrective_hint(corrective_hint))

        # Add custom instructions if provided
        if custom_instructions:
            messages.append(
                {
                    "role": "user",
                    "content": f"Custom review instructions for this repository:\n{custom_instructions}",
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": "Understood. I'll follow these custom review guidelines.",
                }
            )

        # Add repo context if available
        if repo_context:
            truncated_context = repo_context[: self.max_context_chars]
            messages.append(
                {
                    "role": "user",
                    "content": f"Repository context:\n{truncated_context}",
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": "Understood. I'll consider this context during the review.",
                }
            )

        # Add file contents if available
        if file_contents:
            file_blob = "\n\n".join(
                f"### {path}\n```\n{content[:5000]}\n```" for path, content in file_contents.items()
            )
            messages.append(
                {
                    "role": "user",
                    "content": f"Full file contents for context:\n{file_blob[: self.max_file_content_chars]}",
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": "Thanks, I have the full context of the changed files.",
                }
            )

        # Add few-shot examples
        for example in get_few_shot_examples():
            messages.append(example)

        # Build the main diff message with truncation tracking
        diff_message, truncated = self._build_diff_message(diff)
        messages.append(diff_message)

        if truncated:
            logger.info(
                "Diff truncated from %d to %d characters",
                len(diff),
                self.max_diff_chars,
            )

        return messages

    def _build_corrective_hint(self, corrective_hint: str) -> dict[str, Any]:
        """Build a corrective hint message for retry."""
        return {
            "role": "user",
            "content": (
                "Note: Your previous response failed validation with this error:\n"
                f"{corrective_hint}\n\n"
                "Please return ONLY valid JSON matching the required schema. "
                "Double-check your JSON syntax before responding."
            ),
        }

    def _build_diff_message(self, diff: str) -> tuple[dict[str, Any], bool]:
        """Build the main diff review message with truncation handling.

        Returns:
            Tuple of (message dict, was_truncated)
        """
        original_len = len(diff)
        if original_len > self.max_diff_chars:
            truncated_diff = diff[: self.max_diff_chars]
            warning = TRUNCATION_WARNING % (original_len, self.max_diff_chars)
            content = (
                f"Review this pull request diff:\n\n```diff\n{truncated_diff}\n```\n\n"
                f"{warning}\n\n"
                "Return your findings as a JSON object with a 'findings' array."
            )
            return (
                {"role": "user", "content": content},
                True,
            )

        content = (
            f"Review this pull request diff:\n\n```diff\n{diff}\n```\n\n"
            "Return your findings as a JSON object with a 'findings' array."
        )
        return (
            {"role": "user", "content": content},
            False,
        )
