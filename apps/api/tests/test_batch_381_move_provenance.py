"""Batch 381 — a moved session says who moved it and why.

379's case #33: on 2 Nov 2026 Craig moved ten Dumbbells A rows to Thursdays by running
``swap_day`` in the api container. ``swap_day`` stamped every move ``today_card_swap``,
so the coach told Mark the record showed his own Today-card move with no reason logged.

Who moved a session now lives in the row's ``source`` (``today_card_swap`` for Mark,
``operator_move`` for Craig) and why lives in the move's own audit row. Every figure,
date and word below is invented.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, PlannedWorkout
from src.models.profile import Profile
from src.services.chat_context import MOVED_SESSION_MEANING, TODAY_PLANNED_WORKOUTS_MEANING
from src.services.coach_policy import internal_vocabulary_hits, source_basis
from src.services.coach_tools import CoachToolbox
from src.services.executable_coaching import ExecutableCoachingService
from src.services.move_provenance import (
    MOVE_REASON_MAX_CHARS,
    MOVED_BY_OPERATOR,
    MOVED_BY_OWNER,
    OPERATOR_MOVE_SOURCE,
    OWNER_MOVE,
    OWNER_MOVE_SOURCE,
    move_reasons,
    move_reasons_for,
    operator_move,
)
from src.services.training_week import TrainingWeekService, build_training_week_packet
from src.services.weekly_restructure import RESTRUCTURE_SOURCE, WeeklyRestructureService
from src.tools import move_provenance as tool
from tests.test_executable_coaching import _FakeIntervalsClient, _seed_profile
from tests.test_weekly_restructure import (
    _ENDURANCE,
    _SWEET,
    _VO2,
    SAT,
    TUE,
    WED,
    WEEK_START,
    _planned,
)
from tests.test_weekly_restructure import _FakeIntervalsClient as _RestructureIntervals

REASON = "Craig moved the legs session so it sits after the long ride (invented reason)."
MONDAY, THURSDAY, FRIDAY = date(2026, 7, 13), date(2026, 7, 16), date(2026, 7, 17)


def _strength(
    user_id: uuid.UUID, day: date, *, title: str = "Dumbbells A (legs)"
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=user_id,
        workout_date=day,
        version=1,
        title=title,
        workout_type="strength_maintenance",
        status="planned",
        is_active=True,
        planned_duration_min=30,
        intensity_target="Dumbbells 3 × 8",
        structured_workout={"summary": "Split squat 3 × 8; row 3 × 8 (invented)."},
        source="plan_no2_import",
    )


def _audit(
    user_id: uuid.UUID,
    workout_id: uuid.UUID,
    *,
    at: datetime,
    subject: date,
    extra: dict | None = None,
) -> Analysis:
    return Analysis(
        user_id=user_id,
        activity_id=None,
        analysis_type="workout_moved",
        subject_date=subject,
        generated_at_utc=at,
        prompt_version="executable-coaching:v1",
        model_name=None,
        verdict=None,
        context_packet={
            "tag": f"swap:{uuid.uuid4()}:{subject.isoformat()}",
            "status": "moved",
            "intervalsEventId": None,
            "plannedWorkoutId": str(workout_id),
            "plannedWorkoutVersion": 2,
            **(extra or {}),
        },
        output_markdown="Moved Dumbbells A.",
        raw_response={},
    )


# ---------------------------------------------------------------------------
# The provenance itself
# ---------------------------------------------------------------------------


def test_marks_moves_keep_their_label_and_craigs_get_their_own() -> None:
    assert OWNER_MOVE.source == OWNER_MOVE_SOURCE == "today_card_swap"
    assert OWNER_MOVE.audit_fields() == {"movedBy": MOVED_BY_OWNER}
    craig = operator_move(REASON)
    assert craig.source == OPERATOR_MOVE_SOURCE == "operator_move"
    assert craig.audit_fields() == {"movedBy": MOVED_BY_OPERATOR, "reason": REASON}


@pytest.mark.parametrize("reason", ["", "   ", "x" * (MOVE_REASON_MAX_CHARS + 1)])
def test_a_move_craig_makes_must_say_why_in_one_short_sentence(reason: str) -> None:
    with pytest.raises(ValueError):
        operator_move(reason)


def test_both_labels_read_as_plain_words_the_coach_may_say() -> None:
    assert source_basis(OWNER_MOVE_SOURCE) == "moved to this day from the app's Today card"
    assert source_basis(OPERATOR_MOVE_SOURCE) == "moved to this day by Craig, not by you"
    for words in (tool.NOV_2_REASON, MOVED_SESSION_MEANING):
        assert internal_vocabulary_hits(words) == (), words
        assert "_" not in words
    assert len(tool.NOV_2_REASON) <= MOVE_REASON_MAX_CHARS
    # The exact words Craig signed off on 9 Nov (Decision #489).
    assert tool.NOV_2_REASON == (
        "Craig moved Dumbbells A from Mondays to Thursdays for this plan, so it no longer "
        "falls the day before Tuesday's VO₂ session; on Thursday it comes after the "
        "sweet-spot ride and 48 hours before Saturday's ride."
    )
    assert MOVED_SESSION_MEANING in TODAY_PLANNED_WORKOUTS_MEANING


def test_a_reason_belongs_to_the_rows_the_move_produced_and_a_later_own_move_drops_it() -> None:
    user_id, moved, partner, mine = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first = datetime(2026, 7, 10, 9, 0)
    audits = [
        _audit(
            user_id,
            moved,
            at=first,
            subject=MONDAY,
            extra={
                "movedBy": "operator",
                "reason": REASON,
                "swappedPlannedWorkoutId": str(partner),
            },
        ),
        _audit(user_id, mine, at=first + timedelta(hours=1), subject=THURSDAY),
        # A later move of the partner row itself, made by Mark, carries no reason.
        _audit(
            user_id,
            uuid.uuid4(),
            at=first + timedelta(hours=2),
            subject=MONDAY,
            extra={"movedBy": "owner", "swappedPlannedWorkoutId": str(partner)},
        ),
    ]
    for audit in audits:
        audit.created_at = audit.generated_at_utc
    assert move_reasons(audits) == {moved: REASON}


def test_only_the_chat_is_told_why_so_the_morning_packet_keeps_its_shape() -> None:
    user_id = uuid.uuid4()
    row = _strength(user_id, THURSDAY)
    row.source = OPERATOR_MOVE_SOURCE
    audit = _audit(
        user_id,
        row.id,
        at=datetime(2026, 7, 10, 9, 0),
        subject=MONDAY,
        extra={"movedBy": "operator", "reason": REASON},
    )
    audit.created_at = audit.generated_at_utc

    def build(*, chat: bool) -> dict:
        return build_training_week_packet(
            start_date=MONDAY,
            end_date=MONDAY + timedelta(days=6),
            timezone_name="Europe/London",
            planned_workouts=[row],
            action_audits=[audit],
            activities=[],
            workouts_by_id={row.id: row},
            subject_date=MONDAY,
            planned_contents=chat,
        )

    [chat_row] = build(chat=True)["days"][3]["planned"]
    [morning_row] = build(chat=False)["days"][3]["planned"]
    assert chat_row["basis"] == morning_row["basis"] == "moved to this day by Craig, not by you"
    assert chat_row["moveReason"] == REASON
    assert "moveReason" not in morning_row
    assert set(chat_row) - set(morning_row) == {"contents", "moveReason"}


# ---------------------------------------------------------------------------
# Each move path, on Postgres
# ---------------------------------------------------------------------------


async def _planned_lookup(session: AsyncSession, user: Profile, start: date, end: date) -> list:
    payload = json.loads(
        await CoachToolbox(session, user).planned_workouts(
            {"startDate": start.isoformat(), "endDate": end.isoformat()}
        )
    )
    assert "moveReason, when present, is why Craig moved it" in payload["meaning"]
    return payload["rows"]


async def _move_audits(session: AsyncSession, user_id: uuid.UUID) -> list[Analysis]:
    return list(
        (
            await session.execute(
                select(Analysis)
                .where(Analysis.user_id == user_id, Analysis.analysis_type == "workout_moved")
                .order_by(Analysis.generated_at_utc)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_marks_own_move_is_his_and_records_no_reason(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    row = _strength(user_id, MONDAY)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(row)
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        moved = await ExecutableCoachingService(
            session, intervals_client=_FakeIntervalsClient()
        ).swap_day(user, planned_workout_id=row.id, target_date=THURSDAY)

        assert moved.source == "today_card_swap"
        [audit] = await _move_audits(session, user_id)
        assert audit.context_packet["movedBy"] == "owner"
        assert "reason" not in audit.context_packet
        [looked_up] = await _planned_lookup(session, user, THURSDAY, THURSDAY)
        assert looked_up["basis"] == "moved to this day from the app's Today card"
        assert "moveReason" not in looked_up


@pytest.mark.asyncio
async def test_craigs_swap_labels_both_rows_and_the_coach_can_quote_why(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    a_row = _strength(user_id, MONDAY)
    b_row = _strength(user_id, THURSDAY, title="Dumbbells B (upper)")
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([a_row, b_row])
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        await ExecutableCoachingService(session, intervals_client=_FakeIntervalsClient()).swap_day(
            user,
            planned_workout_id=a_row.id,
            target_date=THURSDAY,
            provenance=operator_move(REASON),
        )

        rows = await _planned_lookup(session, user, MONDAY, THURSDAY)
        by_title = {row["title"]: row for row in rows}
        assert {row["workoutDate"] for row in rows} == {MONDAY.isoformat(), THURSDAY.isoformat()}
        for title in ("Dumbbells A (legs)", "Dumbbells B (upper)"):
            assert by_title[title]["basis"] == "moved to this day by Craig, not by you"
            assert by_title[title]["moveReason"] == REASON
        [audit] = await _move_audits(session, user_id)
        assert audit.context_packet["movedBy"] == "operator"
        assert audit.context_packet["reason"] == REASON
        assert audit.context_packet["swappedPlannedWorkoutId"]

        week = await TrainingWeekService(session).build_window(
            user,
            start_date=MONDAY,
            end_date=MONDAY + timedelta(days=6),
            subject_date=MONDAY,
            window_kind="week_ahead_from_today",
            planned_contents=True,
        )
        [thursday] = week["days"][3]["planned"]
        assert thursday["moveReason"] == REASON


@pytest.mark.asyncio
async def test_mark_moving_craigs_session_again_makes_it_his(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    row = _strength(user_id, MONDAY)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(row)
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=_FakeIntervalsClient())
        by_craig = await service.swap_day(
            user, planned_workout_id=row.id, target_date=THURSDAY, provenance=operator_move(REASON)
        )
        by_mark = await service.swap_day(user, planned_workout_id=by_craig.id, target_date=FRIDAY)

        assert by_mark.source == "today_card_swap"
        assert await move_reasons_for(session, user_id, [by_mark.id, by_craig.id]) == {
            by_craig.id: REASON
        }
        [looked_up] = await _planned_lookup(session, user, MONDAY, FRIDAY)
        assert looked_up["workoutDate"] == FRIDAY.isoformat()
        assert "moveReason" not in looked_up


@pytest.mark.asyncio
async def test_a_restructure_keeps_its_own_label_and_no_reason(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    rows = [
        _planned(user_id, TUE, "bike_vo2", "VO2 Max 30/30", _VO2),
        _planned(user_id, WED, "bike_sweet_spot", "Sweet Spot Builder", _SWEET),
        _planned(user_id, SAT, "bike_endurance", "Long Endurance Ride", _ENDURANCE),
    ]
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(rows)
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        result = await WeeklyRestructureService(
            session, intervals_client=_RestructureIntervals()
        ).apply_for_week(user, WEEK_START, as_of=TUE)
        assert result.versioned_workouts
        assert {row.source for row in result.versioned_workouts} == {RESTRUCTURE_SOURCE}
        looked_up = await _planned_lookup(session, user, WEEK_START, WEEK_START + timedelta(days=6))
        moved = [
            row for row in looked_up if row.get("basis") == "moved when the week was rearranged"
        ]
        assert moved
        assert all("moveReason" not in row for row in looked_up)


# ---------------------------------------------------------------------------
# The 2 Nov correction
# ---------------------------------------------------------------------------


async def _seed_nov_2(db_conn: AsyncConnection, user_id: uuid.UUID, rows: int) -> dict:
    """``rows`` operator moves at 13:00 on 2 Nov, plus Mark's move back of the first."""
    await _seed_profile(db_conn, user_id)
    seeded: dict = {"operator": [], "audits": []}
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for week in range(rows + 1):
            monday = date(2026, 11, 9) + timedelta(weeks=week)
            thursday = monday + timedelta(days=3)
            row = _strength(user_id, thursday, title="Dumbbells A (legs and back)")
            row.version, row.source = 2, "today_card_swap"
            session.add(row)
            await session.flush()
            audit = _audit(
                user_id,
                row.id,
                at=datetime(2026, 11, 2, 13, 0, 9 + 2 * week),
                subject=monday,
            )
            session.add(audit)
            seeded["operator"].append(row)
            seeded["audits"].append(audit)
        # Mark moved the first one back himself at 16:05; his move is left alone.
        first = seeded["operator"][0]
        first.is_active = False
        back = _strength(user_id, date(2026, 11, 9), title="Dumbbells A (legs and back)")
        back.version, back.source = 2, "today_card_swap"
        session.add(back)
        await session.flush()
        session.add(
            _audit(
                user_id, back.id, at=datetime(2026, 11, 2, 16, 5, 24), subject=first.workout_date
            )
        )
        seeded["mark"] = back
        await session.commit()
    return seeded


