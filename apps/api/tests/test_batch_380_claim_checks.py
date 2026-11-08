"""Batch 380 — the coach checks a claim before it states it.

Batch 379's review of the live coach found three kinds of unchecked claim on chat v31,
each inside an answer whose core figures were right:

* **a stretch** — that his recovery had stayed in his usual range across six weeks, said
  from monthly means while several mornings in that stretch were outside it;
* **a phase or a session** — a week of his plan, and what a session was, named from his
  weekly rhythm rather than the record of that week or that day;
* **a platform's mechanism** — an invented account of how Garmin scores a workout.

The fix is one prompt rule (``CHECKED_CLAIM_RULE``, restated in the closing reply rule)
plus the two records the first two claims needed and the coach did not hold: six weeks of
dated wake readings (``recoveryDays``) and his plan's weeks by name and type
(``planWeeks``, and ``planWeek`` on each planned-workouts lookup row).

Every question, name and figure here is invented. The real cases stay in the review's
git-ignored private evidence.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DAILY_METRIC_PHASE_SETTLED,
    DailyMetric,
    PlanBlock,
    PlannedWorkout,
)
from src.models.profile import Profile, UserRole
from src.services import brief_chat
from src.services.chat_context import (
    _DROP_ORDER,
    _FETCHABLE_OMISSIONS,
    APP_STATE_CHAR_BUDGET,
    CHECKABLE_STRETCH_DAYS,
    PLAN_WEEKS_MEANING,
    RECOVERY_DAY_COLUMNS,
    RECOVERY_DAYS_MEANING,
    ChatContextService,
    _apply_char_budget,
    app_state_length,
)
from src.services.coach_policy import (
    GROUNDING_RULE,
    PROPOSE_CONFIRM_RULE,
    RECORD_CONTRADICTION_RULE,
    SYMPTOM_RULE,
    floors_sentence,
)
from src.services.coach_tools import (
    COACH_TOOLS,
    MAX_RESULT_CHARS,
    TOOL_NAMES,
    CoachToolbox,
    _daily_metric_state,
    _result,
)
from src.services.plan_weeks import plan_week_on, plan_week_state
from src.services.prompt_artifacts import PROMPT_ARTIFACTS, RegenerationContract

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-11-08-batch-380-wording.md"

#: An invented Sunday: the six weeks before it and the week after.
TODAY = date(2026, 3, 15)
ASKED_AT = datetime(2026, 3, 15, 10, 0)


def _tool(name: str) -> dict[str, Any]:
    (tool,) = [tool for tool in COACH_TOOLS if tool["name"] == name]
    return tool


def _block(
    name: str, block_type: str, start: date, *, version: int = 1, days: int = 7
) -> PlanBlock:
    return PlanBlock(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name=name,
        version=version,
        block_type=block_type,
        start_date=start,
        end_date=start + timedelta(days=days - 1),
        goals_json={},
        raw_plan={},
    )


# -- the rule (380.2) ------------------------------------------------------------------


def test_the_version_moves_and_withdraws_nothing() -> None:
    """380.3: a new chat version; chat turns are UNFILTERED, so no answer is withdrawn."""
    assert brief_chat.PROMPT_VERSION == "coach-chat-v32-2026-11-08"
    (artifact,) = [row for row in PROMPT_ARTIFACTS if row.module == "brief_chat"]
    assert artifact.contract is RegenerationContract.UNFILTERED
    assert artifact.analysis_types == ()


def test_the_rule_is_in_the_prompt_after_the_record_rule() -> None:
    prompt = brief_chat.SYSTEM_PROMPT
    assert brief_chat.CHECKED_CLAIM_RULE in prompt
    assert prompt.index(RECORD_CONTRADICTION_RULE) < prompt.index(brief_chat.CHECKED_CLAIM_RULE)


def test_a_stretch_claim_is_checked_day_by_day_not_from_an_average() -> None:
    """Claim type 1: 'your readings stayed in range for six weeks', from a mean."""
    rule = " ".join(brief_chat.CHECKED_CLAIM_RULE.split())
    assert "An average or a trend describes a stretch as a whole, never each day in it" in rule
    assert "read its days in recoveryDays or look them up" in rule
    assert "say how many and when" in rule
    assert "say in a few words what you checked" in rule


def test_a_phase_or_session_claim_comes_from_its_own_record() -> None:
    """Claim type 2: a week's phase, and what a session was, from the weekly rhythm."""
    rule = " ".join(brief_chat.CHECKED_CLAIM_RULE.split())
    assert "Name a week's phase only from planWeeks or a session's planWeek" in rule
    assert "never from his weekly rhythm" in rule
    assert "only from its own record for that date" in rule
    assert "never from the day of the week it fell on" in rule


