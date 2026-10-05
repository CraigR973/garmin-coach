"""Batch 296 — the colour comes from the graded verdict.

296.8's tests. The fixture days give the replay's colours and actions in the production
packet and on the delivery rail; packets written before the switch still render; the
VO₂ gate and the two-Reds rule read the new status; flipping the setting back restores
the ladder's output exactly.

Against ``main`` every one of these fails: the graded packet, the rail's morning context
and the review measures do not exist there. The two Postgres tests run in CI only; each
asserts the ladder's Red beside the graded Amber on the same rows, so neither can pass
while the ladder sets the colour.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    Analysis,
    DailyMetric,
    ManualEntry,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile, UserRole
from src.services import morning_analysis as morning_analysis_module
from src.services.coach_policy import LADDER_MORNING_FLOORS, READ_PROMPT_FLOORS, missing_floors
from src.services.daily_loop_envelope import _serialize_analysis
from src.services.executable_coaching import (
    ExecutableCoachingService,
    MorningContext,
    morning_ir,
)
from src.services.morning_analysis import (
    GRADED_PROMPT_VERSION,
    GRADED_SYSTEM_PROMPT,
    LADDER_PROMPT_VERSION,
    LADDER_SYSTEM_PROMPT,
    MorningAnalysisService,
    _eased_ride_detail,
    _log_verdict_engines,
    build_today_actions,
)
from src.services.morning_verdict import (
    BIKE_REST_PLAN_LINE,
    GRADED_EASE_HARD_LINE,
    GRADED_MOVE_LINE,
    GRADED_RECOVERY_WEEK_LINE,
    GRADED_ZONE_TWO_LINE,
    HRV_HOLD_PLAN_LINE,
    LADDER_ONLY_FIELDS,
    graded_plan_adjustments,
    graded_verdict_packet,
)
from src.services.reviews import cautious_day_rollup, key_session_rollup
from src.services.verdict_grading import (
    ENGINE_GRADED,
    ENGINE_LADDER,
    ride_transform,
    stored_actions,
    stored_engine,
)
from src.services.verdict_replay import (
    MorningRead,
    ReplayReport,
    VerdictReplayService,
    _planned_workouts_from_packet,
    render_markdown,
    replay_morning,
)
from src.services.verdict_scaling import (
    ENDURANCE_CEILING_PCT,
    adjust_ir_for_verdict,
    blocks_red_vo2,
    ease_amber_power_pct,
    summarize_verdict_adjustment,
)
from src.services.workout_delivery import build_structured_workout_ir
from tests.test_batch_295_verdict_grading import _load_fixture, _replayed
from tests.test_executable_coaching import (
    ENDURANCE_STRUCTURED,
    VO2_STRUCTURED,
    _planned_workout,
)
from tests.test_morning_analysis import FakeMorningClient

API_ROOT = Path(__file__).resolve().parents[1]

#: The ladder's morning prompt on ``main`` before this batch (v50), byte for byte.
LADDER_PROMPT_SHA256 = "f2e1f2f6bbdad1942379f8bccdb909b14244a66e8f83cfa6ace35118458b201c"

FIXTURE_DAYS = (
    date(2026, 7, 16),
    date(2026, 9, 7),
    date(2026, 9, 18),
    date(2026, 9, 19),
    date(2026, 9, 20),
    date(2026, 9, 21),
    date(2026, 9, 22),
    date(2026, 9, 23),
    date(2026, 9, 24),
    date(2026, 9, 25),
    date(2026, 9, 26),
)


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _load_fixture()


@pytest.fixture(scope="module")
def replayed(fixture: dict[str, Any]) -> dict[date, Any]:
    # Batch 304 marks 22 Sep's HRV dip, so it is no longer held. These tests pin 296's
    # mechanics (the held plan line, the VO2 gate, the drift report) on the mornings as
    # they were graded when 296 shipped, so they replay them without that rule.
    return _replayed(fixture, before=304)


def _planned(fixture: dict[str, Any], day: date) -> list[PlannedWorkout]:
    [morning] = [m for m in fixture["mornings"] if m["subjectDate"] == day.isoformat()]
    return _planned_workouts_from_packet(day, morning["plannedWorkouts"])


def _packet(replayed: dict[date, Any], fixture: dict[str, Any], day: date) -> dict[str, Any]:
    morning = replayed[day]
    return graded_verdict_packet(
        morning.ladder_packet, morning.graded, _planned(fixture, day), breathwork_line=None
    )


# -- 296.8: the fixture days, through the production packet and the delivery rail -------


@pytest.mark.parametrize("day", FIXTURE_DAYS)
def test_the_fixture_days_give_the_replays_colour_and_actions_in_the_packet(
    replayed: dict[date, Any], fixture: dict[str, Any], day: date
) -> None:
    morning = replayed[day]
    planned = _planned(fixture, day)
    packet = _packet(replayed, fixture, day)

    assert packet["engine"] == ENGINE_GRADED
    assert packet["status"] == morning.graded.status
    assert packet["held"] is morning.graded.held
    replay_actions = {item.session_id: item.action for item in morning.graded.actions}
    assert stored_actions({"verdict": packet}) == replay_actions

    # The delivery rail reads the stored packet and gives each ride the replay's action.
    context = MorningContext(
        status=packet["status"], graded=True, actions=stored_actions({"verdict": packet})
    )
    for workout in planned:
        assert context.transform_for(workout) == ride_transform(
            morning.graded.status, graded=True, action=replay_actions.get(str(workout.id))
        )


def test_the_fixture_days_plan_lines_follow_the_session_actions(
    replayed: dict[date, Any], fixture: dict[str, Any]
) -> None:
    # 22 Sep: ladder Red, graded Green with the targets held. The VO₂ moves or holds.
    sept_22 = _packet(replayed, fixture, date(2026, 9, 22))
    assert (sept_22["status"], sept_22["held"]) == ("Green", True)
    assert GRADED_MOVE_LINE.format(title="VO₂ (5 × 2:30 @ 119%)") in sept_22["planAdjustments"]
    assert HRV_HOLD_PLAN_LINE in sept_22["planAdjustments"]
    assert sept_22["reasons"][0].startswith("One thing is a little off: your HRV was low")

    # 19 Sep: a planned recovery week holds the session.
    sept_19 = _packet(replayed, fixture, date(2026, 9, 19))
    assert GRADED_RECOVERY_WEEK_LINE in sept_19["planAdjustments"]
    assert HRV_HOLD_PLAN_LINE not in sept_19["planAdjustments"]

    # 24 Sep: Amber eases the Sweet Spot's hard work.
    sept_24 = _packet(replayed, fixture, date(2026, 9, 24))
    assert sept_24["status"] == "Amber"
    assert GRADED_EASE_HARD_LINE in sept_24["planAdjustments"]

    # 7 Sep: one very poor night alone is Amber, not Red; the day is strength only.
    sept_7 = _packet(replayed, fixture, date(2026, 9, 7))
    assert sept_7["status"] == "Amber"
    assert sept_7["reasons"][0] == "One thing is clearly off: a very poor night's sleep (score 53)."
    assert any("strength submaximal" in line for line in sept_7["planAdjustments"])


def test_a_graded_packet_carries_none_of_the_ladders_working(
    replayed: dict[date, Any], fixture: dict[str, Any]
) -> None:
    packet = _packet(replayed, fixture, date(2026, 9, 22))

    assert not set(LADDER_ONLY_FIELDS) & set(packet)
    # Kept: the acute rail and its floors, the check-in and the rest-day context.
    assert "acutePhysiology" in packet
    assert "isRestDay" in packet
    graded = packet["graded"]
    assert [domain["domain"] for domain in graded["domains"]] == [
        "autonomic",
        "sleep",
        "load",
        "subjective",
    ]
    assert set(graded["references"]) == {
        "readinessLowerQuartile",
        "inRecoveryWeek",
        "recoveryClassBlock",
        "notesFeelNotch",
        "notesFeelWords",
        # Batch 298: the light week's name, for the plan line and the hero.
        "lightWeek",
        # Batch 304: whether the HRV persistence rule graded it.
        "hrvPersistence",
        # Batch 305: whether a hard yesterday counted only before a hard session.
        "yesterdayCountsOnHardDays",
        # Batch 306: whether a tired morning offered its choices.
        "tiredMorningChoices",
        # Batch 310: whether the holiday catch-up graded it, and the nights away it saw.
        "hrvHolidayCatchUp",
        "hrvWeekNightsAway",
        # Batch 313: what made a tired morning tired, for today's call's words.
        "tiredBy",
    }
    assert "graded_verdict" in packet["safetyRulesApplied"]


def test_a_floor_still_decides_the_plan_line() -> None:
    graded = Mock(status="Amber", held=False, actions=())
    workout = _planned_workout(VO2_STRUCTURED)
    bike_rest = graded_plan_adjustments(
        graded,
        [workout],
        is_rest_day=False,
        acute={"requiresBikeRest": True},
        has_vo2=True,
    )
    assert bike_rest == [BIKE_REST_PLAN_LINE]

    symptom = graded_plan_adjustments(
        graded,
        [workout],
        is_rest_day=False,
        acute={
            "requiresTrainingRest": True,
            "requiresBikeRest": True,
            "symptoms": {"planLine": "No training today."},
        },
        has_vo2=True,
    )
    assert symptom == ["No training today."]


def test_a_graded_amber_keeps_a_zone_2_ride_at_full_length() -> None:
    ride = _planned_workout(ENDURANCE_STRUCTURED)
    ride.workout_type = "bike_endurance"
    graded = Mock(
        status="Amber",
        held=False,
        actions=(Mock(session_id=str(ride.id), action="as_planned"),),
    )
    lines = graded_plan_adjustments(graded, [ride], is_rest_day=False, acute={}, has_vo2=False)
    assert lines == [GRADED_ZONE_TWO_LINE]


def test_red_is_never_vo2_under_the_graded_verdict() -> None:
    graded = Mock(status="Red", held=False, actions=())
    lines = graded_plan_adjustments(
        graded,
        [_planned_workout(VO2_STRUCTURED)],
        is_rest_day=False,
        acute={},
        has_vo2=True,
    )
    assert "Replace VO2 with rest, mobility, or a very easy spin." in lines


# -- 296.3: the one scaling rule ---------------------------------------------------------


def _ir(structured: dict[str, Any]) -> dict[str, Any]:
    return build_structured_workout_ir(_planned_workout(structured), ftp_watts=280)


def _power(step: dict[str, Any]) -> int:
    return max(int(step["powerStartPct"]), int(step["powerEndPct"]))


def test_the_graded_amber_eases_only_the_hard_work_at_full_length() -> None:
    base = _ir(VO2_STRUCTURED)
    eased = adjust_ir_for_verdict(base, "Amber", graded=True)

    assert eased["totalDurationSec"] == base["totalDurationSec"]
    assert eased["origin"] == "graded_amber_ease"
    assert eased["adjustment"]["graded"] is True
    for before, after in zip(base["steps"], eased["steps"], strict=True):
        if _power(before) <= ENDURANCE_CEILING_PCT:
            assert _power(after) == _power(before)
        else:
            assert _power(after) == ease_amber_power_pct(_power(before))

    # The ladder's Amber is unchanged: shorter, and the hard work dropped a zone.
    ladder = adjust_ir_for_verdict(base, "Amber")
    assert ladder["totalDurationSec"] < base["totalDurationSec"]
    assert ladder["origin"] == "amber_regeneration"


def test_the_graded_amber_leaves_a_zone_2_ride_alone() -> None:
    base = _ir(ENDURANCE_STRUCTURED)
    unchanged = adjust_ir_for_verdict(base, "Amber", graded=True)

    assert unchanged["steps"] == base["steps"]
    assert unchanged["adjustment"] == {"verdict": "Amber", "changed": False, "graded": True}
    assert summarize_verdict_adjustment(base, "Amber", graded=True) is None
    # The ladder still shortens it.
    assert adjust_ir_for_verdict(base, "Amber")["totalDurationSec"] < base["totalDurationSec"]


def test_the_approve_card_reads_full_length() -> None:
    assert (
        _eased_ride_detail("Amber", {"graded": True, "adjustedWorkPowerPct": 94})
        == "Ease the hard intervals to ~94% FTP — full length."
    )


def test_a_graded_amber_with_nothing_eased_offers_no_approval() -> None:
    ride = _planned_workout(ENDURANCE_STRUCTURED)
    ride.workout_date = date(2026, 10, 7)
    graded = build_today_actions(
        verdict={"status": "Amber", "engine": "graded", "verdictAdjustment": None},
        planned_workouts=[ride],
        thermal_review={},
        recommend_breathwork=False,
    )
    assert not [action for action in graded if action["kind"] == "approve_ride"]

    ladder = build_today_actions(
        verdict={"status": "Amber", "verdictAdjustment": None},
        planned_workouts=[ride],
        thermal_review={},
        recommend_breathwork=False,
    )
    assert [action for action in ladder if action["kind"] == "approve_ride"]


def test_the_delivery_rail_follows_each_sessions_action() -> None:
    vo2 = _planned_workout(VO2_STRUCTURED)
    ride = _planned_workout(ENDURANCE_STRUCTURED)
    base = _ir(VO2_STRUCTURED)

    held = MorningContext(status="Green", graded=True, actions={str(vo2.id): "move_or_hold"})
    as_planned = morning_ir(base, held, vo2, companion_session=False)
    assert as_planned["steps"] == base["steps"]
    assert as_planned["origin"] == "as_planned"

    amber = MorningContext(
        status="Amber",
        graded=True,
        actions={str(vo2.id): "ease_hard", str(ride.id): "as_planned"},
    )
    assert amber.transform_for(vo2) == "Amber"
    assert amber.transform_for(ride) is None
    eased = morning_ir(base, amber, vo2, companion_session=False)
    assert eased == adjust_ir_for_verdict(base, "Amber", graded=True)

    red = MorningContext(status="Red", graded=True, actions={str(vo2.id): "recovery"})
    assert morning_ir(base, red, vo2, companion_session=True) == adjust_ir_for_verdict(
        base, "Red", companion_session=True, graded=True
    )
    # A ride the packet did not see falls back to the colour.
    unseen = _planned_workout(VO2_STRUCTURED)
    assert amber.transform_for(unseen) == "Amber"


# -- 296.4: every consumer reads the new status -------------------------------------------


def test_the_vo2_gate_reads_the_graded_status(
    replayed: dict[date, Any], fixture: dict[str, Any]
) -> None:
    """22 Sep: the ladder's Red would have blocked the VO₂; the graded Green does not."""

    morning = replayed[date(2026, 9, 22)]
    [vo2] = [w for w in _planned(fixture, date(2026, 9, 22)) if w.workout_type == "bike_vo2"]
    ir = build_structured_workout_ir(vo2, ftp_watts=280)
    packet = _packet(replayed, fixture, date(2026, 9, 22))

    assert morning.ladder == "Red"
    assert blocks_red_vo2(morning.ladder, ir) is True
    # What production stores in Analysis.verdict, and every gate reads, is the packet's.
    assert blocks_red_vo2(packet["status"], ir) is False
    assert blocks_red_vo2("Red", ir) is True


