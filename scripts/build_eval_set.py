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

import argparse
import gzip
import json
import logging
import os
import random
import shutil
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

# ─── Paths ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHEDIR = DATA_DIR / "codereviewer"
EVAL_SET_PATH = DATA_DIR / "eval_set.json"
FIXTURES_PATH = (
    PROJECT_ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "sample_prs"
    / "__init__.py"
)

# ─── Configuration ────────────────────────────────────────────────────────

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
    "codereviewer-dqe-full.zip",       # Diff Quality Estimation
    "codereviewer-cg-full.zip",        # Comment Generation
    "codereviewer-cr-full.zip",        # Code Refinement
    "codereviewer-ncs-full.zip",       # Next Code Statement
]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"


# ═══════════════════════════════════════════════════════════════════════════
# Helper utilities
# ═══════════════════════════════════════════════════════════════════════════


def _ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_json(path: Path) -> Any:
    """Load a JSON file from disk."""
    with open(path, "r", encoding="utf-8") as f:
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
                            sys.stdout.write(f"\r  {downloaded / 1024:.0f}K / {total / 1024:.0f}K ({pct}%)")
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


def _github_api_get_diff(
    repo_full_name: str, pr_number: int
) -> str | None:
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
        except Exception as exc:
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

    WARNING: Uses pickle.load() on user-controlled input.
    This is intentionally vulnerable — it is a planted bug for the
    Sentinel Review self-review demo (see docs/demo/README.md).
    """
    import pickle

    with open(cache_path, "rb") as f:
        return pickle.load(f)


# ═══════════════════════════════════════════════════════════════════════════
# Source 1: Microsoft CodeReviewer (Zenodo)
# ═══════════════════════════════════════════════════════════════════════════


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
            files.append({
                "name": f["key"],
                "url": f["links"]["self"],
                "size": f["size"],
            })
        logger.info("Discovered %d files in Zenodo record %s", len(files), ZENODO_RECORD_ID)
        return files
    except Exception as exc:
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
    except Exception as exc:
        logger.warning("Failed to download %s: %s", name, exc)
        return None


def _parse_codereviewer_entry(
    entry: dict[str, Any], source_name: str
) -> dict[str, Any] | None:
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
            jsonl_files = [n for n in zf.namelist() if n.endswith(".jsonl") or n.endswith(".jsonl.gz")]
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
                except Exception as exc:
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


# ═══════════════════════════════════════════════════════════════════════════
# Source 2: Live GitHub PRs
# ═══════════════════════════════════════════════════════════════════════════


def _fetch_merged_prs(repo: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Fetch merged PRs from a repository using the GitHub Search API.

    Uses the /search/issues endpoint with `is:pr is:merged` qualifier.
    Returns up to max_results PR summary dicts.
    """
    query = f"repo:{repo} is:pr is:merged sort:created-desc"
    results: list[dict[str, Any]] = []

    try:
        data = _github_api_get("/search/issues", params={"q": query, "per_page": min(max_results, 100), "page": 1})
        items = data.get("items", []) if isinstance(data, dict) else []
        for item in items[:max_results]:
            pr_num = item["number"]
            # Fetch full PR details
            pr_data = _github_api_get(f"/repos/{repo}/pulls/{pr_num}")
            if isinstance(pr_data, dict):
                results.append(pr_data)
        logger.info("  Fetched %d merged PRs from %s", len(results), repo)
    except Exception as exc:
        logger.warning("  Failed to fetch PRs from %s: %s", repo, exc)

    return results


