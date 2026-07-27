"""
Load test script for Sentinel Review webhook endpoint.

Simulates concurrent GitHub webhook deliveries to verify the endpoint
returns quickly under load and the queue absorbs backpressure.

Usage:
    # Test local webhook
    python scripts/load_test.py --url http://localhost:8000/webhooks/github/ --concurrent 20 --total 100

    # Quick smoke test (10 requests, 5 concurrent)
    python scripts/load_test.py --concurrent 5 --total 10

    # Stress test (50 concurrent, 500 total)
    python scripts/load_test.py --concurrent 50 --total 500

The script sends minimal valid webhook payloads with HMAC signatures.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from statistics import mean, median, stdev
from typing import Any

import httpx


def _compute_signature(payload: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature matching GitHub's format."""
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_webhook_payload() -> tuple[bytes, str]:
    """Build a minimal valid pull_request webhook payload."""
    delivery_id = f"test-delivery-{time.time_ns()}"
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 9999,
            "title": f"Load test PR {delivery_id[-8:]}",
            "user": {"login": "load-tester"},
            "head": {"sha": "abc123"},
            "base": {"sha": "def456"},
        },
        "repository": {
            "id": 99999999,
            "full_name": "loadtest/test-repo",
            "private": False,
            "owner": {"login": "loadtest"},
        },
        "installation": {"id": 999999},
    }
    body = json.dumps(payload).encode()
    return body, delivery_id


def _send_request(
    client: httpx.Client,
    url: str,
    secret: str,
    timeout: float,
) -> dict[str, Any]:
    """Send a single webhook request and return timing/status info."""
    body, delivery_id = _build_webhook_payload()
    signature = _compute_signature(body, secret)

    start = time.monotonic()
    try:
        response = client.post(
            url,
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": delivery_id,
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        elapsed = (time.monotonic() - start) * 1000
        return {
            "status": response.status_code,
            "elapsed_ms": round(elapsed, 1),
            "error": None,
        }
    except httpx.TimeoutException:
        elapsed = (time.monotonic() - start) * 1000
        return {"status": 0, "elapsed_ms": round(elapsed, 1), "error": "timeout"}
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return {"status": 0, "elapsed_ms": round(elapsed, 1), "error": str(e)}


def run_load_test(
    url: str,
    secret: str,
    concurrent: int,
    total: int,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Run the load test with concurrent requests."""
    results: list[dict[str, Any]] = []

    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=concurrent) as executor:
            futures = [
                executor.submit(_send_request, client, url, secret, timeout)
                for _ in range(total)
            ]
            for future in as_completed(futures):
                results.append(future.result())

    return results


def _print_report(results: list[dict[str, Any]], concurrent: int, total: int, elapsed: float, webhook_url: str) -> None:
    """Print a formatted report of load test results."""
    statuses = [r["status"] for r in results]
    errors = [r for r in results if r["error"]]
    successes = [r for r in results if not r["error"]]

    print()
    print("=" * 60)
    print("  Sentinel Review — Webhook Load Test Report")
    print("=" * 60)
    print(f"  Date:         {datetime.now().isoformat()}")
    print(f"  URL:          {webhook_url}")
    print(f"  Concurrent:   {concurrent}")
    print(f"  Total:        {total}")
    print(f"  Duration:     {elapsed:.2f}s")
    print(f"  Throughput:   {total / elapsed:.1f} req/s")
    print()

    status_counts: dict[int, int] = {}
    for s in statuses:
        status_counts[s] = status_counts.get(s, 0) + 1

    print("  ── Status Codes ──")
    for code, count in sorted(status_counts.items()):
        label = {200: "OK (duplicate)", 202: "Accepted", 401: "Unauthorized", 429: "Rate Limited", 0: "Error"}.get(code, str(code))
        print(f"    {code} ({label}): {count} ({count / total * 100:.1f}%)")

    if errors:
        print()
        print(f"  ── Errors ({len(errors)}) ──")
        for err in errors[:5]:
            print(f"    {err['error']} ({err['elapsed_ms']}ms)")
        if len(errors) > 5:
            print(f"    ... and {len(errors) - 5} more")

    if successes:
        print()
        print("  ── Latency (successful requests) ──")
        success_ms = [r["elapsed_ms"] for r in successes]
        print(f"    Min:     {min(success_ms):.1f}ms")
        print(f"    Max:     {max(success_ms):.1f}ms")
        print(f"    Median:  {median(success_ms):.1f}ms")
        print(f"    Mean:    {mean(success_ms):.1f}ms")
        if len(success_ms) > 1:
            print(f"    StdDev:  {stdev(success_ms):.1f}ms")
        print()

        p50 = sorted(success_ms)[len(success_ms) // 2]
        p95 = sorted(success_ms)[int(len(success_ms) * 0.95)]
        p99 = sorted(success_ms)[int(len(success_ms) * 0.99)]
        print("  ── Percentiles ──")
        print(f"    p50:  {p50:.1f}ms")
        print(f"    p95:  {p95:.1f}ms")
        print(f"    p99:  {p99:.1f}ms")

    print()
    print("  ── Verdict ──")
    if errors:
        print("  ⚠️  Errors detected — investigate responses above.")
    elif all(s in (200, 202) for s in statuses):
        print("  ✅ All requests successful. Queue is absorbing backpressure.")
    elif statuses.count(429) > total * 0.1:
        print("  ⚠️  Rate limiting engaged (>10% 429s). Consider tuning throttle rates.")
    else:
        print("  ✅ Most requests successful. Acceptable rate limiting.")
    print("=" * 60)
    print()


def _find_webhook_secret() -> str:
    """Try to find the webhook secret from common sources."""
    # Try .env file
    env_paths = [".env", "../.env"]
    for path in env_paths:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("WEBHOOK_SECRET="):
                        val = line.split("=", 1)[1].strip().strip("\"'")
                        if val and not val.startswith("#"):
                            return val
    # Try environment
    return os.environ.get("WEBHOOK_SECRET", "change-me")


def main() -> int:
    """Entry point for the load test script."""
    parser = argparse.ArgumentParser(
        description="Load test the Sentinel Review webhook endpoint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/webhooks/github/",
        help="Webhook URL to test (default: http://localhost:8000/webhooks/github/)",
    )
    parser.add_argument(
        "--secret",
        default="",
        help="Webhook secret (default: auto-detect from .env or env var)",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=10,
        help="Number of concurrent requests (default: 10)",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=50,
        help="Total number of requests to send (default: 50)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Request timeout in seconds (default: 10.0)",
    )
    args = parser.parse_args()

    secret = args.secret or _find_webhook_secret()
    if not secret or secret == "change-me":
        print("⚠️  Could not determine WEBHOOK_SECRET. Use --secret to provide it.")
        return 1

    print(f"🚀 Starting load test: {args.total} requests, {args.concurrent} concurrent")
    print(f"   URL: {args.url}")
    print()

    start = time.monotonic()
    results = run_load_test(args.url, secret, args.concurrent, args.total, args.timeout)
    elapsed = time.monotonic() - start

    _print_report(results, args.concurrent, args.total, elapsed, args.url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