def test_packets_written_before_the_switch_still_render() -> None:
    before = {
        "verdict": {
            "status": "Amber",
            "reasons": ["Sleep 60-73 with Low readiness."],
            "planAdjustments": ["Cut duration 20-30%."],
            "hrvGradedResponse": {"tier": "hold"},
            "trainingLoadCap": {"applies": False},
            "acutePhysiology": {"status": "clear"},
        }
    }
    assert stored_engine(before) == ENGINE_LADDER
    assert stored_actions(before) == {}
    assert stored_engine(None) == ENGINE_LADDER
    # The delivery rail treats it exactly as the ladder did.
    ride = _planned_workout(ENDURANCE_STRUCTURED)
    context = MorningContext(status="Amber", graded=False, actions=stored_actions(before))
    base = _ir(ENDURANCE_STRUCTURED)
    assert morning_ir(base, context, ride, companion_session=False) == adjust_ir_for_verdict(
        base, "Amber"
    )

    analysis = Analysis(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        analysis_type="morning",
        subject_date=date(2026, 9, 27),
        generated_at_utc=datetime(2026, 9, 27, 6, 30),
        created_at=datetime(2026, 9, 27, 6, 30),
        prompt_version=LADDER_PROMPT_VERSION,
        verdict="Amber",
        context_packet=before,
        output_markdown="read",
        raw_response={},
    )
    out = _serialize_analysis(analysis)
    assert out is not None
    assert out.verdictEngine is None
    assert out.verdictHeld is False


