"""Batch 364 — a morning with no overnight data still gets a cautious call.

On 1 Nov 2026 Garmin refused the app's login from 00:25 to 12:01 UTC. The pipeline would
not grade a morning without the night's Garmin rows (Decision #300), so nothing after
the gate ran: no call, no ride change, nothing on Home but "Something went wrong while
writing", and the coach told Mark to ride the 2-hour session as planned and that checking
in "may trigger that read" (CI359-01, AI358-01, UX362-01). A symptom tapped that day would
have started no follow-up, and a fever ended on the next morning's preselected "None"
(HS361-02).

The pure tests pin the calls and the chat's state; the Postgres ones replay the 1 Nov
shape through the real pipeline with the night's rows removed, and the days a symptom was
reported with no morning stored.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Analysis,
    BriefGenerationStatus,
    DailyMetric,
    Sleep,
    SymptomFollowUp,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.services import brief_chat
from src.services.brief_generation_status import STATUS_FAILED, STATUS_READY
from src.services.chat_context import (
    TODAYS_BRIEF_DID_NOT_FINISH,
    TODAYS_BRIEF_NOT_STARTED,
    TODAYS_BRIEF_WAITING_FOR_DATA,
    TODAYS_BRIEF_WRITING,
    TODAYS_BRIEF_WRITTEN,
    ChatContextService,
)
from src.services.graded_morning import brief_is_written
from src.services.morning_pipeline import (
    BACKSTOP_POLICY,
    CHECKIN_POLICY,
    RETRY_POLICY,
    MorningBriefPipeline,
)
from src.services.nudge_alerts import ANALYSIS_TYPE_CALL_READY
from src.services.recent_mornings import MorningCall
from src.services.symptom_check import (
    EASING_CHEST_FOLLOW_UP,
    EASING_FEVER_FOLLOW_UP,
    FEVER_FOLLOW_UP_ANSWER_LABELS,
    SYMPTOMS_CHEST_HEART,
    SYMPTOMS_FEVER_ACHES,
    FeverFollowUp,
    fever_follow_up_easing,
    fever_follow_up_line,
)
from src.services.todays_call import (
    FEVER_EASY_RIDING_ONLY_LINE,
    LIGHT_WEEK,
    NOT_ENOUGH_DATA,
    NOT_ENOUGH_DATA_HARD_LINE,
    NOT_ENOUGH_DATA_RIDE_LINE,
    READING_NOT_ENOUGH_DATA,
    READING_SOME_FATIGUE,
    REST_DAY,
    REST_DAY_NO_DATA_LINE,
    STATE_EASY_RIDING_ONLY,
    STATE_REST_NOT_ENOUGH_DATA,
    STATE_TEST_DAY,
    TEST_DAY_LINE,
    TEST_DAY_NO_DATA_LINE,
    todays_call,
)
from tests.test_batch_296_graded_colour import _seed_one_poor_night
from tests.test_batch_302_stored_morning import _RecordingClient, _savepoint_session
from tests.test_batch_303_medical_follow_through import _graded, _seed_good_days

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-11-02-batch-364-wording.md"
WEB_COPY = REPO / "apps" / "web" / "src" / "lib" / "copy.ts"
WEB_FEVER = REPO / "apps" / "web" / "src" / "lib" / "feverFollowUp.ts"

SEEDED_DAY = date(2026, 9, 7)


# -- the call on a morning without its night's data (364.1) -------------------------------


def _packet(
    status: str,
    sessions: list[dict[str, Any]],
    *,
    no_data: bool = True,
    rest: bool = False,
    easing: str | None = None,
) -> dict[str, Any]:
    planned = [
        {"id": str(index), "workoutType": item["workoutType"], "status": "planned"}
        for index, item in enumerate(sessions)
    ]
    actions = [
        {
            "plannedWorkoutId": str(index),
            "action": item["action"],
            "isHard": item.get("isHard", False),
            "isBike": item["workoutType"].startswith("bike"),
            "workoutType": item["workoutType"],
        }
        for index, item in enumerate(sessions)
    ]
    graded: dict[str, Any] = {"actions": actions, "missingDataFloorApplied": no_data}
    if easing is not None:
        graded["easing"] = easing
    packet: dict[str, Any] = {
        "plannedWorkouts": [] if rest else planned,
        "verdict": {"status": status, "engine": "graded", "acutePhysiology": {}, "graded": graded},
    }
    if rest:
        packet["restDay"] = {"isRestDay": True, "reason": "planned_rest", "insidePlanWeek": True}
    return packet


def test_every_kind_of_day_without_data_reads_not_enough_data_not_fatigue() -> None:
    """CI359-01's table, as the call reads it: never "Some fatigue" for a missing night."""
    hard = todays_call(
        _packet("Amber", [{"action": "ease_hard", "workoutType": "bike_vo2", "isHard": True}])
    )
    assert (hard.headline, hard.line, hard.reading) == (
        NOT_ENOUGH_DATA,
        NOT_ENOUGH_DATA_HARD_LINE,
        READING_NOT_ENOUGH_DATA,
    )
    long_ride = todays_call(
        _packet("Amber", [{"action": "as_planned", "workoutType": "bike_endurance"}])
    )
    assert long_ride.line == NOT_ENOUGH_DATA_RIDE_LINE  # Zone 2 as planned, easy start
    light_week = todays_call(
        _packet("Amber", [{"action": "hold_targets", "workoutType": "bike_vo2", "isHard": True}])
    )
    assert (light_week.headline, light_week.reading) == (LIGHT_WEEK, READING_NOT_ENOUGH_DATA)
    test_day = todays_call(
        _packet("Amber", [{"action": "move_test", "workoutType": "bike_test", "isHard": True}])
    )
    assert (test_day.state, test_day.line, test_day.reading) == (
        STATE_TEST_DAY,
        TEST_DAY_NO_DATA_LINE,
        READING_NOT_ENOUGH_DATA,
    )
    rest = todays_call(_packet("Amber", [], rest=True))
    assert (rest.state, rest.headline, rest.line, rest.reading) == (
        STATE_REST_NOT_ENOUGH_DATA,
        REST_DAY,
        REST_DAY_NO_DATA_LINE,
        READING_NOT_ENOUGH_DATA,
    )
    # A test on a morning with data but not fresh keeps its own words and reading.
    tired_test = todays_call(
        _packet(
            "Amber",
            [{"action": "move_test", "workoutType": "bike_test", "isHard": True}],
            no_data=False,
        )
    )
    assert (tired_test.line, tired_test.reading) == (TEST_DAY_LINE, READING_SOME_FATIGUE)


