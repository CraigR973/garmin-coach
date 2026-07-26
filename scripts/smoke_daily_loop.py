#!/usr/bin/env python3
"""
Non-mutating end-to-end smoke test for the garmin-coach daily loop.

Usage:
    API_URL=https://api-production-e2bc7.up.railway.app python3 scripts/smoke_daily_loop.py

Optional authentication (runs the daily-loop check when set):
    SMOKE_DEVICE_TOKEN=<opaque-device-token> ... python3 scripts/smoke_daily_loop.py

Exit code 0 on pass, 1 on failure.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

API_URL = os.environ.get(
    "API_URL", "https://api-production-e2bc7.up.railway.app"
).rstrip("/")
SMOKE_DEVICE_TOKEN = os.environ.get("SMOKE_DEVICE_TOKEN", "")
SMOKE_STRICT_DAILY_LOOP = os.environ.get("SMOKE_STRICT_DAILY_LOOP", "").lower() in {
    "1",
    "true",
    "yes",
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = field(default="")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception as exc:  # noqa: BLE001
        return 0, {"_error": str(exc)}


# ---------------------------------------------------------------------------
# Response parsers (importable/testable)
# ---------------------------------------------------------------------------


def parse_health_response(body: dict[str, Any]) -> bool:
    return body.get("status") == "ok"


def parse_daily_loop_response(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("data", {})


def parse_daily_loop_gate_failures(data: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not data.get("dailyMetrics"):
        failures.append("dailyMetrics missing")
    if not data.get("sleep"):
        failures.append("sleep missing")
    if not data.get("morningAnalysis"):
        failures.append("morningAnalysis missing")

    thermal = data.get("thermalState") or {}
    if thermal.get("latestTemperatureC") is None:
        failures.append("Hive latestTemperatureC missing")
    if thermal.get("overnightLowC") is None:
        failures.append("weather overnightLowC missing")
    if thermal.get("overnightWindMaxMph") is None:
        failures.append("weather overnightWindMaxMph missing")
    return failures


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_health(api_url: str) -> CheckResult:
    status, body = _get(f"{api_url}/api/v1/health")
    if status != 200:
        return CheckResult("health", False, f"HTTP {status}")
    if not parse_health_response(body):
        return CheckResult("health", False, f"status={body.get('status')!r}")
    sha = body.get("sha", "unknown")
    return CheckResult("health", True, f"sha={sha}")


def check_daily_loop(api_url: str, token: str, *, strict: bool = False) -> CheckResult:
    status, body = _get(
        f"{api_url}/api/v1/daily-loop",
        headers={"Authorization": f"Bearer {token}"},
    )
    if status != 200:
        return CheckResult("daily_loop", False, f"HTTP {status}")
    data = parse_daily_loop_response(body)
    subject_date = data.get("subjectDate")
    if not subject_date:
        return CheckResult("daily_loop", False, "no subjectDate in response")
    if strict:
        gate_failures = parse_daily_loop_gate_failures(data)
        if gate_failures:
            return CheckResult("daily_loop", False, "; ".join(gate_failures))
    morning = data.get("morningAnalysis")
    verdict_val = morning.get("verdict", "none") if morning else "pending"
    return CheckResult(
        "daily_loop", True, f"subjectDate={subject_date} verdict={verdict_val}"
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _print(result: CheckResult) -> None:
    icon = "PASS" if result.passed else "FAIL"
    detail = f" ({result.detail})" if result.detail else ""
    print(f"[smoke] [{icon}] {result.name}{detail}")


def main() -> int:
    results: list[CheckResult] = []

    print(f"[smoke] target: {API_URL}")

    health_result = check_health(API_URL)
    results.append(health_result)
    _print(health_result)

    if SMOKE_DEVICE_TOKEN:
        loop_result = check_daily_loop(
            API_URL, SMOKE_DEVICE_TOKEN, strict=SMOKE_STRICT_DAILY_LOOP
        )
        results.append(loop_result)
        _print(loop_result)
    else:
        print("[smoke] SMOKE_DEVICE_TOKEN not set — skipping authenticated checks")

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"[smoke] {passed}/{total} checks passed")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