def test_the_review_counts_key_sessions_and_cautious_days_by_cause() -> None:
    vo2 = _planned_workout(VO2_STRUCTURED)
    vo2.status = "completed"
    missed = _planned_workout(VO2_STRUCTURED)
    missed.status = "skipped"
    easy = _planned_workout(ENDURANCE_STRUCTURED)
    easy.title = "Easy Z2"
    easy.workout_type = "bike_endurance"
    easy.intensity_target = "64-70% FTP"
    easy.planned_duration_min = 60

    sessions = key_session_rollup([vo2, missed, easy])
    assert (sessions.planned, sessions.completed) == (2, 1)
    assert sessions.by_kind == {"vo2": {"planned": 2, "completed": 1}}

    def row(verdict: str, **fields: Any) -> Mock:
        values = {"held": None, "engine": None, "floor": None, "domains": None, **fields}
        return Mock(verdict=verdict, **values)

    mornings = [
        row("Green", held="true", engine="graded"),
        row(
            "Amber",
            engine="graded",
            domains=[
                {"domain": "autonomic", "rating": "mild"},
                {"domain": "sleep", "rating": "mild"},
                {"domain": "load", "rating": "none"},
            ],
        ),
        row("Red", engine="graded", floor="bike_rest", domains=[]),
        row("Amber"),  # stored before the switch
        row("Green"),
    ]
    cautious = cautious_day_rollup(mornings)
    assert cautious.cautious_days == 3
    assert cautious.held_days == 1
    assert cautious.by_cause == {"autonomic": 1, "sleep": 1, "floor": 1, "ladder": 1}


