#!/usr/bin/env python3
"""Poll production health paths until both serve the expected Git SHA.

Designed for a post-merge GitHub Actions job. A stale or unreachable endpoint
after the bounded timeout exits 1, making the workflow itself the operator
alert for a dropped Railway/Vercel deployment webhook.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthObservation:
    name: str
    url: str
    sha: str | None
    error: str | None = None


FetchHealth = Callable[[str, str, float], HealthObservation]


def fetch_health(
    name: str, url: str, request_timeout_seconds: float
) -> HealthObservation:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "garmin-coach-deploy-monitor/1",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=request_timeout_seconds
        ) as response:
            body = json.loads(response.read())
            if response.status != 200:
                return HealthObservation(name, url, None, f"HTTP {response.status}")
            if body.get("status") != "ok":
                return HealthObservation(
                    name, url, None, f"status={body.get('status')!r}"
                )
            sha = body.get("sha")
            if not isinstance(sha, str) or not sha:
                return HealthObservation(name, url, None, "missing sha")
            return HealthObservation(name, url, sha)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return HealthObservation(name, url, None, f"{type(exc).__name__}: {exc}")


def poll_until_fresh(
    expected_sha: str,
    endpoints: Sequence[tuple[str, str]],
    *,
    timeout_seconds: float,
    interval_seconds: float,
    request_timeout_seconds: float = 10,
    fetch: FetchHealth = fetch_health,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, list[HealthObservation]]:
    """Return once every endpoint matches, or after the bounded deadline."""

    deadline = monotonic() + timeout_seconds
    latest: list[HealthObservation] = []
    while True:
        latest = [fetch(name, url, request_timeout_seconds) for name, url in endpoints]
        if all(item.sha == expected_sha for item in latest):
            return True, latest
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False, latest
        sleep(min(interval_seconds, remaining))


def _parse_endpoint(value: str) -> tuple[str, str]:
    name, separator, url = value.partition("=")
    if not separator or not name or not url.startswith(("https://", "http://")):
        raise argparse.ArgumentTypeError(
            "endpoint must be NAME=https://host/api/v1/health"
        )
    return name, url


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail unless every production health path reaches an expected Git SHA."
    )
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--endpoint",
        action="append",
        required=True,
        type=_parse_endpoint,
        help="Repeatable NAME=URL health endpoint",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--interval-seconds", type=float, default=15)
    parser.add_argument("--request-timeout-seconds", type=float, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.timeout_seconds < 0 or args.interval_seconds <= 0:
        _build_parser().error("timeout must be >= 0 and interval must be > 0")

    print(
        f"[deploy-freshness] expected={args.expected_sha} "
        f"timeout={args.timeout_seconds:g}s"
    )
    fresh, observations = poll_until_fresh(
        args.expected_sha,
        args.endpoint,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=args.interval_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    for item in observations:
        detail = f"sha={item.sha}" if item.sha is not None else f"error={item.error}"
        print(f"[deploy-freshness] {item.name}: {detail} ({item.url})")
    if fresh:
        print("[deploy-freshness] PASS: both production paths serve the expected SHA")
        return 0

    message = (
        f"Production did not reach expected SHA {args.expected_sha} within "
        f"{args.timeout_seconds:g}s"
    )
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title=Stale production deployment::{message}")
    print(f"[deploy-freshness] FAIL: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