@pytest.mark.asyncio
async def test_the_dry_run_lists_only_the_still_mislabelled_rows(db_conn: AsyncConnection) -> None:
    seeded = await _seed_nov_2(db_conn, uuid.uuid4(), rows=9)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        report = await tool.correct_nov_2(session, commit=False)
    assert report["dryRun"] is True
    assert report["found"] == 9
    listed = [row["plannedWorkoutId"] for row in report["rows"]]
    assert listed == [str(row.id) for row in seeded["operator"][1:]]
    assert str(seeded["mark"].id) not in listed
    assert all(
        row["weekday"] == "Thu" and row["oldSource"] == "today_card_swap" for row in report["rows"]
    )


@pytest.mark.asyncio
async def test_the_write_refuses_anything_but_exactly_the_listed_rows(
    db_conn: AsyncConnection,
) -> None:
    seeded = await _seed_nov_2(db_conn, uuid.uuid4(), rows=8)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        with pytest.raises(SystemExit, match="found 8 rows"):
            await tool.correct_nov_2(
                session, commit=True, expected_ids={row.id for row in seeded["operator"][1:]}
            )


@pytest.mark.asyncio
async def test_the_write_needs_the_listed_ids(db_conn: AsyncConnection) -> None:
    await _seed_nov_2(db_conn, uuid.uuid4(), rows=9)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        with pytest.raises(SystemExit, match="expect-ids"):
            await tool.correct_nov_2(session, commit=True)
        with pytest.raises(SystemExit, match="not the rows listed"):
            await tool.correct_nov_2(session, commit=True, expected_ids={uuid.uuid4()})


