#!/usr/bin/env python3
"""The app's watchdog, run from outside it (Batch 365.1, DS357-02).

A scheduled GitHub Actions job runs this every 30 minutes. It reads production's
``/api/v1/health/ready`` (the database answers) and ``/api/v1/health/jobs`` (every
scheduled job ran recently and is not failing, Garmin and Hive accept the app's login,
today's brief did not fail), and exits 1 with the problems if either says no, so the
workflow fails and GitHub emails Craig. Before this nothing outside the process watched
it: the 25 Oct database outage and the 1 Nov Garmin refusal reached nobody.

Standard library only, so the job needs no install and no secret.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

Fetch = Callable[[str, float], tuple[int, dict[str, Any]]]


def fetch_json(url: str, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "garmin-coach-watchdog/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            body = {}
        return exc.code, body
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return 0, {"error": type(exc).__name__}


def problems(
    base_url: str, *, fetch: Fetch = fetch_json, timeout_seconds: float = 20.0
) -> list[str]:
    """Every problem production reports, or that reading it found."""

    base = base_url.rstrip("/")
    found: list[str] = []
    status, ready = fetch(f"{base}/api/v1/health/ready", timeout_seconds)
    if status != 200 or ready.get("db") != "ok":
        found.append(f"not_ready:http_{status}")
    status, jobs = fetch(f"{base}/api/v1/health/jobs", timeout_seconds)
    if status != 200:
        found.append(f"jobs_unreadable:http_{status}")
    reported = jobs.get("problems")
    if isinstance(reported, list):
        found.extend(str(item) for item in reported)
    elif status == 200:
        found.append("jobs_unreadable:no_problems_field")
    return list(dict.fromkeys(found))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)
    found = problems(args.base_url, timeout_seconds=args.timeout_seconds)
    if found:
        print("Production needs attention:")
        for item in found:
            print(f"- {item}")
        return 1
    print("Production is healthy: database ready, every job fresh, no refused login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
