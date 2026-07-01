"""Tests for the training-plan importer (DECISIONS #102).

Pure ``build_plan_rows`` mapping only — no DB — validated against the committed
reviewed plan (``apps/api/data/plans/plan_no2.json``):
  1. 13 Monday-anchored blocks with sequential weekly dates.
  2. Block types match the 2121-ish structure (recovery / consolidation / taper).
  3. Weekly shape: Friday is rest (no row); Wednesday is a Z2 endurance ride.
  4. Start date must be a Monday; an override re-anchors the whole plan.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.services.plan_import import build_plan_rows

PLAN_PATH = Path(__file__).resolve().parents[1] / "data" / "plans" / "plan_no2.json"


@pytest.fixture
def plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def test_thirteen_blocks_monday_anchored(plan: dict) -> None:
    rows = build_plan_rows(plan)
    assert len(rows.blocks) == 13
    assert rows.start_date == date(2026, 7, 6)
    for i, block in enumerate(rows.blocks):
        assert block.sequence_index == i + 1
        assert block.start_date == date(2026, 7, 6) + timedelta(weeks=i)
        assert block.start_date.weekday() == 0
        assert (block.end_date - block.start_date).days == 6
    # names carry the prefix so a re-import can find + clear its own rows
    assert rows.blocks[0].name.startswith("PN2 W01")


def test_block_types_follow_structure(plan: dict) -> None:
    by_seq = {b.sequence_index: b.block_type for b in build_plan_rows(plan).blocks}
    assert by_seq[3] == "recovery"
    assert by_seq[9] == "recovery"
    assert by_seq[12] == "consolidation"
    assert by_seq[13] == "taper"


def test_weekly_shape(plan: dict) -> None:
    rows = build_plan_rows(plan)
    # Mon bodyweight + Tue/Wed/Thu + Sat/Sun = 6 rows/week x 13; Friday is rest.
    assert len(rows.workouts) == 78
    assert [w for w in rows.workouts if w.workout_date.weekday() == 4] == []
    wednesday = [w for w in rows.workouts if w.workout_date == date(2026, 7, 8)]
    assert len(wednesday) == 1
    assert wednesday[0].workout_type == "bike_endurance"
    # every workout hangs off a block that exists
    weeks = {b.sequence_index for b in rows.blocks}
    assert all(w.week in weeks for w in rows.workouts)


def test_field_bounds(plan: dict) -> None:
    rows = build_plan_rows(plan)
    assert all(len(w.title) <= 200 for w in rows.workouts)
    assert all(len(w.intensity_target) <= 120 for w in rows.workouts)
    assert all(len(b.name) <= 160 for b in rows.blocks)


def test_start_date_must_be_monday(plan: dict) -> None:
    with pytest.raises(ValueError, match="Monday"):
        build_plan_rows(plan, date(2026, 7, 7))  # a Tuesday


def test_override_start_reanchors(plan: dict) -> None:
    rows = build_plan_rows(plan, date(2026, 8, 3))  # a Monday
    assert rows.blocks[0].start_date == date(2026, 8, 3)
    assert rows.blocks[-1].start_date == date(2026, 8, 3) + timedelta(weeks=12)
    assert min(w.workout_date for w in rows.workouts) >= date(2026, 8, 3)