# -- 296.2: the ladder beside the graded verdict, and the one-setting rollback -------------


def test_both_colours_are_logged_and_two_steps_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = Mock()
    monkeypatch.setattr(morning_analysis_module, "log", log)
    monkeypatch.setattr(morning_analysis_module, "VERDICT_ENGINE", ENGINE_GRADED)
    player = Mock(id=uuid.uuid4())
    green = Mock(status="Green", label="Green")

    _log_verdict_engines(player, date(2026, 10, 7), ladder_status="Red", graded=green)
    info = log.info.call_args
    assert info.args == ("verdict_engines_compared",)
    assert info.kwargs["ladder"] == "Red"
    assert info.kwargs["graded"] == "Green"
    assert info.kwargs["agree"] is False
    log.error.assert_called_once()
    assert log.error.call_args.args == ("verdict_graded_two_steps_less_cautious",)

    log.reset_mock()
    amber = Mock(status="Amber", label="Amber")
    _log_verdict_engines(player, date(2026, 10, 7), ladder_status="Red", graded=amber)
    log.error.assert_not_called()

    # Rolled back, the ladder sets the colour and nothing is less cautious than it.
    log.reset_mock()
    monkeypatch.setattr(morning_analysis_module, "VERDICT_ENGINE", ENGINE_LADDER)
    _log_verdict_engines(player, date(2026, 10, 7), ladder_status="Red", graded=green)
    log.info.assert_called_once()
    log.error.assert_not_called()


