#!/usr/bin/env python3
"""
Sentinel Review — Data Acquisition Pipeline (build_eval_set.py)

Builds the evaluation dataset from three sources:
1. Microsoft CodeReviewer dataset (Zenodo archive)
2. Live GitHub pull requests from popular open-source repos
3. Synthetic planted-bug fixtures (local, hand-authored)

Usage:
    python scripts/build_eval_set.py              # Full pipeline
    python scripts/build_eval_set.py --sources fixtures  # Fixtures only
    python scripts/build_eval_set.py --sources github    # GitHub PRs only
    python scripts/build_eval_set.py --sources codereviewer  # MS codereviewer only
    python scripts/build_eval_set.py --max-github-prs 10   # Limit GitHub PRs
    python scripts/build_eval_set.py --force              # Re-download everything

Output:
    data/eval_set.json  — Structured evaluation dataset (committed)
    data/codereviewer/  — Raw CodeReviewer dataset cache (gitignored)
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import random
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_eval_set")

# Paths

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHEDIR = DATA_DIR / "codereviewer"
EVAL_SET_PATH = DATA_DIR / "eval_set.json"
FIXTURES_PATH = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "sample_prs" / "__init__.py"

# Configuration

# Repos to sample for live PR data — diverse, permissively-licensed, Python-heavy.
# Selected to avoid overfitting to one project's code style.
GITHUB_REPOS = [
    "pallets/flask",
    "pytest-dev/pytest",
    "encode/httpx",
    "psf/requests",
    "django/django",
    "tiangolo/fastapi",
    "pallets/click",
    "pydantic/pydantic",
    "sqlalchemy/sqlalchemy",
    "pytest-dev/pluggy",
]

ZENODO_RECORD_ID = "6900648"
ZENODO_BASE = f"https://zenodo.org/records/{ZENODO_RECORD_ID}"

# Known files in the CodeReviewer Zenodo archive (as of 2024):
# These are the task-specific dataset zip files.
# We check which ones actually exist and skip missing ones gracefully.
CODEREVIEWER_FILES = [
    "codereviewer-dqe-full.zip",  # Diff Quality Estimation
    "codereviewer-cg-full.zip",  # Comment Generation
    "codereviewer-cr-full.zip",  # Code Refinement
    "codereviewer-ncs-full.zip",  # Next Code Statement
]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"


# Helper utilities


def _ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_json(path: Path) -> Any:
    """Load a JSON file from disk."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: Any) -> None:
    """Save data as pretty-printed JSON to disk."""
    _ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Wrote %s (%d entries)", path.name, len(data) if isinstance(data, list) else 1)


def _download_file(url: str, dest: Path, chunk_size: int = 8192) -> None:
    """Download a file with a progress indicator.

    Uses urllib for zero external dependencies on the core path.
    Falls back to httpx if available for better redirect handling.
    """
    logger.info("Downloading %s → %s", url, dest.name)
    _ensure_dir(dest.parent)

    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=300) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                dest_path = dest.with_suffix(".part")
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            sys.stdout.write(
                                f"\r  {downloaded / 1024:.0f}K / {total / 1024:.0f}K ({pct}%)"
                            )
                            sys.stdout.flush()
                sys.stdout.write("\n")
                dest_path.rename(dest)
    except ImportError:
        # Fallback to urllib
        import urllib.request

        dest_path = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, str(dest_path))
        dest_path.rename(dest)


def _github_api_get(path: str, params: dict | None = None) -> dict[str, Any] | list[Any]:
    """Call the GitHub REST API with optional auth and rate-limit handling."""
    import httpx

    url = f"{GITHUB_API}{path}" if not path.startswith("http") else path
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "sentinel-review-eval-builder/1.0",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    with httpx.Client(follow_redirects=True, timeout=60) as client:
        while True:
            resp = client.get(url, params=params, headers=headers)

            if resp.status_code == 403 and int(resp.headers.get("X-RateLimit-Remaining", 1)) == 0:
                if not GITHUB_TOKEN:
                    logger.error(
                        "Rate limited by GitHub API without GITHUB_TOKEN. "
                        "Set the GITHUB_TOKEN env var for a higher rate limit (5,000/hr)."
                    )
                    return {} if path.startswith("/search") else {}
                reset_ts = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                sleep_secs = max(reset_ts - time.time() + 1, 1)
                logger.warning("Rate limited. Sleeping %d seconds...", sleep_secs)
                time.sleep(min(sleep_secs, 600))
                continue

            resp.raise_for_status()
            return resp.json()