@pytest.mark.asyncio
async def test_the_write_relabels_the_nine_leaves_marks_move_and_can_be_undone(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    seeded = await _seed_nov_2(db_conn, user_id, rows=9)
    targets = seeded["operator"][1:]
    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        report = await tool.correct_nov_2(
            session, commit=True, expected_ids={row.id for row in targets}
        )
        assert report["written"] == 9

        user = await session.get(Profile, user_id)
        assert user is not None
        looked_up = await _planned_lookup(session, user, date(2026, 11, 9), date(2027, 1, 31))
        by_id = {row["id"]: row for row in looked_up}
        for row in targets:
            assert by_id[str(row.id)]["basis"] == "moved to this day by Craig, not by you"
            assert by_id[str(row.id)]["moveReason"] == tool.NOV_2_REASON
            assert by_id[str(row.id)]["workoutDate"] == row.workout_date.isoformat()
        mark = by_id[str(seeded["mark"].id)]
        assert mark["basis"] == "moved to this day from the app's Today card"
        assert "moveReason" not in mark
        audit = await session.get(Analysis, seeded["audits"][1].id)
        assert audit is not None
        assert audit.context_packet["provenanceCorrection"]["previousSource"] == "today_card_swap"

        assert await tool.undo_nov_2(session, report) == 9
        for row in targets:
            restored = await session.get(PlannedWorkout, row.id)
            assert restored is not None and restored.source == "today_card_swap"
        restored_audit = await session.get(Analysis, seeded["audits"][1].id)
        assert restored_audit is not None
        assert "reason" not in restored_audit.context_packet
