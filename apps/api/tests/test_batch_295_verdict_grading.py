"""Batch 295 — the graded verdict, built beside the ladder and replayed.

Three kinds of test:

* **Fixture days.** Mark's own rows, extracted read-only from production on 29 Sep 2026
  (``fixtures/verdict_replay_2026_09.json``): 16 Jul (the illness-grade HRV floor),
  7 Sep (one very poor night alone) and 18-26 Sep (the HRV cluster he disputed). They
  go through the same ``replay_morning`` the committed report used, so the colours
  below are the report's.
* **Invariants over an exhaustive grid** (295.8): a worse input never gives a better
  colour; floors always hold; missing data never gives Red; no VO2 on Red; identical
  inputs give identical output.
* **The boundary** this batch shipped with (nothing live read the engine) ended with
  Batch 296, which switches the colour; its tests pin the new boundary.
"""

from __future__ import annotations

import itertools
import json
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.models.coaching import DailyMetric, PlanBlock, Sleep
from src.services import verdict_replay as verdict_replay_module
from src.services.symptom_check import symptom_signal
from src.services.verdict_grading import (
    ACTION_NO_TRAINING,
    ACTION_OFF_THE_BIKE,
    ACTION_RECOVERY,
    DOMAIN_AUTONOMIC,
    DOMAIN_LOAD,
    DOMAIN_SLEEP,
    DOMAIN_SUBJECTIVE,
    THRESHOLDS,
    GradingInputs,
    PlannedSession,
    classify_session,
    grade,
)
from src.services.verdict_replay import MorningRead, replay_morning

FIXTURE = Path(__file__).parent / "fixtures" / "verdict_replay_2026_09.json"
DAY = date(2026, 10, 7)

# -- the fixture days -------------------------------------------------------------------


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def _metrics(rows: list[list[Any]]) -> dict[date, DailyMetric]:
    return {
        date.fromisoformat(row[0]): DailyMetric(
            calendar_date=date.fromisoformat(row[0]),
            phase=row[1],
            hrv_last_night_avg_ms=row[2],
            hrv_weekly_avg_ms=row[3],
            resting_heart_rate_bpm=row[4],
            hrv_baseline_low_ms=row[5],
            hrv_baseline_high_ms=row[6],
            readiness_score=row[7],
        )
        for row in rows
    }


#: The graded rules added since the switch, by the batch that added them, as the
#: ``GradingInputs`` flag that turns each off.
LATER_RULES: dict[int, dict[str, bool]] = {
    304: {"hrv_persistence": False},
    305: {"yesterday_counts_on_hard_days": False},
    306: {"tired_morning_choices": False},
}


def _replayed(fixture: Mapping[str, Any], *, before: int | None = None) -> dict[date, Any]:
    """The fixture days through ``replay_morning``.

    The fixture's mornings were stored before the switch, so the replay grades them
    under today's rules. ``before=N`` grades them without the rules batch N and later
    added, as the engine stood when that batch began, for the tests that pin earlier
    batches' own mechanics on the mornings they were written against.
    """
    if before is not None:
        flags = {
            name: value
            for batch, rules in LATER_RULES.items()
            if batch >= before
            for name, value in rules.items()
        }

        def graded_before(inputs: GradingInputs) -> Any:
            return grade(replace(inputs, **flags))

        with patch.object(verdict_replay_module, "grade", graded_before):
            return _replayed(fixture)
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
    feels = {date.fromisoformat(day): score for day, score in fixture["feels"]}
    blocks = [
        PlanBlock(
            name=name,
            block_type=block_type,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end),
        )
        for name, block_type, start, end in fixture["blocks"]
    ]
    out: dict[date, Any] = {}
    for morning in fixture["mornings"]:
        day = date.fromisoformat(morning["subjectDate"])
        read = MorningRead(
            id=uuid.uuid4(),
            subject_date=day,
            generated_at_utc=datetime.combine(day, datetime.min.time()),
            created_at=datetime.combine(day, datetime.min.time()),
            verdict=morning["verdict"],
            daily_metrics=morning["dailyMetrics"],
            sleep=morning["sleep"],
            manual_entries=morning["manualEntries"],
            planned_workouts=morning["plannedWorkouts"],
            yesterday_load=morning["yesterdayLoad"],
            rest_day=morning["restDay"],
            readiness_trend=None,
            age_adjusted=morning["ageAdjusted"],
        )
        out[day] = replay_morning(
            read,
            metrics=wake,
            baseline_metrics=preferred,
            sleeps=sleeps,
            feels=feels,
            blocks=blocks,
        )
    return out