def _engine_prompt(engine: str | None) -> tuple[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "VERDICT_ENGINE"}
    if engine is not None:
        env["VERDICT_ENGINE"] = engine
    env["PYTHONPATH"] = str(API_ROOT)
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import hashlib; from src.services import morning_analysis as m; "
            "print(m.PROMPT_VERSION); "
            "print(hashlib.sha256(m.SYSTEM_PROMPT.encode()).hexdigest())",
        ],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    version, digest = out.stdout.strip().splitlines()[-2:]
    return version, digest


def test_flipping_the_setting_back_restores_the_ladders_prompt_exactly() -> None:
    assert _engine_prompt(None) == (
        GRADED_PROMPT_VERSION,
        hashlib.sha256(GRADED_SYSTEM_PROMPT.encode()).hexdigest(),
    )
    assert _engine_prompt("ladder") == (LADDER_PROMPT_VERSION, LADDER_PROMPT_SHA256)
    assert hashlib.sha256(LADDER_SYSTEM_PROMPT.encode()).hexdigest() == LADDER_PROMPT_SHA256


def test_the_rollback_prompt_still_states_the_ladders_floors() -> None:
    assert missing_floors(LADDER_SYSTEM_PROMPT, LADDER_MORNING_FLOORS) == ()
    assert missing_floors(GRADED_SYSTEM_PROMPT, READ_PROMPT_FLOORS["morning_analysis"]) == ()
    # The graded prompt no longer explains the ladder's rungs.
    for field in ("verdict.sleepCreditCeiling", "verdict.cumulativeEscalation"):
        assert field not in GRADED_SYSTEM_PROMPT


# -- the replay against production after the switch ---------------------------------------