def test_a_platform_mechanism_is_general_knowledge_or_unknown_never_fact() -> None:
    """Claim type 3: how Garmin scores a workout, invented and stated as fact."""
    rule = " ".join(brief_chat.CHECKED_CLAIM_RULE.split())
    assert "How Garmin, his watch or the app works a figure out" in rule
    assert "say it is general knowledge, or that you do not know" in rule
    assert "never present it as fact" in rule
    assert "If you have not checked a claim, leave it out or say that you have not" in rule


def test_the_closing_reply_rule_restates_it() -> None:
    final = brief_chat.FINAL_REPLY_RULE
    assert "Check a claim about a stretch of days, a phase of his plan or what a session" in final
    assert "an average never shows that every day stayed in range" in final
    assert "only as general knowledge, or say you do not know" in final


def test_the_closed_list_of_what_the_coach_holds_names_both_records() -> None:
    """Batch 289's lesson: the enumeration is closed, so a section it omits reads as absent."""
    prompt = " ".join(brief_chat.SYSTEM_PROMPT.split())
    assert "the weeks of his plan by name and type from six weeks back" in prompt
    assert "his Garmin wake readings for each morning of the last six weeks" in prompt


def test_no_rule_of_the_call_changes() -> None:
    """380.2: floors, guards, pass-on and propose/approve are unchanged and still composed."""
    prompt = brief_chat.SYSTEM_PROMPT
    for rule in (GROUNDING_RULE, PROPOSE_CONFIRM_RULE, SYMPTOM_RULE, floors_sentence()):
        assert rule in prompt
    assert "never invent a mechanism for how the app reached a figure" in prompt
    assert "Answer his question in the first sentence" in prompt
    assert "keep under 100 unless he explicitly" in " ".join(prompt.split())


def test_the_rule_and_the_new_record_meanings_are_in_the_draft_craig_signs_off() -> None:
    """380.3: the exact words are in the sanitised draft."""
    draft = " ".join(DRAFT.read_text(encoding="utf-8").replace("\n> ", " ").split())
    for words in (
        brief_chat.CHECKED_CLAIM_RULE,
        RECOVERY_DAYS_MEANING,
        PLAN_WEEKS_MEANING,
        _tool("get_daily_metrics")["description"],
        _tool("get_planned_workouts")["description"],
    ):
        assert " ".join(words.split()) in draft, words[:60]


# -- the tools ---------------------------------------------------------------------------


def _realistic_wake_row(day: date) -> DailyMetric:
    return DailyMetric(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        calendar_date=day,
        phase=DAILY_METRIC_PHASE_MORNING,
        recorded_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=6),
        readiness_score=64,
        readiness_level="MODERATE",
        readiness_sleep_score=77,
        recovery_time_min=1180,
        acute_load=488,
        training_status="PRODUCTIVE_3",
        hrv_last_night_avg_ms=43,
        hrv_weekly_avg_ms=45,
        hrv_status="UNBALANCED",
        hrv_baseline_low_ms=44,
        hrv_baseline_high_ms=51,
        resting_heart_rate_bpm=46,
        stress_avg=23,
        body_battery_charged=58,
        body_battery_drained=11,
        body_battery_end=81,
        raw_payload={},
    )


