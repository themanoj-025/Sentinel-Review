#!/usr/bin/env python3
"""
Sentinel Review — GitHub Actions execution mode.

Thin entry point for CI. The implementation lives in
backend/sentinel_review/workers/gha_runner.py so it can be
imported and tested without path manipulation.

Usage:
    python scripts/gha_review.py

Environment variables (set by the composite action):
    GITHUB_TOKEN          — GitHub API token
    GITHUB_REPOSITORY     — owner/repo
    GITHUB_EVENT_PATH     — path to the event payload JSON file
    ANTHROPIC_API_KEY     — optional, for Claude
    OPENAI_API_KEY        — optional, for GPT-4o
    LLM_PROVIDER          — "anthropic" (default) or "openai"
"""

import os
import sys

# Add backend/ to the path so we can import from sentinel_review
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.normpath(_BACKEND_DIR))

from sentinel_review.workers.gha_runner import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
