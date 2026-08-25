"""
Logging filters for redacting sensitive patterns from log output.

Prevents secrets (API keys, tokens, passwords) from appearing in
structured logs. Applied as a Django logging filter so it runs
on every log record before the handler writes it.
"""

from __future__ import annotations

import json
import logging
import re

# Patterns to redact — ordered by specificity (most specific first).
# NOTE: We intentionally do NOT include a generic `[a-fA-F0-9]{40,}` pattern
# because it falsely matches git commit SHAs and other legitimate hex strings.
# Secret detection relies on known formats (prefixes, structure).
REDACT_PATTERNS: list[re.Pattern[str]] = [
    # Anthropic API keys (sk-ant-...)
    re.compile(r"sk-ant-[a-zA-Z0-9]{20,}(?:\.[a-zA-Z0-9_-]+)?"),
    # OpenAI API keys (sk-proj-... or sk-...)
    re.compile(r"sk-[a-zA-Z0-9]{20,}(?:\.[a-zA-Z0-9_-]+)*"),
    # GitHub App private key base64 (long base64 blobs)
    re.compile(
        r"-----BEGIN\s?(RSA\s)?PRIVATE\s?KEY-----[-\sA-Za-z0-9+/=]*?-----END\s?(RSA\s)?PRIVATE\s?KEY-----"
    ),
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
    # Database connection strings with credentials
    re.compile(r"(?i)(postgres|mysql|redis|mongodb)://[^@\s]+:[^@\s]+@"),
]

REDACTED_PLACEHOLDER = "***REDACTED***"


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive patterns from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive patterns in the log message and args."""
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                # Mapping-style args (e.g. Celery trace logs) — redact values in place.
                record.args = {
                    key: self._redact(str(value)) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                redacted_args = tuple(
                    self._redact(str(arg)) if isinstance(arg, str) else arg for arg in record.args
                )
                record.args = redacted_args

        if record.exc_text:
            record.exc_text = self._redact(record.exc_text)

        for key in dir(record):
            if key.startswith("_") or key in ("args", "msg", "exc_text", "exc_info"):
                continue
            try:
                val = getattr(record, key)
                if isinstance(val, str):
                    setattr(record, key, self._redact(val))
            except (AttributeError, TypeError):
                pass

        return True

    @staticmethod
    def _redact(text: str) -> str:
        """Apply all redaction patterns to the given text."""
        for pattern in REDACT_PATTERNS:
            text = pattern.sub(REDACTED_PLACEHOLDER, text)
        return text


class MappingArgsFilter(logging.Filter):
    """Normalize records whose args wrap a mapping inside a tuple.

    Celery's ``celery.app.trace`` helper logs mapping-style format strings
    (e.g. ``"Task %(name)s[%(id)s] succeeded in %(runtime)ss: ..."``) by
    passing the context dict positionally: ``logger.info(fmt, context,
    extra=...)``. Python's logging then stores ``record.args = (context,)``
    and ``LogRecord.getMessage()`` executes ``msg % (context,)``, which
    raises ``TypeError: format requires a mapping`` for ``%(name)s``-style
    placeholders. This filter rewrites such records so any handler or
    formatter (Django console, pytest capture, JSON) can render them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            isinstance(record.msg, str)
            and "%(" in record.msg
            and isinstance(record.args, tuple)
            and len(record.args) == 1
            and isinstance(record.args[0], dict)
        ):
            record.args = record.args[0]
        return True


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter.

    Outputs log records as JSON objects with consistent fields
    suitable for log aggregation systems (ELK, Datadog, etc.).
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
            "process": record.process,
            "thread": record.thread,
        }

        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include any extra fields attached to the record
        for key in ("task_id", "repo", "pr_number", "request_id", "delivery_id"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        return json.dumps(log_entry, default=str)