@pytest.fixture(scope="module")
def replayed() -> dict[date, Any]:
    return _replayed(_load_fixture())


@pytest.fixture(scope="module")
def replayed_before_304() -> dict[date, Any]:
    return _replayed(_load_fixture(), before=304)


@pytest.mark.parametrize(
    ("day", "ladder", "before_304", "graded"),
    [
        # 16 Jul: 33 ms against 48, the one illness-grade night. The floor holds.
        (date(2026, 7, 16), "Amber", "Amber", "Amber"),
        # 7 Sep: sleep 53 on its own. One very poor night is at most marked, so Amber.
        (date(2026, 9, 7), "Red", "Amber", "Amber"),
        # 18-26 Sep: the HRV cluster Mark called a sledgehammer.
        (date(2026, 9, 18), "Green (held)", "Green", "Green"),
        (date(2026, 9, 19), "Green (held)", "Green (held)", "Green (held)"),
        (date(2026, 9, 20), "Green", "Green", "Green"),
        (date(2026, 9, 21), "Red", "Amber", "Amber"),
        # Batch 304: a second night under his floor with the week already under his
        # smallest worthwhile change marks autonomic.
        (date(2026, 9, 22), "Red", "Green (held)", "Amber"),
        # Batch 304: the third morning running with the week under it.
        (date(2026, 9, 23), "Green (held)", "Green (held)", "Amber"),
        (date(2026, 9, 24), "Amber", "Amber", "Amber"),
        (date(2026, 9, 25), "Red", "Amber", "Amber"),
        (date(2026, 9, 26), "Amber", "Green (held)", "Amber"),
    ],
)
def test_the_fixture_days_replay_to_the_reports_colours(
    replayed: dict[date, Any],
    replayed_before_304: dict[date, Any],
    day: date,
    ladder: str,
    before_304: str,
    graded: str,
) -> None:
    morning = replayed[day]
    assert morning.ladder_label == ladder
    assert morning.graded_label == graded
    # The committed 295 report's colours: the engine as it graded before Batch 304.
    assert replayed_before_304[day].graded_label == before_304


def test_16_jul_keeps_its_floor(replayed: dict[date, Any]) -> None:
    morning = replayed[date(2026, 7, 16)]
    assert morning.ladder_bike_rest is True
    assert morning.graded.floor == "bike_rest"
    assert morning.graded.domain(DOMAIN_AUTONOMIC).rating == "marked"


def test_7_sep_is_one_poor_night_and_nothing_else(replayed: dict[date, Any]) -> None:
    morning = replayed[date(2026, 9, 7)]
    ratings = {item.domain: item.rating for item in morning.graded.domains}
    assert ratings == {
        DOMAIN_AUTONOMIC: "none",
        DOMAIN_SLEEP: "marked",
        DOMAIN_LOAD: "none",
        DOMAIN_SUBJECTIVE: "none",
    }


def test_22_sep_is_one_domain_not_two(
    replayed: dict[date, Any], replayed_before_304: dict[date, Any]
) -> None:
    """Last night low and the week low are the same autonomic evidence: one domain."""
    before = replayed_before_304[date(2026, 9, 22)].graded
    autonomic = before.domain(DOMAIN_AUTONOMIC)
    assert autonomic.rating == "mild"
    assert {signal.signal for signal in autonomic.signals if signal.rating == "mild"} == {
        "hrv_overnight",
        "hrv_7_day",
    }
    assert [item.rating for item in before.domains].count("mild") == 1

    # Batch 304: together they now mark the domain. Still one domain, never two.
    graded = replayed[date(2026, 9, 22)].graded
    assert [item.rating for item in graded.domains] == ["marked", "none", "none", "none"]


def test_21_sep_is_amber_because_age_credit_cannot_decide_it(
    replayed: dict[date, Any], replayed_before_304: dict[date, Any]
) -> None:
    before = replayed_before_304[date(2026, 9, 21)].graded
    assert before.age_credit_guard_applied is True
    assert before.status == "Amber"

    # Batch 304: the low week with a night under his floor makes it Amber on its own,
    # so the guard has nothing left to decide.
    graded = replayed[date(2026, 9, 21)].graded
    assert graded.status == "Amber"
    assert graded.domain(DOMAIN_AUTONOMIC).rating == "marked"
    assert graded.age_credit_guard_applied is False


