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

import sys

from sentinel_review.workers.gha_runner import main

if __name__ == "__main__":
    sys.exit(main())