def _graded_read(morning: Any, packet: dict[str, Any], day_packet: dict[str, Any]) -> MorningRead:
    return MorningRead(
        id=uuid.uuid4(),
        subject_date=morning.subject_date,
        generated_at_utc=datetime.combine(morning.subject_date, datetime.min.time()),
        created_at=datetime.combine(morning.subject_date, datetime.min.time()),
        verdict=packet["status"],
        daily_metrics=day_packet["dailyMetrics"],
        sleep=day_packet["sleep"],
        manual_entries=day_packet["manualEntries"],
        planned_workouts=day_packet["plannedWorkouts"],
        yesterday_load=day_packet["yesterdayLoad"],
        rest_day=day_packet["restDay"],
        readiness_trend=None,
        age_adjusted=day_packet["ageAdjusted"],
        engine=packet["engine"],
        acute=packet["acutePhysiology"],
        held=packet["held"],
        references=packet["graded"]["references"],
    )


def test_the_replay_reproduces_a_graded_morning_and_reports_drift(
    replayed: dict[date, Any], fixture: dict[str, Any]
) -> None:
    from tests.test_batch_295_verdict_grading import _metrics

    day = date(2026, 9, 22)
    morning = replayed[day]
    packet = _packet(replayed, fixture, day)
    [day_packet] = [m for m in fixture["mornings"] if m["subjectDate"] == day.isoformat()]
    wake = _metrics(fixture["wakeMetrics"])
    preferred = _metrics(fixture["preferredMetrics"])
    sleeps = {
        date.fromisoformat(row[0]): Sleep(
            calendar_date=date.fromisoformat(row[0]),
            duration_sec=row[1],
            resting_heart_rate_bpm=row[2],
            average_spo2_pct=row[3],
            lowest_spo2_pct=row[4],
            average_respiration=row[5],
        )
        for row in fixture["sleeps"]
    }
    feels = {date.fromisoformat(d): score for d, score in fixture["feels"]}
    from src.models.coaching import PlanBlock

    blocks = [
        PlanBlock(
            name=name,
            block_type=block_type,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end),
        )
        for name, block_type, start, end in fixture["blocks"]
    ]

    def replay(read: MorningRead) -> Any:
        return replay_morning(
            read,
            metrics=wake,
            baseline_metrics=preferred,
            sleeps=sleeps,
            feels=feels,
            blocks=blocks,
        )

    again = replay(_graded_read(morning, packet, day_packet))
    assert again.shown_engine == ENGINE_GRADED
    assert again.shown_label == "Green (held)"
    assert again.reproduces_production is True

    # A morning where production showed something else is called out, by date.
    drifted_packet = {**packet, "held": False}
    drifted = replay(_graded_read(morning, drifted_packet, day_packet))
    assert drifted.reproduces_production is False
    text = render_markdown(
        ReplayReport(start=day, end=day, mornings=[drifted]), generated="Generated in a test"
    )
    assert "- **Replay reproduces production:** 0 of 1 graded mornings — DRIFTED on 22 Sep" in text

    # A morning stored before the switch is not judged against the replay.
    assert morning.reproduces_production is None


# -- on Postgres: production stores the graded colour, and the replay reproduces it ------


async def _seed_one_poor_night(session: Any, user_id: uuid.UUID, day: date) -> PlannedWorkout:
    """7 Sep's shape: one very poor night and nothing else. Ladder Red, graded Amber."""

    for offset in range(1, 43):
        night = day - timedelta(days=offset)
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=night,
                phase=DAILY_METRIC_PHASE_MORNING,
                recorded_at_utc=datetime.combine(night, datetime.min.time()) + timedelta(hours=6),
                hrv_last_night_avg_ms=(46, 47, 48)[offset % 3],
                resting_heart_rate_bpm=45,
                readiness_score=70,
                raw_payload={},
            )
        )
        session.add(
            Sleep(
                user_id=user_id,
                calendar_date=night,
                score=80,
                duration_sec=(440, 450, 460)[offset % 3] * 60,
                raw_payload={},
                factors_json={},
            )
        )
    session.add_all(
        [
            DailyMetric(
                user_id=user_id,
                calendar_date=day,
                phase=DAILY_METRIC_PHASE_MORNING,
                recorded_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=6),
                readiness_score=66,
                readiness_level="MODERATE",
                hrv_last_night_avg_ms=47,
                hrv_weekly_avg_ms=47,
                hrv_status="BALANCED",
                hrv_baseline_low_ms=43,
                hrv_baseline_high_ms=55,
                resting_heart_rate_bpm=45,
                raw_payload={},
            ),
            Sleep(
                user_id=user_id,
                calendar_date=day,
                score=53,
                duration_sec=450 * 60,
                raw_payload={},
                factors_json={},
            ),
            ManualEntry(
                user_id=user_id,
                entry_date=day,
                entry_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=6),
                subjective_score=7,
                feel="good",
                supplements_json={},
                food_json={},
                sleep_setup_json={},
            ),
        ]
    )
    vo2 = PlannedWorkout(
        user_id=user_id,
        workout_date=day,
        version=1,
        title="VO2 Max 30/30",
        workout_type="bike_vo2",
        status="planned",
        is_active=True,
        planned_duration_min=60,
        intensity_target="105-110% FTP",
        structured_workout=VO2_STRUCTURED,
        source="test",
    )
    session.add(vo2)
    return vo2