def _github_api_get_diff(repo_full_name: str, pr_number: int) -> str | None:
    """Fetch the raw diff for a PR."""
    import httpx

    url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "sentinel-review-eval-builder/1.0",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    with httpx.Client(follow_redirects=True, timeout=60) as client:
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code == 403:
                if not GITHUB_TOKEN:
                    logger.error(
                        "Rate limited on diff fetch without GITHUB_TOKEN. "
                        "Set the GITHUB_TOKEN env var for a higher rate limit."
                    )
                    return None
                reset_ts = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                sleep_secs = max(reset_ts - time.time() + 1, 1)
                logger.warning("Rate limited on diff fetch. Sleeping %d seconds...", sleep_secs)
                time.sleep(min(sleep_secs, 600))
                return _github_api_get_diff(repo_full_name, pr_number)
            resp.raise_for_status()
            return resp.text
        except (OSError, ValueError) as exc:
            logger.warning("Failed to fetch diff for %s#%d: %s", repo_full_name, pr_number, exc)
            return None


def _build_known_issue_from_comment(comment: dict[str, Any]) -> dict[str, Any]:
    """Convert a GitHub review comment dict to our known_issues format."""
    return {
        "file_path": comment.get("path", ""),
        "line_number": comment.get("line") or comment.get("original_line"),
        "category": "suggestion",  # We can't infer category from human comments
        "severity": "warning",
        "description": comment.get("body", "")[:500],
    }


def _load_cached_evaluation_results(cache_path: str) -> dict:
    """Load cached evaluation results from a pickle file.

    WARNING: This function contains a pickle.load() on caller-supplied input
    (CWE-502). It is a deliberately planted demo fixture for the Sentinel
    Review self-review demo (see docs/demo/README.md) — the call below is
    what the bot is supposed to flag. It has no production callers.

    FAIL-CLOSED GUARD: even as a demo, this function refuses to run unless
    BOTH conditions hold, so it can never be wired into a real code path or
    pointed at attacker-controlled files by accident:
      1. the env opt-in ``SENTINEL_EVAL_ALLOW_PICKLE_DEMO=1`` is set, AND
      2. ``cache_path`` resolves inside the repo-controlled eval cache dir
         (``data/codereviewer``).
    Otherwise it raises before any file is opened or unpickled.
    """
    import os
    import pickle

    if os.environ.get("SENTINEL_EVAL_ALLOW_PICKLE_DEMO") != "1":
        raise RuntimeError(
            "Refusing pickle cache load: demo opt-in "
            "SENTINEL_EVAL_ALLOW_PICKLE_DEMO=1 is not set "
            f"(path: {cache_path}). This is an intentionally vulnerable demo "
            "fixture and must never run outside the self-review demo."
        )

    cache_dir = Path(CACHEDIR).resolve()
    target = Path(cache_path).resolve()
    if not target.is_relative_to(cache_dir):
        raise RuntimeError(
            "Refusing pickle cache load outside the repo-controlled eval "
            f"cache dir ({CACHEDIR}): {cache_path}"
        )

    with open(cache_path, "rb") as f:
        return pickle.load(f)


# Source 1: Microsoft CodeReviewer (Zenodo)


def _discover_zenodo_files() -> list[dict[str, str]]:
    """Query Zenodo API to discover downloadable files for the CodeReviewer record.

    Returns a list of {name, url, size} dicts.
    """
    import httpx

    try:
        resp = httpx.get(f"https://zenodo.org/api/records/{ZENODO_RECORD_ID}", timeout=30)
        resp.raise_for_status()
        record = resp.json()
        files = []
        for f in record.get("files", []):
            files.append(
                {
                    "name": f["key"],
                    "url": f["links"]["self"],
                    "size": f["size"],
                }
            )
        logger.info("Discovered %d files in Zenodo record %s", len(files), ZENODO_RECORD_ID)
        return files
    except (OSError, ValueError) as exc:
        logger.warning("Could not query Zenodo API: %s", exc)
        logger.info("Falling back to known file list for record %s", ZENODO_RECORD_ID)
        # Fallback: construct URLs from known filenames
        return [
            {
                "name": fname,
                "url": f"{ZENODO_BASE}/files/{fname}",
                "size": 0,
            }
            for fname in CODEREVIEWER_FILES
        ]


def _download_codereviewer_archive(file_info: dict[str, str], dest_dir: Path) -> Path | None:
    """Download a single CodeReviewer zip archive if not already cached."""
    name = file_info["name"]
    dest = dest_dir / name
    if dest.exists() and dest.stat().st_size > 1000:
        logger.info("Already cached: %s (%d bytes)", name, dest.stat().st_size)
        return dest

    try:
        _download_file(file_info["url"], dest)
        return dest
    except (OSError, ValueError) as exc:
        logger.warning("Failed to download %s: %s", name, exc)
        return None