def test_an_open_fever_follow_up_with_nothing_hard_reads_easy_riding_only() -> None:
    call = todays_call(
        _packet(
            "Amber",
            [{"action": "mobility_instead", "workoutType": "strength"}],
            no_data=False,
            easing=EASING_FEVER_FOLLOW_UP,
        )
    )
    assert (call.state, call.line) == (STATE_EASY_RIDING_ONLY, FEVER_EASY_RIDING_ONLY_LINE)


# -- the pipeline: a code-only morning, and the brief once the data lands (364.1-.2) --------


async def _seed_outage_morning(session: AsyncSession) -> tuple[Profile, uuid.UUID]:
    """7 Sep's shape (a VO2 session, his check-in) with the night's Garmin rows gone."""
    user_id = uuid.uuid4()
    player = Profile(
        id=user_id,
        display_name=f"No Data {user_id.hex[:6]}",
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )
    session.add(player)
    await session.flush()
    vo2 = await _seed_one_poor_night(session, user_id, SEEDED_DAY)
    await session.flush()
    await session.execute(
        delete(DailyMetric).where(
            DailyMetric.user_id == user_id, DailyMetric.calendar_date == SEEDED_DAY
        )
    )
    await session.execute(
        delete(Sleep).where(Sleep.user_id == user_id, Sleep.calendar_date == SEEDED_DAY)
    )
    await session.commit()
    return player, vo2.id


def _is_morning(row: Any) -> bool:
    return bool(row.analysis_type == "morning")


async def _rows(session: AsyncSession, model: Any, user_id: uuid.UUID) -> list[Any]:
    rows = await session.execute(
        select(model).where(model.user_id == user_id).execution_options(populate_existing=True)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [BACKSTOP_POLICY, CHECKIN_POLICY])
async def test_on_postgres_a_morning_without_its_night_stores_a_careful_call_and_eases_the_vo2(
    db_conn: AsyncConnection, policy: Any
) -> None:
    """The acceptance case: 1 Nov's outage, replayed. On `main` this stored nothing."""
    async with _savepoint_session(db_conn) as session:
        player, vo2_id = await _seed_outage_morning(session)
        user_id = player.id
        client = _RecordingClient()

        outcome = await MorningBriefPipeline(session, policy=policy).generate_brief(
            player, SEEDED_DAY, client=client
        )

        assert client.calls == 0  # no paid brief without the night's data
        assert (outcome.code_only, outcome.inputs_not_ready) == (True, True)
        [stored] = [row for row in await _rows(session, Analysis, user_id) if _is_morning(row)]
        assert brief_is_written(stored) is False
        verdict = stored.context_packet["verdict"]
        assert verdict["status"] == "Amber"
        assert verdict["graded"]["missingDataFloorApplied"] is True
        assert verdict["acutePhysiology"]["dataSufficiency"]["missingRows"] == [
            "daily_metric",
            "sleep",
        ]
        assert "Insufficient data to judge today." in verdict["reasons"]
        [action] = verdict["graded"]["actions"]
        assert action["action"] == "ease_hard"
        call = stored.context_packet["todaysCall"]
        assert (call["key"], call["reading"]) == ("not_enough_data", READING_NOT_ENOUGH_DATA)

        # Stage 2 offered the eased ride for Zwift, as on any Amber morning (364.2).
        [proposal] = await _rows(session, WorkoutDeliveryProposal, user_id)
        assert proposal.planned_workout_id == vo2_id
        assert proposal.status == "proposed"
        assert proposal.structured_workout_ir["adjustment"]["changed"] is True

        # Home is told why, and he is told the call is there.
        [status] = await _rows(session, BriefGenerationStatus, user_id)
        assert (status.status, status.reason) == (STATUS_FAILED, "inputs")
        assert outcome.call_ready_pushes == 1
        pushes = [
            row.analysis_type
            for row in await _rows(session, Analysis, user_id)
            if row.analysis_type == ANALYSIS_TYPE_CALL_READY
        ]
        assert pushes == [ANALYSIS_TYPE_CALL_READY]