@pytest.mark.asyncio
async def test_production_stores_the_graded_colour_and_the_replay_reproduces_it(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = Mock()
    monkeypatch.setattr(morning_analysis_module, "log", log)
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    day = date(2026, 9, 7)
    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Graded Colour",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        vo2 = await _seed_one_poor_night(session, user_id, day)
        await session.commit()

        result = await MorningAnalysisService(session).generate_and_store(
            player, day, client=FakeMorningClient()
        )
        analysis = result.analysis
        # Delivered at 07:30 local, so the replay's delivered-read rule picks it.
        analysis.generated_at_utc = datetime(2026, 9, 7, 6, 30)
        await session.commit()

        [compared] = [
            call for call in log.info.call_args_list if call.args == ("verdict_engines_compared",)
        ]
        assert compared.kwargs["ladder"] == "Red"
        assert compared.kwargs["graded"] == "Amber"

        # Analysis.verdict, which the VO₂ gate and the two-Reds rule read, is graded.
        assert analysis.verdict == "Amber"
        verdict = analysis.context_packet["verdict"]
        assert verdict["engine"] == ENGINE_GRADED
        assert not set(LADDER_ONLY_FIELDS) & set(verdict)

        context = await ExecutableCoachingService(session)._morning_context_for(user_id, day)
        assert (context.status, context.graded) == ("Amber", True)
        # Batch 306: one very poor night is a tired morning: Mark picks how to ride it.
        assert context.actions == {str(vo2.id): "pick_zone2_or_tempo"}
        base = build_structured_workout_ir(vo2, ftp_watts=280)
        assert blocks_red_vo2(context.status, base) is False
        delivered = morning_ir(base, context, vo2, companion_session=False)
        assert delivered["totalDurationSec"] == base["totalDurationSec"]
        # The brief quotes the same eased ride the rail delivers.
        assert verdict["verdictAdjustment"]["graded"] is True
        assert verdict["verdictAdjustment"]["plannedWorkoutId"] == str(vo2.id)
        assert verdict["verdictAdjustment"]["choice"]["kind"] == "pick"

        report = await VerdictReplayService(session).replay(player)

    [morning] = report.mornings
    assert morning.ladder == "Red"
    assert morning.graded.status == "Amber"
    assert morning.reproduces_production is True


@pytest.mark.asyncio
async def test_flipping_the_setting_back_restores_the_ladders_packet(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What a restart with VERDICT_ENGINE=ladder sets at import (proven above in a
    # subprocess): the engine and the prompt it selects.
    monkeypatch.setattr(morning_analysis_module, "VERDICT_ENGINE", ENGINE_LADDER)
    monkeypatch.setattr(morning_analysis_module, "PROMPT_VERSION", LADDER_PROMPT_VERSION)
    monkeypatch.setattr(morning_analysis_module, "SYSTEM_PROMPT", LADDER_SYSTEM_PROMPT)
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    day = date(2026, 9, 7)
    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Ladder Rollback",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        await _seed_one_poor_night(session, user_id, day)
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, day)

    verdict = packet["verdict"]
    assert verdict["status"] == "Red"
    assert not {"engine", "held", "graded"} & set(verdict)
    assert {"hrvGradedResponse", "trainingLoadCap", "sleepCreditCeiling"} <= set(verdict)
    assert "lead_with_graded_domains_and_his_numbers" not in packet["prompt"]["outputRules"]
    assert packet["prompt"]["version"] == LADDER_PROMPT_VERSION