# -- a synthetic history for the grid ---------------------------------------------------

BASE_HRV = [42.0, 47.0, 52.0]  # mean 47, SD 4.08
BASE_SLEEP = [420.0, 450.0, 480.0]  # mean 450 min, SD 24.5
BASE_FEEL = [6, 7, 8]  # mean 7, SD 0.82


def _hrv_nights(week_value: float | None) -> tuple[tuple[date, float], ...]:
    nights = [(DAY - timedelta(days=offset), BASE_HRV[offset % 3]) for offset in range(90, 6, -1)]
    if week_value is not None:
        nights += [(DAY - timedelta(days=offset), week_value) for offset in range(6, -1, -1)]
    return tuple(nights)


def _acute(
    *,
    overnight: str = "none",
    rhr_rise: int = 0,
    rhr_two: bool = False,
    symptoms: str | None = None,
    insufficient: bool = False,
) -> dict[str, Any]:
    """The acute rail as Batch 294 builds it: two mornings above his usual range, or a
    rise of 7 bpm, triggers the resting-HR rail; a single-morning rise under 7 does not.
    """
    capped = overnight in {"capped", "illness"}
    illness = overnight == "illness"
    rhr_trigger = "absolute_delta" if rhr_rise >= 7 else "consecutive_q3" if rhr_two else None
    delta = float(max(rhr_rise, 2 if rhr_two else 0))
    signal = symptom_signal(symptoms)
    bike_rest = (
        illness
        or rhr_rise >= 7
        or signal["requiresBikeRest"]
        or (capped and (rhr_trigger is not None or symptoms not in (None, "none")))
    )
    return {
        "symptoms": signal,
        "requiresTrainingRest": signal["requiresTrainingRest"],
        "requiresBikeRest": bike_rest,
        "overnightHrv": {
            "triggered": capped,
            "illnessGrade": illness,
            "currentMs": 30 if illness else 40 if capped else 47,
            "acuteFloorMs": 41,
            "illnessLineMs": 36,
            "baselineMedianMs": 47,
        },
        "restingHeartRate": {
            "triggered": rhr_trigger is not None,
            "trigger": rhr_trigger,
            "currentBpm": 44 + delta,
            "deltaFromMedianBpm": delta,
            "baselineMedianBpm": 44,
        },
        "dataSufficiency": {"status": "insufficient_data" if insufficient else "sufficient"},
    }


VO2 = classify_session(
    session_id="vo2",
    title="VO2",
    workout_type="bike_vo2",
    planned_minutes=60,
    ir={"steps": [{"durationSec": 180, "powerStartPct": 120, "powerEndPct": 120}]},
)
Z2 = classify_session(
    session_id="z2",
    title="Z2",
    workout_type="bike_endurance",
    planned_minutes=75,
    ir={"steps": [{"durationSec": 4500, "powerStartPct": 67, "powerEndPct": 67}]},
)


def _inputs(
    *,
    week: float = 47.0,
    overnight: str = "none",
    rhr_rise: int = 0,
    rhr_two: bool = False,
    sleep_score: int = 80,
    raw_offset: int = 0,
    minutes: float = 450.0,
    acwr: float = 1.0,
    recovery_hours: float = 10.0,
    yesterday: str = "easy",
    feel: int | None = 8,
    readiness: str = "HIGH",
    symptoms: str | None = None,
    insufficient: bool = False,
    sessions: tuple[PlannedSession, ...] = (VO2, Z2),
) -> GradingInputs:
    return GradingInputs(
        subject_date=DAY,
        acute=_acute(
            overnight=overnight,
            rhr_rise=rhr_rise,
            rhr_two=rhr_two,
            symptoms=symptoms,
            insufficient=insufficient,
        ),
        hrv_nights=_hrv_nights(week),
        sleep_score_raw=sleep_score - raw_offset,
        sleep_score_age_adjusted=sleep_score,
        sleep_minutes=minutes,
        sleep_minutes_history=tuple(BASE_SLEEP[i % 3] for i in range(84)),
        acwr=acwr,
        recovery_time_min=recovery_hours * 60,
        yesterday_load=yesterday,
        feel=feel,
        feel_history=tuple(BASE_FEEL[i % 3] for i in range(30)),
        readiness_level=readiness,
        readiness_score=70,
        readiness_lower_quartile=55,
        sessions=sessions,
    )