def test_the_daily_metrics_description_tells_the_truth_about_its_cap() -> None:
    """One lookup fits about two weeks of mornings, so six weeks takes three lookups.

    That is why ``recoveryDays`` exists, and why the description says so: a coach
    told only to "look it up" gets a truncated fortnight and may sum up six weeks
    from it.
    """
    description = _tool("get_daily_metrics")["description"]
    assert "about two weeks of mornings at most" in description
    assert "several ranges in one go" in description

    rows = [_daily_metric_state(_realistic_wake_row(TODAY - timedelta(days=i))) for i in range(40)]
    fitted = json.loads(_result(rows, meaning="x" * 450, row_cap_exceeded=True))["rowCount"]
    assert 12 <= fitted <= 18, fitted
    assert MAX_RESULT_CHARS == 12_000


def test_the_planned_workouts_description_is_the_route_to_an_older_phase() -> None:
    description = _tool("get_planned_workouts")["description"]
    assert "the week of his plan it falls in" in description
    assert "before you say what a past session was or which phase of his plan" in description


# -- the records (380.2) -------------------------------------------------------------------


def test_a_date_names_the_plan_week_it_falls_in() -> None:
    base = _block("PN4 W05 BUILD", "build", date(2026, 3, 9))
    taper = _block("PN4 W06 TAPER", "taper", date(2026, 3, 16))
    assert plan_week_on([base, taper], date(2026, 3, 14)) == {
        "name": "PN4 W05 BUILD",
        "weekType": "build",
    }
    assert plan_week_on([base, taper], date(2026, 3, 16)) == {
        "name": "PN4 W06 TAPER",
        "weekType": "taper",
    }
    assert plan_week_on([base, taper], date(2026, 3, 30)) is None
    assert plan_week_on([], date(2026, 3, 14)) is None


def test_a_week_loaded_over_another_names_the_day() -> None:
    old = _block("PN3 W12 CONSOLIDATION", "consolidation", date(2026, 3, 9))
    new = _block("PN4 W01 TEST", "build", date(2026, 3, 11), days=5)
    assert plan_week_on([old, new], date(2026, 3, 12)) == {
        "name": "PN4 W01 TEST",
        "weekType": "build",
    }
    assert plan_week_on([old, new], date(2026, 3, 10)) == {
        "name": "PN3 W12 CONSOLIDATION",
        "weekType": "consolidation",
    }


def test_a_plan_week_carries_its_dates_name_and_type() -> None:
    block = _block("PN4 W05 BUILD", "build", date(2026, 3, 9))
    assert plan_week_state(block) == {
        "name": "PN4 W05 BUILD",
        "weekType": "build",
        "startDate": "2026-03-09",
        "endDate": "2026-03-15",
    }


def _full_recovery_days() -> dict[str, Any]:
    days = [
        [(TODAY - timedelta(days=i)).isoformat(), 71, 47, 46, "BALANCED", 45]
        for i in range(CHECKABLE_STRETCH_DAYS - 1, -1, -1)
    ]
    return {"columns": list(RECOVERY_DAY_COLUMNS), "days": days, "meaning": RECOVERY_DAYS_MEANING}


def _full_plan_weeks() -> dict[str, Any]:
    start = TODAY - timedelta(days=CHECKABLE_STRETCH_DAYS + 6)
    weeks = [
        plan_week_state(
            _block(
                f"PN4 W{index:02d} RECOVERY + BUILD",
                "consolidation",
                start + timedelta(weeks=index),
            )
        )
        for index in range(8)
    ]
    return {"weeks": weeks, "meaning": PLAN_WEEKS_MEANING}


def test_both_records_are_small_against_the_budget() -> None:
    """A full six weeks and eight plan weeks, with long invented names, measured.

    The live block is uncached and re-charged on every call, so the additions are
    sized: about 2,500 and 1,400 characters, under 7% of the 62,500 budget together.
    """
    recovery = app_state_length({"recoveryDays": _full_recovery_days()})
    weeks = app_state_length({"planWeeks": _full_plan_weeks()})
    assert recovery < 2_700, recovery
    assert weeks < 1_600, weeks
    assert recovery + weeks < APP_STATE_CHAR_BUDGET * 0.07


