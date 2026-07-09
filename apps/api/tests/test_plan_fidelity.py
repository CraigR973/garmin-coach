"""Batch 67 — plan-JSON fidelity shape guard for ``plan_no2.json``.

Locks in the transcription of Mark's 13-week plan doc into real structured bike
sessions: every ``bike_*`` workout must expand to a multi-step IR with a warm-up
ramp, a cool-down, and work intervals at an explicit % — never the old single
collapsed block that delivered a flat 55% ride. The app-displayed total
(``duration_min``) must trace the summed delivered steps (total time plan -> app).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.plan_import import build_plan_rows
from src.services.workout_delivery import (
    DEFAULT_FTP_WATTS,
    expand_structured_steps,
)

PLAN_PATH = Path(__file__).resolve().parents[1] / "data" / "plans" / "plan_no2.json"


@pytest.fixture
def plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _bike_days(plan: dict) -> list[tuple[int, dict]]:
    days = []
    for wk in plan["weeks"]:
        for day in wk["days"]:
            if (day.get("structured_workout") or {}).get("format") == "bike":
                days.append((int(wk["week"]), day))
    return days


def test_every_bike_workout_is_a_real_structured_session(plan: dict) -> None:
    bike_days = _bike_days(plan)
    assert len(bike_days) == 65  # 13 weeks × 5 bike days
    for week, day in bike_days:
        where = f"W{week} {day['title']}"
        steps = expand_structured_steps(day["structured_workout"], day.get("intensity_target"))
        # No single-block bike step survives.
        assert len(steps) > 1, f"{where} collapsed to a single block"
        phases = {s["phase"] for s in steps}
        assert "warmup" in phases, f"{where} has no warm-up"
        assert "cooldown" in phases, f"{where} has no cool-down"
        assert any(s["kind"] == "ramp" for s in steps), f"{where} authors no ramp"


def test_total_time_traces_plan_to_app(plan: dict) -> None:
    # duration_min == the summed delivered steps for every bike workout, so the
    # number the app shows is the true ride length (fixes the VO2 60 -> 47 drift).
    for week, day in _bike_days(plan):
        steps = expand_structured_steps(day["structured_workout"], day.get("intensity_target"))
        total_sec = sum(int(s["durationSec"]) for s in steps)
        assert total_sec == day["duration_min"] * 60, f"W{week} {day['title']}"


def test_no_bike_workout_delivers_a_flat_55_percent_block(plan: dict) -> None:
    # The signature of the old silent fallback: a whole ride pinned at 55%.
    for week, day in _bike_days(plan):
        steps = expand_structured_steps(day["structured_workout"], day.get("intensity_target"))
        work_targets = {s["powerEndPct"] for s in steps if s["phase"] == "interval"}
        assert work_targets != {55}, f"W{week} {day['title']} looks like a flat 55% ride"


def test_week1_vo2_delivers_as_120_percent_intervals(plan: dict) -> None:
    day = next(d for w, d in _bike_days(plan) if w == 1 and d["workout_type"] == "bike_vo2")
    steps = expand_structured_steps(day["structured_workout"], day.get("intensity_target"))
    work = [s for s in steps if s["label"].startswith("VO₂") and "work" in s["label"]]
    assert len(work) == 5
    assert all(s["powerStartPct"] == 120 for s in work)
    assert {s["phase"] for s in steps} >= {"warmup", "cooldown"}
    assert sum(int(s["durationSec"]) for s in steps) == 47 * 60


def test_endurance_bands_deliver_their_midpoint(plan: dict) -> None:
    # Long Z2 65–72% -> 68; easy/recovery Z2 60–65% -> 62 (Decision #140).
    long_z2 = next(d for w, d in _bike_days(plan) if w == 1 and d["title"] == "Long Z2")
    steps = expand_structured_steps(long_z2["structured_workout"], long_z2.get("intensity_target"))
    main = max(steps, key=lambda s: s["durationSec"])
    assert main["powerStartPct"] == 68

    easy_z2 = next(d for w, d in _bike_days(plan) if w == 3 and d["dow"] == 6)
    easy_steps = expand_structured_steps(
        easy_z2["structured_workout"], easy_z2.get("intensity_target")
    )
    easy_main = max(easy_steps, key=lambda s: s["durationSec"])
    assert easy_main["powerStartPct"] == 62


def test_build_plan_rows_accepts_the_transcribed_plan(plan: dict) -> None:
    # The import gate (build_plan_rows validates every bike workout) passes for the
    # committed plan and yields the expected block/workout counts.
    rows = build_plan_rows(plan)
    assert len(rows.blocks) == 13
    assert len(rows.workouts) == 87  # 65 bike + 22 strength


def test_default_ftp_matches_the_plan(plan: dict) -> None:
    # FTP stays 280W (Decision #140) — the delivery default and the plan agree.
    assert plan["ftp_watts"] == DEFAULT_FTP_WATTS


def test_build_plan_rows_rejects_a_single_block_bike_plan() -> None:
    # The import gate fails a malformed plan (single collapsed block, no ramps)
    # before anything can reach Zwift.
    bad_plan = {
        "name": "bad",
        "source": "test_bad_plan",
        "start_date": "2026-07-06",
        "weeks": [
            {
                "week": 1,
                "label": "BUILD",
                "block_type": "build",
                "days": [
                    {
                        "dow": 1,
                        "rest": False,
                        "title": "VO₂",
                        "workout_type": "bike_vo2",
                        "duration_min": 60,
                        "intensity_target": "VO₂ (see prescription)",
                        "structured_workout": {
                            "format": "bike",
                            "steps": [
                                {"label": "VO₂", "minutes": 60, "target": "see prescription"}
                            ],
                        },
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError):
        build_plan_rows(bad_plan)
