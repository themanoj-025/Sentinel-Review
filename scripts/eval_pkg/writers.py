def _fetch_merged_prs(repo: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Fetch merged PRs from a repository using the GitHub Search API.

    Uses the /search/issues endpoint with `is:pr is:merged` qualifier.
    Returns up to max_results PR summary dicts.
    """
    query = f"repo:{repo} is:pr is:merged sort:created-desc"
    results: list[dict[str, Any]] = []

    try:
        data = _github_api_get(
            "/search/issues", params={"q": query, "per_page": min(max_results, 100), "page": 1}
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        for item in items[:max_results]:
            pr_num = item["number"]
            # Fetch full PR details
            pr_data = _github_api_get(f"/repos/{repo}/pulls/{pr_num}")
            if isinstance(pr_data, dict):
                results.append(pr_data)
        logger.info("  Fetched %d merged PRs from %s", len(results), repo)
    except (OSError, ValueError) as exc:
        logger.warning("  Failed to fetch PRs from %s: %s", repo, exc)

    return results


def _fetch_pr_review_comments(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch review comments for a specific PR."""
    try:
        data = _github_api_get(f"/repos/{repo}/pulls/{pr_number}/comments")
        return data if isinstance(data, list) else []
    except (OSError, ConnectionError, TimeoutError, KeyError, ValueError):
        return []


def _fetch_pr_issue_comments(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch general issue comments for a specific PR (timeline discussion)."""
    try:
        data = _github_api_get(f"/repos/{repo}/issues/{pr_number}/comments")
        return data if isinstance(data, list) else []
    except (OSError, ConnectionError, TimeoutError, KeyError, ValueError):
        return []


def _has_meaningful_review(comments: list[dict[str, Any]]) -> bool:
    """Check if a PR has review comments that suggest meaningful human review."""
    meaningful_keywords = [
        "should",
        "bug",
        "fix",
        "issue",
        "error",
        "vulnerable",
        "security",
        "incorrect",
        "wrong",
        "missing",
        "need",
        "must",
        "don't",
        "doesn't",
        "problem",
        "better to",
        "consider",
        "please",
        "suggest",
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

    logger.info(
        "GitHub dataset: %d entries from %d repos",
        len(all_entries),
        len({e["repo"] for e in all_entries}),
    )
    return all_entries


# Source 3: Synthetic planted-bug fixtures


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
        from tests.fixtures.sample_prs import FIXTURES
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

    logger.info(
        "Fixture dataset: %d entries (%d known issues)",
        len(entries),
        sum(len(fx["known_issues"]) for fx in FIXTURES),
    )
    return entries


# Combined output


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
        except (OSError, ValueError) as exc:
            logger.error("CodeReviewer source failed: %s", exc)
            logger.info("Continuing without CodeReviewer data.")

    if "github" in sources:
        try:
            entries = build_github_dataset(max_prs=max_github_prs)
            all_entries.extend(entries)
        except (OSError, ValueError) as exc:
            logger.error("GitHub source failed: %s", exc)
            logger.info("Continuing without GitHub data.")

    if "fixtures" in sources:
        try:
            entries = build_fixture_dataset()
            all_entries.extend(entries)
        except (OSError, ValueError) as exc:
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

    # Dependency check
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
            "Missing required dependencies: %s\nInstall with: pip install httpx",
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

    # Build
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