def test_six_weeks_of_wake_readings_drop_after_sleep_history_and_can_be_fetched() -> None:
    order = list(_DROP_ORDER)
    assert order.index("sleepHistory") < order.index("recoveryDays") < order.index("recentMornings")
    assert _FETCHABLE_OMISSIONS["recoveryDays"] == "get_daily_metrics"
    assert "get_daily_metrics" in TOOL_NAMES
    assert "planWeeks" not in order


def test_under_pressure_the_readings_go_before_the_mornings_and_the_plan_weeks_stay() -> None:
    quarter = "x" * (APP_STATE_CHAR_BUDGET // 4)
    half = "x" * (APP_STATE_CHAR_BUDGET // 2)
    state: dict[str, Any] = {
        "planWeeks": _full_plan_weeks(),
        "recentActivities": [{"note": quarter}],
        "latestReviews": [{"note": quarter}],
        "sleepHistory": [{"note": quarter}],
        "recoveryDays": _full_recovery_days(),
        "recentMornings": {"days": [{"note": half}]},
        "knowledgeBase": {"sections": [{"note": half}]},
    }
    _apply_char_budget(state)

    assert state["omittedForLength"] == [
        "recentActivities",
        "latestReviews",
        "sleepHistory",
        "recoveryDays",
        "recentMornings",
    ]
    assert state["recoveryDays"] == {}
    assert state["omittedForLengthFetchWith"]["recoveryDays"] == "get_daily_metrics"
    assert state["knowledgeBase"]["sections"]
    assert state["planWeeks"]["weeks"]


# -- assembled from Postgres ----------------------------------------------------------------


async def _profile(session: AsyncSession) -> Profile:
    user = Profile(
        id=uuid.uuid4(),
        display_name="Batch 380",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


def _wake(user_id: uuid.UUID, day: date, *, hrv: int, rhr: int, phase: str) -> DailyMetric:
    return DailyMetric(
        id=uuid.uuid4(),
        user_id=user_id,
        calendar_date=day,
        phase=phase,
        readiness_score=70,
        hrv_last_night_avg_ms=hrv,
        hrv_weekly_avg_ms=hrv,
        hrv_status="LOW" if hrv < 40 else "BALANCED",
        resting_heart_rate_bpm=rhr,
        raw_payload={},
    )


def _week(
    user_id: uuid.UUID, name: str, block_type: str, start: date, *, version: int = 1
) -> PlanBlock:
    return PlanBlock(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        version=version,
        block_type=block_type,
        start_date=start,
        end_date=start + timedelta(days=6),
        goals_json={},
        raw_plan={},
    )


@pytest.mark.asyncio
async def test_on_postgres_a_low_week_inside_an_in_range_month_is_in_front_of_the_coach(
    db_conn: AsyncConnection,
) -> None:
    """Claim type 1, end to end: the month's mean sits in range, five mornings do not.

    The monthly trend alone shows the mean; ``recoveryDays`` shows each morning, the
    wake row ahead of the settled one, oldest first, and nothing before the six weeks.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _profile(session)
        stretch_start = TODAY - timedelta(days=CHECKABLE_STRETCH_DAYS - 1)
        low_days = {stretch_start + timedelta(days=offset) for offset in range(10, 15)}
        for offset in range(CHECKABLE_STRETCH_DAYS):
            day = stretch_start + timedelta(days=offset)
            low = day in low_days
            session.add(
                _wake(
                    user.id,
                    day,
                    hrv=36 if low else 52,
                    rhr=51 if low else 44,
                    phase=DAILY_METRIC_PHASE_MORNING,
                )
            )
        # A settled row beside one wake row, and one reading before the stretch.
        session.add(_wake(user.id, TODAY, hrv=99, rhr=99, phase=DAILY_METRIC_PHASE_SETTLED))
        session.add(
            _wake(
                user.id,
                stretch_start - timedelta(days=1),
                hrv=20,
                rhr=60,
                phase=DAILY_METRIC_PHASE_MORNING,
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(user, None, asked_at_utc=ASKED_AT)

    recovery = context.app_state["recoveryDays"]
    assert recovery["columns"] == list(RECOVERY_DAY_COLUMNS)
    days = recovery["days"]
    assert len(days) == CHECKABLE_STRETCH_DAYS
    assert days[0][0] == stretch_start.isoformat()
    assert days[-1] == [TODAY.isoformat(), 70, 52, 52, "BALANCED", 44]
    low_rows = [row for row in days if row[2] < 40]
    assert [row[0] for row in low_rows] == sorted(day.isoformat() for day in low_days)
    assert all(row[5] == 51 for row in low_rows)
    assert "check its days here" in recovery["meaning"]


@pytest.mark.asyncio
async def test_on_postgres_the_coach_holds_the_plans_weeks_by_name_and_type(
    db_conn: AsyncConnection,
) -> None:
    """Claim type 2, the phase: six weeks back through the week ahead, latest version."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _profile(session)
        monday = TODAY - timedelta(days=TODAY.weekday())
        session.add_all(
            [
                _week(user.id, "PN4 W01 TEST + BUILD", "build", monday - timedelta(weeks=8)),
                _week(
                    user.id, "PN4 W04 CONSOLIDATION", "consolidation", monday - timedelta(weeks=5)
                ),
                _week(user.id, "PN4 W06 TAPER", "build", monday - timedelta(weeks=1), version=1),
                _week(user.id, "PN4 W06 TAPER", "taper", monday - timedelta(weeks=1), version=2),
                _week(user.id, "PN4 W07 RECOVERY", "recovery", monday),
                _week(user.id, "PN4 W08 BUILD", "build", monday + timedelta(weeks=1)),
                _week(user.id, "PN4 W10 BUILD", "build", monday + timedelta(weeks=3)),
            ]
        )
        await session.commit()

        context = await ChatContextService(session).build(user, None, asked_at_utc=ASKED_AT)

    plan_weeks = context.app_state["planWeeks"]
    assert [(week["name"], week["weekType"]) for week in plan_weeks["weeks"]] == [
        ("PN4 W04 CONSOLIDATION", "consolidation"),
        ("PN4 W06 TAPER", "taper"),
        ("PN4 W07 RECOVERY", "recovery"),
        ("PN4 W08 BUILD", "build"),
    ]
    assert "never from his weekly rhythm" in plan_weeks["meaning"]


@pytest.mark.asyncio
async def test_on_postgres_a_past_session_lookup_names_its_plan_week(
    db_conn: AsyncConnection,
) -> None:
    """Claim type 2, the session: what it was, and the week it fell in, from its record."""
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _profile(session)
        week_start = date(2025, 12, 1)
        block = _week(user.id, "PN3 W13 TAPER", "taper", week_start)
        session.add(block)
        await session.flush()
        primer_day = week_start + timedelta(days=5)
        session.add_all(
            [
                PlannedWorkout(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    plan_block_id=block.id,
                    workout_date=primer_day,
                    version=1,
                    title="Saturday primer",
                    workout_type="bike_tempo",
                    status="completed",
                    is_active=True,
                    planned_duration_min=35,
                    intensity_target="85% FTP",
                    structured_workout={"workPctFtp": 85},
                ),
                PlannedWorkout(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    workout_date=week_start + timedelta(days=8),
                    version=1,
                    title="Easy spin",
                    workout_type="bike_recovery",
                    status="planned",
                    is_active=True,
                    planned_duration_min=30,
                    intensity_target="55% FTP",
                    structured_workout={"workPctFtp": 55},
                ),
            ]
        )
        await session.commit()

        result = await CoachToolbox(session, user).execute(
            tool_use_id="tu_380",
            name="get_planned_workouts",
            payload={
                "startDate": week_start.isoformat(),
                "endDate": (week_start + timedelta(days=9)).isoformat(),
            },
        )

    payload = json.loads(result.content)
    by_title = {row["title"]: row for row in payload["rows"]}
    assert by_title["Saturday primer"]["plannedDurationMin"] == 35
    assert by_title["Saturday primer"]["planWeek"] == {"name": "PN3 W13 TAPER", "weekType": "taper"}
    assert by_title["Easy spin"]["planWeek"] is None
    assert "planWeek is the week of his plan the date falls in" in payload["meaning"]
