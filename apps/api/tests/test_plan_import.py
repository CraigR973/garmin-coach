"""Tests for the training-plan importer (DECISIONS #102, #138).

Pure ``build_plan_rows`` mapping (no DB) plus a DB-backed ``import_plan`` test,
validated against the committed reviewed plan
(``apps/api/data/plans/plan_no2.json``):
  1. 13 Monday-anchored blocks with sequential weekly dates.
  2. Block types match the 2121-ish structure (recovery / consolidation / taper).
  3. Weekly shape: Friday is rest (no row); Wednesday is a Z2 endurance ride.
  4. Start date must be a Monday; an override re-anchors the whole plan.
  5. Batch 65: Mondays are the Dumbbell (weights) session, build-week Saturdays
     split into a ride + a Bodyweight strength row, and ``import_plan`` assigns
     per-date versions so the split day satisfies the unique constraint.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.plan_import import build_plan_rows, import_plan
from src.services.workout_categories import category_for_workout_type

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
    # Dumbbells Mon + Tue/Wed/Thu + Sat + Sun = 6 rows/week; Friday is rest. Each of
    # the 9 build weeks adds a second Saturday entry (the split Bodyweight strength),
    # so 9*7 + 4*6 = 87 (Batch 65).
    assert len(rows.workouts) == 87
    assert [w for w in rows.workouts if w.workout_date.weekday() == 4] == []
    wednesday = [w for w in rows.workouts if w.workout_date == date(2026, 7, 8)]
    assert len(wednesday) == 1
    assert wednesday[0].workout_type == "bike_endurance"
    # every workout hangs off a block that exists
    weeks = {b.sequence_index for b in rows.blocks}
    assert all(w.week in weeks for w in rows.workouts)


def test_dumbbell_mondays_and_split_saturdays(plan: dict) -> None:
    """Batch 65: every Monday is the Dumbbell (weights) session, and build-week
    Saturdays carry two rows — the ride first (v1 at import) then the Bodyweight
    strength — while recovery/consolidation/taper Saturdays stay a single ride."""
    rows = build_plan_rows(plan)

    mondays = [w for w in rows.workouts if w.workout_date.weekday() == 0]
    assert len(mondays) == 13
    assert all(category_for_workout_type(w.workout_type) == "weights" for w in mondays)
    assert all("Dumbbell" in w.title for w in mondays)

    saturdays: dict[date, list] = {}
    for w in rows.workouts:
        if w.workout_date.weekday() == 5:
            saturdays.setdefault(w.workout_date, []).append(w)
    split = {d: ws for d, ws in saturdays.items() if len(ws) == 2}
    single = {d: ws for d, ws in saturdays.items() if len(ws) == 1}
    assert len(split) == 9 and len(single) == 4

    for ride, strength in split.values():
        # Row order is preserved from the JSON: ride first, strength second.
        assert category_for_workout_type(ride.workout_type) == "cycle"
        assert category_for_workout_type(strength.workout_type) == "weights"
        assert ride.title == "Z2 + Neuromuscular"
        assert strength.title == "Bodyweight"
        # The welded "Then: 20min dumbbells" tail is gone from the ride summary.
        assert "dumbbell" not in str(ride.structured_workout.get("summary", "")).lower()
    for ws in single.values():
        assert category_for_workout_type(ws[0].workout_type) == "cycle"


@pytest.mark.asyncio
async def test_import_plan_assigns_per_date_versions(db_conn: AsyncConnection, plan: dict) -> None:
    """Batch 65: ``import_plan`` versions same-day rows (ride v1, strength v2) so a
    split Saturday satisfies uq_planned_workouts_user_date_version, and a re-import
    lands on the same versions with no unique-constraint violation."""
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Import Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        summary = await import_plan(session, user_id, plan, dry_run=False)
    assert summary.workouts_inserted == 87

    monday, saturday = date(2026, 7, 6), date(2026, 7, 11)  # W1 Mon (start) + Sat

    async def _rows_on(session: AsyncSession, day: date) -> list[PlannedWorkout]:
        return list(
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == day,
                        PlannedWorkout.is_active.is_(True),
                    )
                    .order_by(PlannedWorkout.version)
                )
            )
            .scalars()
            .all()
        )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        sat_rows = await _rows_on(session, saturday)
        mon_rows = await _rows_on(session, monday)

    assert [w.version for w in sat_rows] == [1, 2]
    assert sat_rows[0].workout_type == "bike_endurance"  # ride = v1
    assert category_for_workout_type(sat_rows[1].workout_type) == "weights"  # strength = v2
    assert [w.version for w in mon_rows] == [1]
    assert category_for_workout_type(mon_rows[0].workout_type) == "weights"

    # A second import clears the forward schedule and re-lands on the same versions.
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        await import_plan(session, user_id, plan, dry_run=False)
        again = await _rows_on(session, saturday)
    assert [w.version for w in again] == [1, 2]


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