# Levels for each input, from best to worst.
LEVELS: dict[str, list[Any]] = {
    "week": [47.0, 44.5, 42.5],
    "overnight": ["none", "capped", "illness"],
    # Size and persistence are separate: 294's floor reads persistence, not size.
    "rhr_rise": [0, 4, 5, 7],
    "rhr_two": [False, True],
    "sleep_score": [80, 70, 55],
    "minutes": [450.0, 360.0],
    "acwr": [1.0, 1.6],
    "recovery_hours": [10.0, 50.0],
    "yesterday": ["easy", "hard"],
    "feel": [8, 5, 3],
    "readiness": ["HIGH", "LOW"],
}
RANK = {"Green": 0, "Green (held)": 1, "Amber": 2, "Red": 3}


def test_the_grid_levels_mean_what_they_say() -> None:
    """Each level rates as named, so the grid below tests what it claims to."""

    def rating(domain: str, **kwargs: Any) -> str:
        return grade(_inputs(**kwargs)).domain(domain).rating

    assert [rating(DOMAIN_AUTONOMIC, week=w) for w in LEVELS["week"]] == ["none", "mild", "marked"]
    assert [rating(DOMAIN_AUTONOMIC, overnight=o) for o in LEVELS["overnight"]] == [
        "none",
        "mild",
        "marked",
    ]
    assert [rating(DOMAIN_AUTONOMIC, rhr_rise=r) for r in LEVELS["rhr_rise"]] == [
        "none",
        "mild",
        "marked",
        "marked",
    ]
    assert rating(DOMAIN_AUTONOMIC, rhr_two=True) == "mild"
    assert [rating(DOMAIN_SLEEP, sleep_score=s) for s in LEVELS["sleep_score"]] == [
        "none",
        "mild",
        "marked",
    ]
    assert [rating(DOMAIN_SLEEP, minutes=m) for m in LEVELS["minutes"]] == ["none", "marked"]
    assert [rating(DOMAIN_LOAD, acwr=a) for a in LEVELS["acwr"]] == ["none", "marked"]
    assert [rating(DOMAIN_LOAD, recovery_hours=h) for h in LEVELS["recovery_hours"]] == [
        "none",
        "marked",
    ]
    assert [rating(DOMAIN_LOAD, yesterday=y) for y in LEVELS["yesterday"]] == ["none", "mild"]
    assert [rating(DOMAIN_SUBJECTIVE, feel=f) for f in LEVELS["feel"]] == [
        "none",
        "marked",
        "marked",
    ]
    assert rating(DOMAIN_SUBJECTIVE, feel=6) == "mild"


def test_the_lines_sit_where_the_table_says() -> None:
    marked, mild = THRESHOLDS["acwr_marked"].value, THRESHOLDS["acwr_mild"].value
    assert grade(_inputs(acwr=marked)).domain(DOMAIN_LOAD).rating == "marked"
    assert grade(_inputs(acwr=marked - 0.01)).domain(DOMAIN_LOAD).rating == "mild"
    assert grade(_inputs(acwr=mild - 0.01)).domain(DOMAIN_LOAD).rating == "none"
    hours = THRESHOLDS["recovery_time_mild_hours"].value
    assert grade(_inputs(recovery_hours=hours)).domain(DOMAIN_LOAD).rating == "none"
    assert grade(_inputs(recovery_hours=hours + 1)).domain(DOMAIN_LOAD).rating == "mild"
    below = int(THRESHOLDS["sleep_score_marked_below"].value)
    assert grade(_inputs(sleep_score=below)).domain(DOMAIN_SLEEP).rating == "mild"
    assert grade(_inputs(sleep_score=below - 1)).domain(DOMAIN_SLEEP).rating == "marked"
    assert grade(_inputs(feel=int(THRESHOLDS["feel_rough_max"].value))).status == "Red"


