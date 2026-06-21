"""Unit tests for smoke script helper functions."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_smoke() -> types.ModuleType:
    path = Path(__file__).parent.parent.parent.parent / "scripts" / "smoke_daily_loop.py"
    spec = importlib.util.spec_from_file_location("smoke_daily_loop", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["smoke_daily_loop"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_smoke = _load_smoke()


# ---------------------------------------------------------------------------
# parse_health_response
# ---------------------------------------------------------------------------


def test_parse_health_ok() -> None:
    assert _smoke.parse_health_response({"status": "ok", "sha": "abc123"}) is True


def test_parse_health_not_ok() -> None:
    assert _smoke.parse_health_response({"status": "error"}) is False


def test_parse_health_empty() -> None:
    assert _smoke.parse_health_response({}) is False


# ---------------------------------------------------------------------------
# parse_login_response
# ---------------------------------------------------------------------------


def test_parse_login_data_envelope() -> None:
    token = _smoke.parse_login_response({"data": {"access_token": "tok123"}})
    assert token == "tok123"


def test_parse_login_flat() -> None:
    token = _smoke.parse_login_response({"access_token": "tok456"})
    assert token == "tok456"


def test_parse_login_missing() -> None:
    assert _smoke.parse_login_response({}) == ""


def test_parse_login_prefers_data_envelope() -> None:
    body = {"data": {"access_token": "inner"}, "access_token": "outer"}
    assert _smoke.parse_login_response(body) == "inner"


# ---------------------------------------------------------------------------
# parse_daily_loop_response
# ---------------------------------------------------------------------------


def test_parse_daily_loop_returns_data() -> None:
    body = {"data": {"subjectDate": "2026-06-20", "morningAnalysis": None}}
    data = _smoke.parse_daily_loop_response(body)
    assert data["subjectDate"] == "2026-06-20"


def test_parse_daily_loop_missing_data() -> None:
    data = _smoke.parse_daily_loop_response({})
    assert data == {}


def test_parse_daily_loop_ignores_meta() -> None:
    body = {
        "data": {"subjectDate": "2026-06-20"},
        "meta": {"generatedAtUtc": "2026-06-20T07:00:00Z"},
    }
    data = _smoke.parse_daily_loop_response(body)
    assert "meta" not in data


def test_parse_daily_loop_gate_failures_passes_with_live_data() -> None:
    failures = _smoke.parse_daily_loop_gate_failures(
        {
            "dailyMetrics": {"readinessScore": 75},
            "sleep": {"score": 71},
            "morningAnalysis": {"verdict": "Green"},
            "thermalState": {
                "latestTemperatureC": 18.5,
                "overnightLowC": 12.4,
                "overnightWindMaxMph": 8.1,
            },
        }
    )

    assert failures == []


def test_parse_daily_loop_gate_failures_reports_empty_production_loop() -> None:
    failures = _smoke.parse_daily_loop_gate_failures(
        {
            "dailyMetrics": None,
            "sleep": None,
            "morningAnalysis": None,
            "thermalState": {
                "latestTemperatureC": None,
                "overnightLowC": None,
                "overnightWindMaxMph": None,
            },
        }
    )

    assert failures == [
        "dailyMetrics missing",
        "sleep missing",
        "morningAnalysis missing",
        "Hive latestTemperatureC missing",
        "weather overnightLowC missing",
        "weather overnightWindMaxMph missing",
    ]