@pytest.mark.asyncio
async def test_on_postgres_try_again_after_the_data_lands_regrades_and_writes_the_brief(
    db_conn: AsyncConnection,
) -> None:
    async with _savepoint_session(db_conn) as session:
        player, _vo2_id = await _seed_outage_morning(session)
        user_id = player.id
        await MorningBriefPipeline(session, policy=CHECKIN_POLICY).generate_brief(
            player, SEEDED_DAY, client=_RecordingClient()
        )
        # A retry while Garmin is still refusing regrades nothing and pays for nothing.
        still_down = _RecordingClient()
        again = await MorningBriefPipeline(session, policy=RETRY_POLICY).generate_brief(
            player, SEEDED_DAY, client=still_down
        )
        assert (again.code_only, still_down.calls) == (True, 0)
        mornings = [row for row in await _rows(session, Analysis, user_id) if _is_morning(row)]
        assert len(mornings) == 1

        # The night lands; "Try again" grades the real morning and writes its brief.
        session.add_all(
            [
                DailyMetric(
                    user_id=user_id,
                    calendar_date=SEEDED_DAY,
                    phase="morning",
                    recorded_at_utc=datetime(2026, 9, 7, 6, 0),
                    readiness_score=70,
                    readiness_level="HIGH",
                    hrv_last_night_avg_ms=47,
                    hrv_weekly_avg_ms=47,
                    hrv_status="BALANCED",
                    resting_heart_rate_bpm=45,
                    raw_payload={},
                ),
                Sleep(
                    user_id=user_id,
                    calendar_date=SEEDED_DAY,
                    score=80,
                    duration_sec=450 * 60,
                    raw_payload={},
                    factors_json={},
                ),
            ]
        )
        await session.commit()
        client = _RecordingClient(markdown="**Today's call:** Green light.")
        outcome = await MorningBriefPipeline(session, policy=RETRY_POLICY).generate_brief(
            player, SEEDED_DAY, client=client
        )
        assert (outcome.code_only, outcome.generated, client.calls) == (False, True, 1)
        mornings = [row for row in await _rows(session, Analysis, user_id) if _is_morning(row)]
        latest = max(mornings, key=lambda row: row.generated_at_utc)
        assert brief_is_written(latest)
        assert latest.context_packet["verdict"]["graded"]["missingDataFloorApplied"] is False
        [status] = await _rows(session, BriefGenerationStatus, user_id)
        assert status.status == STATUS_READY


# -- what follows a symptom on a day no morning was stored (364.5) --------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "kind", "record"),
    [
        (SYMPTOMS_CHEST_HEART, EASING_CHEST_FOLLOW_UP, "chestFollowUp"),
        (SYMPTOMS_FEVER_ACHES, EASING_FEVER_FOLLOW_UP, "feverFollowUp"),
    ],
)
async def test_on_postgres_a_symptom_on_a_day_with_no_stored_morning_starts_its_follow_up(
    db_conn: AsyncConnection, answer: str, kind: str, record: str
) -> None:
    """HS361-02, proved: before this batch the next morning's follow-up returned None."""
    reported = date(2026, 8, 18)
    async with _savepoint_session(db_conn) as session:
        player, entries, _rides = await _seed_good_days(session, reported - timedelta(1), 3)
        await _graded(session, player, reported - timedelta(1))
        entries[reported].symptoms = answer
        await session.commit()
        # No morning is stored for the day he reported it: its grading never ran.

        next_day = await _graded(session, player, reported + timedelta(1))
        symptoms = next_day["acutePhysiology"]["symptoms"]
        assert symptoms["easing"]["kind"] == kind
        assert symptoms[record] == {
            "reportedOn": reported.isoformat(),
            "answer": None,
            "open": True,
        }
        [ride] = next_day["graded"]["actions"]
        assert ride["action"] == "recovery"