@pytest.fixture(scope="module")
def grid() -> dict[tuple[int, ...], Any]:
    keys = list(LEVELS)
    results: dict[tuple[int, ...], Any] = {}
    for combo in itertools.product(*(range(len(LEVELS[key])) for key in keys)):
        kwargs = {key: LEVELS[key][index] for key, index in zip(keys, combo, strict=True)}
        results[combo] = grade(_inputs(**kwargs))
    return results


def test_a_worse_input_never_gives_a_better_colour(grid: dict[tuple[int, ...], Any]) -> None:
    keys = list(LEVELS)
    violations: list[str] = []
    for combo, verdict in grid.items():
        for position, key in enumerate(keys):
            if combo[position] + 1 >= len(LEVELS[key]):
                continue
            worse = list(combo)
            worse[position] += 1
            label, worse_label = verdict.label, grid[tuple(worse)].label
            if RANK[worse_label] < RANK[label]:
                violations.append(f"{key} worse at {combo}: {label} -> {worse_label}")
    assert violations == [], violations[:5]
    assert len(grid) == 20_736


def test_every_colour_is_reachable_on_the_grid(grid: dict[tuple[int, ...], Any]) -> None:
    assert {verdict.label for verdict in grid.values()} == set(RANK)


@pytest.mark.parametrize("symptoms", ["head_cold", "fever_aches", "chest_heart"])
def test_symptom_floors_always_hold(symptoms: str) -> None:
    for kwargs in (
        {},
        {"week": 42.5, "overnight": "capped", "feel": 3},
        {"sleep_score": 90, "acwr": 1.0, "feel": 10},
    ):
        verdict = grade(_inputs(symptoms=symptoms, **kwargs))
        assert verdict.status == "Red"
        if symptoms in {"fever_aches", "chest_heart"}:
            assert verdict.floor == "no_training"
            assert {action.action for action in verdict.actions} == {ACTION_NO_TRAINING}


@pytest.mark.parametrize(
    ("overnight", "rhr_rise", "rhr_two"),
    [("illness", 0, False), ("none", 7, False), ("capped", 0, True)],
)
def test_bike_rest_floors_always_hold(overnight: str, rhr_rise: int, rhr_two: bool) -> None:
    verdict = grade(_inputs(overnight=overnight, rhr_rise=rhr_rise, rhr_two=rhr_two))
    assert verdict.floor == "bike_rest"
    assert RANK[verdict.label] >= RANK["Amber"]
    for action in verdict.actions:
        assert action.action == ACTION_OFF_THE_BIKE


def test_missing_data_never_gives_red() -> None:
    for kwargs in (
        {},
        {"week": 44.5},
        {"sleep_score": 70, "yesterday": "hard"},
        {"acwr": 1.6},
    ):
        verdict = grade(_inputs(insufficient=True, **kwargs))
        assert verdict.status != "Red"
        assert RANK[verdict.label] >= RANK["Amber"]
    empty = GradingInputs(
        subject_date=DAY,
        acute=_acute(insufficient=True),
        sessions=(VO2, Z2),
    )
    verdict = grade(empty)
    assert verdict.status == "Amber"
    assert all(item.rating == "none" for item in verdict.domains)


def test_no_vo2_on_red(grid: dict[tuple[int, ...], Any]) -> None:
    reds = [verdict for verdict in grid.values() if verdict.status == "Red"]
    assert reds
    for verdict in reds:
        vo2 = next(action for action in verdict.actions if action.session_id == "vo2")
        assert vo2.action in {ACTION_RECOVERY, ACTION_OFF_THE_BIKE, ACTION_NO_TRAINING}


def test_identical_inputs_give_identical_output() -> None:
    for kwargs in ({}, {"week": 44.5, "feel": 5}, {"symptoms": "head_cold"}):
        first, second = grade(_inputs(**kwargs)), grade(_inputs(**kwargs))
        assert first == second
        assert first.to_packet() == second.to_packet()


def test_readiness_confirms_one_domain_at_most() -> None:
    verdict = grade(_inputs(sleep_score=70, yesterday="hard", readiness="LOW"))
    confirmed = [item.domain for item in verdict.domains if item.confirmed_by_readiness]
    assert confirmed == [DOMAIN_SLEEP]
    assert verdict.status == "Amber"  # one marked (confirmed), one mild
    assert grade(_inputs(readiness="LOW")).label == "Green"  # it never votes alone


