"""
Pydantic schemas for structured review output from the LLM.

These enforce that malformed LLM output never reaches the GitHub API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """A single review finding/comment."""

    file_path: str = Field(description="Path to the file containing the issue")
    line_number: int | None = Field(
        default=None,
        description="Line number of the issue (null if file-level)",
    )
    category: Literal["bug", "style", "security", "suggestion"] = Field(
        description="Category of the finding"
    )
    severity: Literal["blocking", "warning", "nit"] = Field(
        description="Severity level of the finding"
    )
    comment: str = Field(
        description=(
            "Concise explanation of the issue. Never restate the diff. "
            "Explain why it matters in one sentence."
        )
    )
    suggested_fix: str | None = Field(
        default=None,
        description="A concrete suggested fix for the issue, if applicable",
    )


class ReviewOutput(BaseModel):
    """Complete structured output from the LLM review."""

    findings: list[Finding] = Field(
        description="List of findings identified in the review. "
        "Omit a finding entirely rather than guessing when context is insufficient."
    )


SYSTEM_PROMPT = """You are a senior engineer conducting a thorough but concise code review.

## Your role
Act like an experienced, slightly-burnt-out senior engineer doing a PR review.
Be direct, specific, and helpful. Never be vague or overly positive.

## Rules
1. NEVER restate the diff. I can already see what changed.
2. ALWAYS explain *why* something matters in one terse sentence.
3. Prefer a concrete suggested_fix over a vague complaint.
4. For each issue, provide: file_path, line_number (or null), category, severity, comment, and suggested_fix.
5. OMIT a finding entirely rather than guessing when you don't have enough context.
   False positives are worse than false negatives.
6. Focus on substantive issues: logic bugs, security vulnerabilities, performance problems,
   API misuse, concurrency issues, and correctness. Avoid nitpicking style unless asked.

## Categories
- bug: Incorrect logic, runtime errors, edge cases not handled, off-by-one, null/None errors
- style: Code organization, naming, readability, consistency (only flag if it harms maintainability)
- security: Injection vulnerabilities, hardcoded secrets, auth issues, unsafe deserialization, XSS, CSRF
- suggestion: Improvements to design, performance, maintainability, test coverage

## Severity
- blocking: Will cause incorrect behavior or a production incident if merged
- warning: Likely to cause problems or is clearly suboptimal — should be fixed
- nit: Minor issue, nice to fix but not critical

## Output format
Return a JSON object with a single "findings" key containing an array of finding objects.
Each finding object has: file_path (string), line_number (int|null), category, severity, comment, suggested_fix (string|null).

Example good finding:
{
  "file_path": "src/auth/login.py",
  "line_number": 42,
  "category": "security",
  "severity": "blocking",
  "comment": "SQL query uses f-string interpolation with user input — vulnerable to injection. Parameterize the query instead.",
  "suggested_fix": "Use `cursor.execute('SELECT * FROM users WHERE email = %s', (email,))` instead of f-strings."
}

Example of what NOT to do (too vague, no impact explained):
{
  "file_path": "src/utils.py",
  "line_number": 10,
  "category": "suggestion",
  "severity": "nit",
  "comment": "This function could be better.",
  "suggested_fix": null
}
"""


def get_few_shot_examples() -> list[dict]:
    """
    Return few-shot examples for the LLM prompt.
    Sourced from the evaluation set to demonstrate desired behavior.
    """
    return [
        {
            "role": "user",
            "content": "Review this diff:\n```diff\n--- a/app.py\n+++ b/app.py\n@@ -5,7 +5,8 @@\n def get_user(email):\n-    query = f\"SELECT * FROM users WHERE email = '{email}'\"\n+    query = f\"SELECT * FROM users WHERE email = '{email}'\"\n     cursor.execute(query)\n     return cursor.fetchone()\n```",
        },
        {
            "role": "assistant",
            "content": """{
  "findings": [
    {
      "file_path": "app.py",
      "line_number": 6,
      "category": "security",
      "severity": "blocking",
      "comment": "SQL query uses f-string interpolation with user-controlled 'email' — susceptible to SQL injection. The refactored line doesn't fix this; it's still interpolated.",
      "suggested_fix": "Use parameterized queries: `cursor.execute('SELECT * FROM users WHERE email = %s', (email,))`"
    }
  ]
}""",
        },
        {
            "role": "user",
            "content": "Review this diff:\n```diff\n--- a/utils.py\n+++ b/utils.py\n@@ -1,4 +1,4 @@\n-def format_name(first, last):\n-    return first + ' ' + last\n+def format_name(first_name, last_name):\n+    return first_name + ' ' + last_name\n```",
        },
        {
            "role": "assistant",
            "content": """{
  "findings": []
}""",
            "explanation": "Parameter rename only — no substantive issue. A nit about the name change would be noise.",
        },
    ]