def _parse_codereviewer_entry(entry: dict[str, Any], source_name: str) -> dict[str, Any] | None:
    """Convert a CodeReviewer JSONL entry to eval_set format.

    The CodeReviewer dataset has varying schemas per task. We normalize
    to our common format: {source, repo, pr_number_or_fixture_id, diff, known_issues}.
    """
    diff = entry.get("diff") or entry.get("patch") or ""
    if not diff:
        return None

    # Extract a repo identifier if available
    repo = entry.get("repo") or entry.get("project") or source_name
    pr_id = str(entry.get("review_id") or entry.get("id", "unknown"))

    # The dataset may include existing review comments as ground truth
    comments = entry.get("comments") or entry.get("review_comments") or []
    known_issues = [_build_known_issue_from_comment(c) for c in comments]

    return {
        "source": f"codereviewer/{source_name}",
        "repo": repo,
        "pr_number_or_fixture_id": pr_id,
        "diff": diff,
        "known_issues": known_issues,
    }


def _extract_codereviewer_entries(zip_path: Path) -> list[dict[str, Any]]:
    """Extract and parse JSONL files from a CodeReviewer zip archive."""
    entries: list[dict[str, Any]] = []
    source_name = zip_path.stem  # e.g. "codereviewer-dqe-full"

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            jsonl_files = [
                n for n in zf.namelist() if n.endswith(".jsonl") or n.endswith(".jsonl.gz")
            ]
            if not jsonl_files:
                # Some archives use nested directories
                for name in zf.namelist():
                    if name.endswith((".jsonl", ".jsonl.gz", ".json")):
                        jsonl_files.append(name)

            logger.info("  Found %d JSONL file(s) in %s", len(jsonl_files), source_name)

            for jsonl_name in jsonl_files:
                try:
                    raw = zf.read(jsonl_name)
                    if jsonl_name.endswith(".gz"):
                        raw = gzip.decompress(raw)

                    text = raw.decode("utf-8", errors="replace")
                    for line in text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            parsed = _parse_codereviewer_entry(entry, source_name)
                            if parsed:
                                entries.append(parsed)
                        except json.JSONDecodeError:
                            continue
                except (OSError, ValueError) as exc:
                    logger.warning("  Failed to process %s: %s", jsonl_name, exc)
                    continue

    except zipfile.BadZipFile:
        logger.warning("Bad zip file: %s", zip_path)

    logger.info("  Extracted %d entries from %s", len(entries), source_name)
    return entries


def build_codereviewer_dataset(max_entries: int = 5000) -> list[dict[str, Any]]:
    """Build the evaluation subset from Microsoft CodeReviewer dataset.

    Steps:
    1. Discover files from Zenodo API (or fallback to known names)
    2. Download any uncached zip archives
    3. Extract and parse JSONL entries into normalized format
    4. Subsample to max_entries to keep eval_set.json manageable

    Returns a list of evaluation entries.
    """
    logger.info("═══ Source: Microsoft CodeReviewer (Zenodo) ═══")
    cache_dir = _ensure_dir(CACHEDIR)
    all_entries: list[dict[str, Any]] = []

    # Discover downloadable files
    files = _discover_zenodo_files()
    if not files:
        logger.warning("No files discovered for CodeReviewer dataset. Skipping.")
        return all_entries

    # Filter to the CodeReviewer-specific zip files
    codereviewer_zips = [f for f in files if f["name"].startswith("codereviewer")]
    if not codereviewer_zips:
        logger.warning("No CodeReviewer zip files found in record. Trying all zips...")
        codereviewer_zips = [f for f in files if f["name"].endswith(".zip")]

    logger.info("Found %d CodeReviewer zip file(s) to process", len(codereviewer_zips))

    for file_info in codereviewer_zips:
        zip_path = _download_codereviewer_archive(file_info, cache_dir)
        if zip_path:
            entries = _extract_codereviewer_entries(zip_path)
            all_entries.extend(entries)

    if not all_entries:
        logger.warning(
            "No entries extracted from CodeReviewer dataset. "
            "This is expected if the Zenodo record structure has changed. "
            "The script will still produce output from the other two sources."
        )
        return all_entries

    # Subsample to keep the eval set manageable
    if len(all_entries) > max_entries:
        logger.info("Subsampling %d entries to %d", len(all_entries), max_entries)
        random.seed(42)
        random.shuffle(all_entries)
        all_entries = all_entries[:max_entries]

    logger.info("CodeReviewer dataset: %d total entries", len(all_entries))
    return all_entries


# Source 2: Live GitHub PRs