def test_a_recovery_week_holds_the_session_under_a_concern() -> None:
    base = _inputs(week=44.5, yesterday="hard")  # two mild domains: Amber
    assert grade(base).status == "Amber"
    held = replace(base, recovery_class_block=True)
    actions = {action.session_id: action.action for action in grade(held).actions}
    assert actions == {"vo2": "hold_targets", "z2": "hold_targets"}


def test_session_classification() -> None:
    long_ride = classify_session(
        session_id="long",
        title="Long Endurance Ride",
        workout_type="bike_endurance",
        planned_minutes=150,
        ir={"steps": [{"durationSec": 9000, "powerStartPct": 65, "powerEndPct": 65}]},
    )
    strength = classify_session(
        session_id="s", title="Bodyweight", workout_type="strength_maintenance",
        planned_minutes=30, ir=None,
    )  # fmt: skip
    assert (VO2.is_hard, VO2.is_key, VO2.has_vo2) == (True, True, True)
    assert (Z2.is_hard, Z2.is_key) == (False, False)
    assert (long_ride.is_hard, long_ride.is_key) == (False, True)
    assert (strength.is_bike, strength.is_key) == (False, False)


# -- the report and the loading queries ---------------------------------------------------


def test_the_report_renders_every_morning_and_the_lines(replayed: dict[date, Any]) -> None:
    from src.services.verdict_replay import ReplayReport, floor_violations, render_markdown

    report = ReplayReport(
        start=min(replayed),
        end=max(replayed),
        mornings=[replayed[day] for day in sorted(replayed)],
    )
    text = render_markdown(report, generated="Generated in a test")

    assert floor_violations(report) == []
    assert "## Every changed morning" in text
    # Batch 304: 22 Sep's low week with a second night under his floor is marked.
    assert "| 22 Sep | Red | Red | Amber | MARKED |" in text
    for key in THRESHOLDS:
        assert f"`{key}`" in text


@pytest.mark.asyncio
async def test_the_replay_loads_a_stored_morning_from_the_database(db_conn: Any) -> None:
    """The loaders' JSONB projections and the delivered-read rule, on real Postgres."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.models.coaching import DAILY_METRIC_PHASE_MORNING, Analysis
    from src.models.profile import Profile, UserRole
    from src.services.verdict_replay import VerdictReplayService

    user_id = uuid.uuid4()
    day = date(2026, 9, 22)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=user_id,
            display_name="Replay",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        for offset in range(1, 40):
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=day - timedelta(days=offset),
                    phase=DAILY_METRIC_PHASE_MORNING,
                    hrv_last_night_avg_ms=BASE_HRV[offset % 3],
                    resting_heart_rate_bpm=44,
                    readiness_score=70,
                    raw_payload={},
                )
            )
        packet = {
            "dailyMetrics": {
                "readinessScore": 78,
                "readinessLevel": "HIGH",
                "hrvLastNightAvgMs": 47,
                "hrvWeeklyAvgMs": 47,
                "hrvStatus": "BALANCED",
                "hrvBaselineLowMs": 44,
                "hrvBaselineHighMs": 56,
                "restingHeartRateBpm": 44,
                "recoveryTimeMin": 0,
                "acuteChronicLoadRatio": 0.9,
            },
            "sleep": {"score": 84, "timeAsleepMin": 450},
            "manualEntries": [{"subjectiveScore": 3, "symptoms": None}],
            "plannedWorkouts": [],
            "yesterdayLoad": {"status": "easy"},
            "restDay": {"isRestDay": False},
            "verdict": {"status": "Green", "ageAdjustedSleepScore": 84},
        }
        for hour, verdict in ((7, "Green"), (21, "Amber")):
            session.add(
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=day,
                    generated_at_utc=datetime(2026, 9, 22, hour, 0),
                    prompt_version="morning-analysis-test",
                    verdict=verdict,
                    context_packet=packet,
                    output_markdown="read",
                    raw_response={},
                )
            )
        await session.commit()

        report = await VerdictReplayService(session).replay(player)

    (morning,) = report.mornings
    # The 07:00 read is the one he was given; the evening regeneration is not.
    assert morning.shown == "Green"
    # He said 3, Rough: the graded verdict is Red on his own word.
    assert morning.graded.status == "Red"
    assert morning.graded.rough_check_in is True
