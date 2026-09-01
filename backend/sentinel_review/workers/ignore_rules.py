"""
.sentinel-ignore file support.

Parses `.sentinel-ignore` files from the repository root (or any ancestor
directory) and filters out review findings for files matching the specified
glob patterns. This lets teams exclude generated files, vendored code,
test fixtures, or any other files they don't want the bot to comment on.

Format:
    # Lines starting with # are comments
    *.generated.py     # Ignore all generated Python files
    node_modules/      # Ignore entire node_modules directory
    *.test.js          # Ignore test files
    docs/*.md          # Ignore markdown files in docs/

Pattern matching uses Python's `fnmatch` for glob-style patterns.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

# Constants

_IGNORE_FILENAME = ".sentinel-ignore"


# Pattern Parsing


def parse_ignore_file(content: str) -> list[str]:
    """Parse a .sentinel-ignore file into a list of glob patterns.

    Strips comments (lines starting with #), blank lines, and inline
    comments after patterns. Returns an empty list if no patterns found.
    """
    patterns: list[str] = []
    for line in content.splitlines():
        line = line.strip()

        # Skip blank lines and full-line comments
        if not line or line.startswith("#"):
            continue

        # Strip inline comments (everything after the first unquoted #)
        # Simple heuristic: split on # that follows a non-backslash space
        comment_idx = _find_inline_comment(line)
        pattern = line[:comment_idx].strip() if comment_idx >= 0 else line

        if pattern:
            patterns.append(pattern)

    logger.debug("Parsed %d ignore patterns from .sentinel-ignore", len(patterns))
    return patterns


def _find_inline_comment(line: str) -> int:
    """Find the index of an inline comment marker (#) in a line.

    Handles basic quoting: # inside quotes is not a comment marker.
    Returns -1 if no comment is found.
    """
    in_single_quote = False
    in_double_quote = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif ch == "#" and not in_single_quote and not in_double_quote:
            return i
    return -1


# Pattern Matching


def is_ignored(file_path: str, patterns: Sequence[str]) -> bool:
    """Check if a file path matches any of the ignore patterns.

    Patterns ending with / match directories (and everything inside).
    Other patterns are matched via fnmatch against the file path.
    """
    # Normalize path separators
    norm_path = file_path.replace("\\", "/")

    for pattern in patterns:
        norm_pattern = pattern.replace("\\", "/")

        # Strip leading ./ or / from patterns
        norm_pattern = norm_pattern.lstrip("./").lstrip("/")

        # Directory pattern (ends with /) — check if path starts with dir
        if norm_pattern.endswith("/"):
            if norm_path.startswith(norm_pattern) or f"/{norm_path}".startswith(f"/{norm_pattern}"):
                return True
        else:
            # Direct fnmatch against the full path
            if fnmatch.fnmatch(norm_path, norm_pattern):
                return True
            # Also try matching just the filename
            if fnmatch.fnmatch(Path(norm_path).name, norm_pattern):
                return True
            # Also try matching against path components
            if "/" in norm_pattern:
                if fnmatch.fnmatch(f"/{norm_path}", f"/{norm_pattern}"):
                    return True

    return False


# Finding Filtering


def filter_ignored_findings(
    findings: list[dict],
    patterns: Sequence[str],
) -> list[dict]:
    """Remove findings whose file_path matches any ignore pattern.

    Returns a new list with ignored findings removed.
    Logs how many findings were filtered.
    """
    if not patterns:
        return findings

    filtered: list[dict] = []
    ignored_count = 0

    for finding in findings:
        file_path = finding.get("file_path", "")
        if is_ignored(file_path, patterns):
            ignored_count += 1
            logger.debug("Ignored finding in %s (matches .sentinel-ignore pattern)", file_path)
        else:
            filtered.append(finding)

    if ignored_count:
        logger.info(
            "Filtered %d/%d findings via .sentinel-ignore patterns",
            ignored_count,
            len(findings),
        )

    return filtered
