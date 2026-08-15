from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch


def _load_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "monitor_deploy_freshness.py"
    spec = importlib.util.spec_from_file_location("monitor_deploy_freshness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["monitor_deploy_freshness"] = module
    spec.loader.exec_module(module)
    return module


monitor = _load_module()


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_monitor_retries_stale_path_until_both_match() -> None:
    clock = _Clock()
    seen = {"railway": 0, "vercel": 0}

    def fetch(name: str, url: str, timeout: float):
        seen[name] += 1
        sha = "old" if name == "vercel" and seen[name] == 1 else "expected"
        return monitor.HealthObservation(name, url, sha)

    fresh, observations = monitor.poll_until_fresh(
        "expected",
        [("railway", "https://railway/health"), ("vercel", "https://vercel/health")],
        timeout_seconds=30,
        interval_seconds=5,
        fetch=fetch,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert fresh is True
    assert {item.sha for item in observations} == {"expected"}
    assert seen == {"railway": 2, "vercel": 2}


def test_simulated_stale_sha_emits_alert_and_exits_nonzero(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    stale = [
        monitor.HealthObservation("railway", "https://railway/health", "old"),
        monitor.HealthObservation("vercel", "https://vercel/health", "old"),
    ]
    with patch.object(monitor, "poll_until_fresh", return_value=(False, stale)):
        exit_code = monitor.main(
            [
                "--expected-sha",
                "expected",
                "--endpoint",
                "railway=https://railway/health",
                "--endpoint",
                "vercel=https://vercel/health",
                "--timeout-seconds",
                "0",
            ]
        )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "::error title=Stale production deployment::" in captured.out
    assert "expected SHA expected" in captured.err