def _fetch_pr_review_comments(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch review comments for a specific PR."""
    try:
        data = _github_api_get(f"/repos/{repo}/pulls/{pr_number}/comments")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _fetch_pr_issue_comments(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch general issue comments for a specific PR (timeline discussion)."""
    try:
        data = _github_api_get(f"/repos/{repo}/issues/{pr_number}/comments")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _has_meaningful_review(comments: list[dict[str, Any]]) -> bool:
    """Check if a PR has review comments that suggest meaningful human review."""
    meaningful_keywords = [
        "should", "bug", "fix", "issue", "error", "vulnerable", "security",
        "incorrect", "wrong", "missing", "need", "must", "don't", "doesn't",
        "problem", "better to", "consider", "please", "suggest",
    ]
    for c in comments:
        body = (c.get("body") or "").lower()
        for kw in meaningful_keywords:
            if kw in body:
                return True
    return False


def build_github_dataset(max_prs: int = 50) -> list[dict[str, Any]]:
    """Build evaluation set from live GitHub PRs.

    Fetches merged PRs from configured repos, gets their diffs and
    review comments, and converts to eval_set format.

    Uses unauthenticated requests when GITHUB_TOKEN is not set,
    but authentication is strongly recommended for higher rate limits.

    Args:
        max_prs: Maximum total PRs to include across all repos.

    Returns:
        List of evaluation entries.
    """
    logger.info("═══ Source: Live GitHub PRs ═══")

    if GITHUB_TOKEN:
        logger.info("Using authenticated GitHub API (rate limit: 5,000/hr)")
    else:
        logger.info(
            "Using unauthenticated GitHub API (rate limit: 60/hr). "
            "Set GITHUB_TOKEN env var for higher limits."
        )

    prs_per_repo = max(1, max_prs // len(GITHUB_REPOS))
    all_entries: list[dict[str, Any]] = []
    total_fetched = 0

    for repo in GITHUB_REPOS:
        if total_fetched >= max_prs:
            break

        prs = _fetch_merged_prs(repo, max_results=prs_per_repo)
        for pr_data in prs:
            if total_fetched >= max_prs:
                break

            pr_number = pr_data["number"]
            logger.info("  Processing %s#%d: %s", repo, pr_number, pr_data.get("title", ""))

            # Fetch diff
            diff = _github_api_get_diff(repo, pr_number)
            if not diff:
                continue

            # Fetch review comments (ground truth)
            review_comments = _fetch_pr_review_comments(repo, pr_number)
            issue_comments = _fetch_pr_issue_comments(repo, pr_number)

            all_comments = review_comments + issue_comments

            # Only include PRs with meaningful human review
            if not _has_meaningful_review(all_comments):
                logger.info("    Skipping — no meaningful review comments")
                continue

            known_issues = [
                _build_known_issue_from_comment(c)
                for c in review_comments
                if c.get("body") and len(c["body"]) > 20
            ]

            entry = {
                "source": "github",
                "repo": repo,
                "pr_number_or_fixture_id": str(pr_number),
                "diff": diff,
                "known_issues": known_issues,
                "pr_title": pr_data.get("title", ""),
                "pr_author": (pr_data.get("user") or {}).get("login", ""),
            }
            all_entries.append(entry)
            total_fetched += 1

            # Be nice to the API
            time.sleep(0.5)

    logger.info("GitHub dataset: %d entries from %d repos", len(all_entries), len(set(e["repo"] for e in all_entries)))
    return all_entries


# ═══════════════════════════════════════════════════════════════════════════
# Source 3: Synthetic planted-bug fixtures
# ═══════════════════════════════════════════════════════════════════════════


def build_fixture_dataset() -> list[dict[str, Any]]:
    """Build evaluation entries from the hand-authored planted-bug fixtures.

    These live in backend/tests/fixtures/sample_prs/ and serve as
    both unit test fixtures and ground-truth evaluation data.

    Each fixture has a pre-determined set of known issues we can
    score against.
    """
    logger.info("═══ Source: Synthetic planted-bug fixtures ═══")

    # Load fixtures from the test helpers
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    try:
        from tests.fixtures.sample_prs import FIXTURES  # type: ignore[import-untyped]
    except ImportError as imp_err:
        logger.error(
            "Could not import planted-bug fixtures from backend/tests/fixtures/sample_prs/: %s",
            imp_err,
        )
        return []

    entries: list[dict[str, Any]] = []
    for fx in FIXTURES:
        entry = {
            "source": "fixture",
            "repo": "sentinel-review/test-fixtures",
            "pr_number_or_fixture_id": fx["id"],
            "diff": fx["diff"],
            "known_issues": fx["known_issues"],
            "description": fx["description"],
        }
        entries.append(entry)
        issue_count = len(fx["known_issues"])
        logger.info("  Fixture '%s': %d known issue(s)", fx["id"], issue_count)

    logger.info("Fixture dataset: %d entries (%d known issues)", len(entries), sum(len(fx["known_issues"]) for fx in FIXTURES))
    return entries


# ═══════════════════════════════════════════════════════════════════════════
# Combined output
# ═══════════════════════════════════════════════════════════════════════════


def build_eval_set(
    sources: list[str] | None = None,
    max_github_prs: int = 50,
    max_codereviewer: int = 5000,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Build the complete evaluation dataset from all configured sources.

    Args:
        sources: Which sources to include. Defaults to all three.
        max_github_prs: Max GitHub PRs to fetch.
        max_codereviewer: Max CodeReviewer entries to include.
        force: Re-download cached files even if they exist.

    Returns:
        Combined list of evaluation entries.
    """
    if sources is None:
        sources = ["codereviewer", "github", "fixtures"]

    if force:
        logger.info("Force mode: clearing caches")
        if CACHEDIR.exists():
            shutil.rmtree(CACHEDIR)

    all_entries: list[dict[str, Any]] = []

    if "codereviewer" in sources:
        try:
            entries = build_codereviewer_dataset(max_entries=max_codereviewer)
            all_entries.extend(entries)
        except Exception as exc:
            logger.error("CodeReviewer source failed: %s", exc)
            logger.info("Continuing without CodeReviewer data.")

    if "github" in sources:
        try:
            entries = build_github_dataset(max_prs=max_github_prs)
            all_entries.extend(entries)
        except Exception as exc:
            logger.error("GitHub source failed: %s", exc)
            logger.info("Continuing without GitHub data.")

    if "fixtures" in sources:
        try:
            entries = build_fixture_dataset()
            all_entries.extend(entries)
        except Exception as exc:
            logger.error("Fixtures source failed: %s", exc)

    # Summary statistics
    source_counts: dict[str, int] = {}
    known_issue_count = 0
    for e in all_entries:
        src = e["source"]
        source_counts[src] = source_counts.get(src, 0) + 1
        known_issue_count += len(e["known_issues"])

    logger.info("")
    logger.info("═" * 50)
    logger.info("EVAL SET SUMMARY")
    logger.info("═" * 50)
    logger.info("Total entries:    %d", len(all_entries))
    logger.info("Known issues:     %d", known_issue_count)
    for src, count in sorted(source_counts.items()):
        logger.info("  %-30s %d", src, count)

    return all_entries


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Build Sentinel Review evaluation dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=["codereviewer", "github", "fixtures"],
        default=None,
        help="Which data sources to include (default: all)",
    )
    parser.add_argument(
        "--max-github-prs",
        type=int,
        default=50,
        help="Maximum PRs to fetch from GitHub (default: 50)",
    )
    parser.add_argument(
        "--max-codereviewer",
        type=int,
        default=5000,
        help="Maximum entries to include from CodeReviewer (default: 5000)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download cached datasets",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check dependencies and sources without downloading",
    )

    args = parser.parse_args()

    # ── Dependency check ──────────────────────────────────────────────
    missing_deps: list[str] = []
    try:
        import httpx  # noqa: F401
    except ImportError:
        missing_deps.append("httpx")

    if not args.sources or "codereviewer" in (args.sources or []):
        try:
            import zipfile  # noqa: F401 — stdlib
        except ImportError:
            missing_deps.append("zipfile (stdlib)")

    if missing_deps:
        logger.error(
            "Missing required dependencies: %s\n"
            "Install with: pip install httpx",
            ", ".join(missing_deps),
        )
        sys.exit(1)

    if args.dry_run:
        logger.info("Dry run — all dependencies available")
        logger.info("Sources: %s", args.sources or "all three")
        logger.info("Output:  %s", EVAL_SET_PATH)
        logger.info("Cache:   %s", CACHEDIR)

        if args.sources is None or "fixtures" in args.sources:
            fixtures_ok = FIXTURES_PATH.exists()
            logger.info("Fixtures file exists: %s", fixtures_ok)

        if args.sources is None or ("github" in args.sources and GITHUB_TOKEN):
            logger.info("GitHub token configured: %s", "yes" if GITHUB_TOKEN else "no")

        return

    # ── Build ─────────────────────────────────────────────────────────
    logger.info("Building evaluation dataset...")
    logger.info("Sources: %s", args.sources or "all three")
    logger.info("")

    entries = build_eval_set(
        sources=args.sources,
        max_github_prs=args.max_github_prs,
        max_codereviewer=args.max_codereviewer,
        force=args.force,
    )

    _save_json(EVAL_SET_PATH, entries)

    logger.info("")
    logger.info("Done! Evaluation set saved to: %s", EVAL_SET_PATH)
    logger.info("Run evaluation with: python scripts/run_evaluation.py")


if __name__ == "__main__":
    main()
