"""
Logging filters for redacting sensitive patterns from log output.

Prevents secrets (API keys, tokens, passwords) from appearing in
structured logs. Applied as a Django logging filter so it runs
on every log record before the handler writes it.
"""

from __future__ import annotations

import logging
import re

# Patterns to redact — ordered by specificity (most specific first)
# to minimize false positives while catching known formats.
REDACT_PATTERNS: list[re.Pattern[str]] = [
    # Anthropic API keys (sk-ant-...)
    re.compile(r"sk-ant-[a-zA-Z0-9]{20,}(?:\.[a-zA-Z0-9_-]+)?"),
    # OpenAI API keys (sk-proj-... or sk-...)
    re.compile(r"sk-[a-zA-Z0-9]{20,}(?:\.[a-zA-Z0-9_-]+)*"),
    # GitHub App private key base64 (long base64 blobs)
    re.compile(r"-----BEGIN\s?(RSA\s)?PRIVATE\s?KEY-----[\s\S]*?-----END\s?(RSA\s)?PRIVATE\s?KEY-----"),
    # GitHub Personal Access Tokens (ghp_, gho_, ghu_, ghs_, ghb_, ghv_)
    re.compile(r"gh[pousvb]_[a-zA-Z0-9_]{36,}"),
    # GitHub OAuth / App tokens (ghr_, gist_)
    re.compile(r"(?:ghr|gist)_[a-zA-Z0-9_]{36,}"),
    # Generic bearer tokens in headers
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}(?:\.[a-zA-Z0-9_\-\.]+)*"),
    # Generic password/secret assignments
    re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    # JWT-like tokens (three base64url segments)
    re.compile(r"eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}"),
    # Generic hex strings that look like secrets (40+ hex chars)
    re.compile(r"[a-fA-F0-9]{40,}"),
    # Database connection strings with credentials
    re.compile(r"(?i)(postgres|mysql|redis|mongodb)://[^@\s]+:[^@\s]+@"),
]

REDACTED_PLACEHOLDER = "***REDACTED***"


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive patterns from log messages.

    Usage in Django LOGGING config::

        LOGGING['filters'] = {
            'redact': {'()': 'sentinel_review.logging_filters.RedactingFilter'},
        }
        LOGGING['handlers']['console']['filters'] = ['redact']
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive patterns in the log message and args."""
        # Redact the message itself
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        # Redact string args
        if record.args:
            redacted_args = tuple(
                self._redact(str(arg)) if isinstance(arg, str) else arg
                for arg in record.args
            )
            record.args = redacted_args

        # Redact exc_info text if present
        if record.exc_text:
            record.exc_text = self._redact(record.exc_text)

        # Redact any extra dict fields that look like secrets
        for key in dir(record):
            if key.startswith("_") or key in ("args", "msg", "exc_text", "exc_info"):
                continue
            try:
                val = getattr(record, key)
                if isinstance(val, str):
                    setattr(record, key, self._redact(val))
            except Exception:
                pass

        return True  # Never filter out the record, just redact its content

    @staticmethod
    def _redact(text: str) -> str:
        """Apply all redaction patterns to the given text."""
        for pattern in REDACT_PATTERNS:
            text = pattern.sub(REDACTED_PLACEHOLDER, text)
        return text