@pytest.mark.asyncio
async def test_on_postgres_still_there_on_a_day_with_no_stored_morning_seeds_too(
    db_conn: AsyncConnection,
) -> None:
    reported = date(2026, 8, 18)
    async with _savepoint_session(db_conn) as session:
        player, _entries, _rides = await _seed_good_days(session, reported - timedelta(1), 3)
        await _graded(session, player, reported - timedelta(1))
        session.add(
            SymptomFollowUp(
                user_id=player.id,
                subject_date=reported,
                reported_on=reported - timedelta(3),
                kind="fever_aches",
                answer="still_there",
                answered_at_utc=datetime(2026, 8, 18, 8, 0),
            )
        )
        await session.commit()
        next_day = await _graded(session, player, reported + timedelta(1))
        assert next_day["acutePhysiology"]["symptoms"]["feverFollowUp"]["reportedOn"] == (
            reported.isoformat()
        )


# -- the coach sees the morning's state (364.4) ---------------------------------------------


def _status_row(status: str, reason: str | None) -> MagicMock:
    return MagicMock(status=status, reason=reason, updated_at=datetime(2026, 11, 1, 9, 46))


def _call_today(day: date) -> MorningCall:
    return MorningCall(
        subject_date=day,
        generated_at_utc=datetime(2026, 11, 1, 9, 46),
        verdict="Amber",
        reasons=[],
        verdict_adjustment=None,
        requires_bike_rest=False,
        rest_day=None,
        planned_workouts=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "called", "state"),
    [
        (_status_row("failed", "inputs"), True, TODAYS_BRIEF_WAITING_FOR_DATA),
        (_status_row("failed", "billing"), True, TODAYS_BRIEF_DID_NOT_FINISH),
        (_status_row("generating", None), True, TODAYS_BRIEF_WRITING),
        (_status_row("ready", None), True, TODAYS_BRIEF_WRITTEN),
        (None, False, TODAYS_BRIEF_NOT_STARTED),
        (None, True, TODAYS_BRIEF_WRITTEN),
    ],
)
async def test_the_coach_is_told_where_todays_brief_is(
    row: MagicMock | None, called: bool, state: str
) -> None:
    today = date(2026, 11, 1)
    builder = ChatContextService(AsyncMock())
    with patch(
        "src.services.chat_context.BriefGenerationStatusService.get",
        AsyncMock(return_value=row),
    ):
        brief = await builder._todays_brief(
            uuid.uuid4(), today, [_call_today(today)] if called else []
        )
    assert brief["state"] == state
    assert "checking in again will not bring the data" in brief["meaning"]


def test_the_coach_is_told_never_to_promise_the_check_in_brings_the_read() -> None:
    assert brief_chat.NO_DATA_MORNING_RULE in brief_chat.SYSTEM_PROMPT
    assert "never tell him that checking in" in brief_chat.NO_DATA_MORNING_RULE
    assert brief_chat.PROMPT_VERSION == "coach-chat-v32-2026-11-08"


# -- every Mark-facing line is in the draft Craig signs off (364.6) -------------------------


def _draft() -> str:
    text = DRAFT.read_text(encoding="utf-8")
    return " ".join(text.replace("\n> ", " ").replace("**", "").split())


def test_every_new_line_is_in_the_draft() -> None:
    draft = _draft()
    weekday_line = FeverFollowUp(reported_on=date(2026, 10, 8))
    for words in (
        NOT_ENOUGH_DATA_RIDE_LINE,
        TEST_DAY_NO_DATA_LINE,
        REST_DAY_NO_DATA_LINE,
        FEVER_EASY_RIDING_ONLY_LINE,
        fever_follow_up_line(weekday_line.reported_on),
        fever_follow_up_easing(weekday_line)["notice"],
        *FEVER_FOLLOW_UP_ANSWER_LABELS.values(),
    ):
        assert " ".join(words.split()) in draft, words


def test_homes_words_are_the_drafts_and_the_fever_buttons_match_the_server() -> None:
    draft = _draft()
    copy = WEB_COPY.read_text(encoding="utf-8")
    for name in (
        "BRIEF_NO_DATA_TITLE",
        "BRIEF_NO_DATA_LINE",
        "BRIEF_NO_DATA_CHECKIN_LINE",
        "BRIEF_NO_DATA_TOAST",
        "BRIEF_NO_DATA_NO_CALL_LINE",
    ):
        start = copy.index(f"export const {name} =")
        value = copy[start:].split("=", 1)[1].split(";", 1)[0].strip()
        words = value.strip().strip("'\"")
        assert " ".join(words.split()) in draft, name
    fever = WEB_FEVER.read_text(encoding="utf-8")
    for label in FEVER_FOLLOW_UP_ANSWER_LABELS.values():
        assert label in fever
