from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.services.chronic_patterns import (
    BaselineBand,
    ChronicSuggestion,
    ChronicSuggestionResult,
    RecordedTrainingContext,
    RecoveryDay,
    RedDayEvidence,
    ScheduledRecoveryBlock,
    SleepNight,
    VerdictDay,
    build_chronic_pattern_suggestions,
)
from src.services.insights import DriverCorrelation, correlation_interval
from src.services.rem_interventions import RemRotation


def _driver(
    driver: str,
    outcome: str,
    coefficient: float,
    sample_count: int,
    summary: str | None = None,
    *,
    adjusted: float | None = None,
) -> DriverCorrelation:
    """A correlation shaped the way ``compute_drivers`` now builds one (Batch 249).

    The interval is not decoration: ``select_lever`` refuses a driver that has
    none, so a fixture without one can never name a lever.
    """
    judged = coefficient if adjusted is None else adjusted
    interval = correlation_interval(judged, sample_count, controls=0 if adjusted is None else 1)
    return DriverCorrelation(
        driver=driver,
        outcome=outcome,
        coefficient=coefficient,
        sample_count=sample_count,
        summary=summary,
        adjusted_coefficient=adjusted,
        interval_low=None if interval is None else interval[0],
        interval_high=None if interval is None else interval[1],
    )


def _nights(end: date, *, rem_pct: float, count: int = 28) -> list[SleepNight]:
    rows: list[SleepNight] = []
    for offset in range(count):
        day = end - timedelta(days=count - offset - 1)
        duration = int(7.1 * 3600)
        deep = int(duration * 0.17)
        rem = int(duration * rem_pct)
        awake = int(duration * 0.09)
        light = duration - deep - rem - awake
        rows.append(
            SleepNight(
                calendar_date=day,
                score=68,
                age_adjusted_score=72,
                duration_sec=duration,
                deep_sleep_sec=deep,
                light_sleep_sec=light,
                rem_sleep_sec=rem,
                awake_sleep_sec=awake,
                restless_moments_count=9,
            )
        )
    return rows


def test_chronic_rem_suggestion_prioritises_measured_driver() -> None:
    """Batch 231: the REM flag reads REM's own drivers, strongest actionable first.

    Before this batch the same inputs returned ``prev_day_training_load`` — the
    weaker driver, of the wrong outcome — because the selection was hardcoded.
    """
    as_of = date(2026, 7, 5)
    outcomes = {
        # A strong load correlation, but against sleep score: not this flag's outcome.
        "sleep_score": [
            _driver(
                "prev_day_training_load",
                "sleep_score",
                -0.61,
                18,
                "Higher load nights averaged 5 points lower sleep score.",
            )
        ],
        # Batch 249: strong enough that its interval clears zero. The real -0.24
        # over 64 nights no longer qualifies, which is what
        # ``test_the_card_never_calls_a_correlation_the_strongest_lever`` pins.
        "rem_sleep_min": [
            _driver(
                "bedroom_warning_minutes",
                "rem_sleep_min",
                -0.44,
                64,
                "Nights with 60+ min above 19.5C average 4.6 min lower REM sleep.",
            ),
            _driver("prev_day_training_load", "rem_sleep_min", -0.08, 115),
        ],
    }

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.13),
        recovery_days=[],
        baselines={},
        driver_outcomes=outcomes,
        age=57,
        sex="male",
        sleep_protocol={"bedtime": "23:15", "sealTargetTime": "22:00"},
        as_of=as_of,
    )

    assert result.status == "active"
    suggestion = result.items[0]
    assert suggestion.metric_key == "rem_sleep_pct"
    assert suggestion.driver is not None
    assert suggestion.driver.driver == "bedroom_warning_minutes"
    assert suggestion.driver.sample_count == 64
    # The thermal driver selects the thermal lever, not a timing one.
    assert suggestion.rotation is not None
    assert "room_cool_late_cycles" in suggestion.rotation.intervention_ids
    assert any("pre-cool" in action for action in suggestion.actions)
    assert suggestion.evidence[0].startswith("28 of 28 measured nights")


def test_chronic_rem_suggestion_rotates_week_to_week() -> None:
    # A persistent REM miss now hands out a rotating slice of the wider library,
    # not the same static pair every week (Batch 72).
    week_one = date(2026, 7, 6)  # Monday
    week_two = week_one + timedelta(days=7)

    first = build_chronic_pattern_suggestions(
        sleeps=_nights(week_one, rem_pct=0.13),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=week_one,
    )
    second = build_chronic_pattern_suggestions(
        sleeps=_nights(week_two, rem_pct=0.13),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=week_two,
    )

    rem_one = first.items[0]
    rem_two = second.items[0]
    assert rem_one.metric_key == "rem_sleep_pct"
    assert rem_one.rotation is not None
    assert rem_one.rotation.shown == 2
    assert rem_one.rotation.total >= 8
    assert rem_one.rotation.period_label != rem_two.rotation.period_label  # type: ignore[union-attr]
    # The set actually rotates between the two weeks...
    assert rem_one.actions != rem_two.actions
    # ...and no longer emits the pre-Batch-72 static line.
    assert all(
        "latest normal lights-out target for the next week" not in action
        for action in rem_one.actions
    )


def test_chronic_rem_suggestion_reuses_the_exact_persisted_assignment() -> None:
    issued_on = date(2026, 7, 6)
    issued = build_chronic_pattern_suggestions(
        sleeps=_nights(issued_on, rem_pct=0.13),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=issued_on,
    ).items[0]
    assert issued.rotation is not None

    replay = build_chronic_pattern_suggestions(
        sleeps=_nights(issued_on + timedelta(days=7), rem_pct=0.13),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=issued_on + timedelta(days=7),
        rem_rotation=issued.rotation,
    ).items[0]

    assert replay.rotation == issued.rotation
    assert replay.actions == list(issued.rotation.actions)


def test_non_rem_suggestion_carries_no_rotation() -> None:
    as_of = date(2026, 7, 6)
    recovery_days = [
        RecoveryDay(
            calendar_date=as_of - timedelta(days=27 - offset),
            readiness_score=60,  # below the personal floor every night
            hrv_7_day_avg_ms=50,
            resting_heart_rate_bpm=45,
        )
        for offset in range(28)
    ]

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),  # REM healthy → not flagged
        recovery_days=recovery_days,
        baselines={
            "readiness_score": BaselineBand(
                metric_key="readiness_score",
                label="Readiness",
                lower_quartile=70,
                upper_quartile=84,
                median=78,
                mean=77,
                sample_count=28,
            )
        },
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
    )

    assert result.status == "active"
    readiness = next(item for item in result.items if item.metric_key == "readiness_score")
    assert readiness.rotation is None
    assert "Pair the suggestion with today's call; do not chase load." in readiness.actions
    assert result.action_signal.triggered is True
    assert result.action_signal.trigger_sources == ("sustained_recovery_marker",)
    assert result.action_signal.recovery_markers == ("readiness_score",)


def test_insufficient_history_is_explicit() -> None:
    as_of = date(2026, 7, 5)

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.13, count=6),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
    )

    assert result.status == "insufficient_history"
    assert result.evidence_window.nights_observed == 6
    assert "21 are needed" in result.summary


def test_clear_when_misses_do_not_repeat_enough() -> None:
    as_of = date(2026, 7, 5)
    sleeps = _nights(as_of, rem_pct=0.22)
    recovery_days = [
        RecoveryDay(
            calendar_date=as_of - timedelta(days=27 - offset),
            readiness_score=78,
            hrv_7_day_avg_ms=50,
            resting_heart_rate_bpm=45,
        )
        for offset in range(28)
    ]

    result = build_chronic_pattern_suggestions(
        sleeps=sleeps,
        recovery_days=recovery_days,
        baselines={
            "readiness_score": BaselineBand(
                metric_key="readiness_score",
                label="Readiness",
                lower_quartile=70,
                upper_quartile=84,
                median=78,
                mean=77,
                sample_count=28,
            )
        },
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
    )

    assert result.status == "clear"
    assert result.items == []


def test_single_bad_recovery_day_does_not_trigger_structural_action() -> None:
    as_of = date(2026, 7, 5)
    recovery_days = [
        RecoveryDay(
            calendar_date=as_of - timedelta(days=27 - offset),
            readiness_score=55 if offset == 27 else 78,
            hrv_7_day_avg_ms=50,
            resting_heart_rate_bpm=45,
        )
        for offset in range(28)
    ]

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=recovery_days,
        baselines={
            "readiness_score": BaselineBand(
                metric_key="readiness_score",
                label="Readiness",
                lower_quartile=70,
                upper_quartile=84,
                median=78,
                mean=77,
                sample_count=28,
            )
        },
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
    )

    assert result.action_signal.triggered is False
    assert result.action_signal.recovery_markers == ()
    assert result.action_signal.red_morning_count == 0


def test_two_unexplained_red_mornings_propose_rearrange_but_one_does_not() -> None:
    as_of = date(2026, 7, 5)
    common = {
        "sleeps": _nights(as_of, rem_pct=0.22),
        "recovery_days": [],
        "baselines": {},
        "driver_outcomes": {},
        "age": 57,
        "sex": "male",
        "sleep_protocol": {},
        "as_of": as_of,
    }
    one_red = build_chronic_pattern_suggestions(
        **common,
        recent_verdicts=[
            VerdictDay(calendar_date=as_of - timedelta(days=1), verdict="Red"),
            VerdictDay(calendar_date=as_of, verdict="Green"),
        ],
    )
    two_red = build_chronic_pattern_suggestions(
        **common,
        recent_verdicts=[
            VerdictDay(calendar_date=as_of - timedelta(days=6), verdict="Red"),
            VerdictDay(calendar_date=as_of - timedelta(days=1), verdict="red"),
            VerdictDay(calendar_date=as_of, verdict="Green"),
        ],
    )

    assert one_red.action_signal.triggered is False
    assert one_red.action_signal.red_morning_count == 1
    assert two_red.action_signal.triggered is True
    assert two_red.action_signal.trigger_sources == ("red_morning_cluster",)
    assert two_red.action_signal.kind == "rearrange_proposal"
    assert two_red.action_signal.red_morning_count == 2
    packet = two_red.action_signal.to_packet()
    assert packet["deliveryContract"] == "restructure_preview_apply"
    assert packet["humanApprovalRequired"] is True
    assert packet["verdictImpact"] == "none"


def test_training_debt_with_intact_markers_is_excluded_but_crashed_red_counts() -> None:
    as_of = date(2026, 8, 1)
    friday = as_of - timedelta(days=1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[
            VerdictDay(calendar_date=friday, verdict="Red"),
            VerdictDay(calendar_date=as_of, verdict="Red"),
        ],
        red_day_evidence={
            friday: RedDayEvidence(
                calendar_date=friday,
                recovery_time_min=2584,
                acute_load=198,
                hrv_ms=52,
                hrv_status="Balanced",
                hrv_floor_ms=43,
                resting_heart_rate_bpm=43,
                resting_hr_ceiling_bpm=46,
            ),
            as_of: RedDayEvidence(
                calendar_date=as_of,
                recovery_time_min=1370,
                acute_load=0,
                hrv_ms=35,
                hrv_status="Low",
                hrv_floor_ms=43,
                resting_heart_rate_bpm=48,
                resting_hr_ceiling_bpm=46,
            ),
        },
    )

    action = result.action_signal
    assert action.red_morning_observed_count == 2
    assert action.red_morning_count == 1
    assert action.triggered is False
    assert [item.classification for item in action.red_morning_qualifications] == [
        "expected_training_debt",
        "systemic_markers_strained",
    ]


def test_training_debt_needs_independent_load_corroboration() -> None:
    as_of = date(2026, 8, 1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=as_of, verdict="Red")],
        red_day_evidence={
            as_of: RedDayEvidence(
                calendar_date=as_of,
                recovery_time_min=2590,
                acute_load=None,
                hrv_ms=49,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=44,
                resting_hr_ceiling_bpm=45,
            )
        },
    )

    qualification = result.action_signal.red_morning_qualifications[0]
    assert qualification.counts_toward_cluster is True
    assert qualification.classification == "uncorroborated_training_debt"
    assert qualification.explanation_sources == (
        "recovery_debt",
        "missing_acute_load_corroboration",
    )


def test_training_debt_exclusion_is_capped_at_one_recent_red() -> None:
    as_of = date(2026, 8, 2)
    red_days = [as_of - timedelta(days=1), as_of]
    evidence = {
        day: RedDayEvidence(
            calendar_date=day,
            recovery_time_min=2590,
            acute_load=198,
            hrv_ms=49,
            hrv_status="Balanced",
            hrv_floor_ms=44,
            resting_heart_rate_bpm=44,
            resting_hr_ceiling_bpm=45,
        )
        for day in red_days
    }
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=day, verdict="Red") for day in red_days],
        red_day_evidence=evidence,
    )

    action = result.action_signal
    assert action.red_morning_count == 1
    assert [item.classification for item in action.red_morning_qualifications] == [
        "training_debt_exclusion_cap_reached",
        "expected_training_debt",
    ]
    packet = action.to_packet()
    assert packet["trainingDebtExclusionLimit"] == 1
    assert packet["trainingDebtExclusionMaxAgeDays"] == 2
    assert packet["redMorningExclusionLimit"] == 1
    assert packet["trainingDebtCorroboratingAcuteLoadMin"] == 1.0


def test_acute_and_training_debt_share_one_exclusion_cap() -> None:
    as_of = date(2026, 8, 2)
    acute_day = as_of - timedelta(days=1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[
            VerdictDay(calendar_date=acute_day, verdict="Red"),
            VerdictDay(calendar_date=as_of, verdict="Red"),
        ],
        red_day_evidence={
            acute_day: RedDayEvidence(
                calendar_date=acute_day,
                hrv_ms=49,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=44,
                resting_hr_ceiling_bpm=45,
                check_in_reasons=("alcohol",),
            ),
            as_of: RedDayEvidence(
                calendar_date=as_of,
                recovery_time_min=2590,
                acute_load=198,
                hrv_ms=49,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=44,
                resting_hr_ceiling_bpm=45,
            ),
        },
    )

    action = result.action_signal
    assert action.red_morning_count == 1
    assert [item.classification for item in action.red_morning_qualifications] == [
        "acute_exclusion_cap_reached",
        "expected_training_debt",
    ]


def test_training_debt_exclusion_expires_before_red_window() -> None:
    as_of = date(2026, 8, 5)
    red_day = as_of - timedelta(days=3)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=red_day, verdict="Red")],
        red_day_evidence={
            red_day: RedDayEvidence(
                calendar_date=red_day,
                recovery_time_min=2590,
                acute_load=198,
                hrv_ms=49,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=44,
                resting_hr_ceiling_bpm=45,
            )
        },
    )

    qualification = result.action_signal.red_morning_qualifications[0]
    assert qualification.counts_toward_cluster is True
    assert qualification.classification == "training_debt_exclusion_expired"


def test_acute_check_in_cannot_override_systemic_markers() -> None:
    as_of = date(2026, 8, 1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=as_of, verdict="Red")],
        red_day_evidence={
            as_of: RedDayEvidence(
                calendar_date=as_of,
                hrv_ms=35,
                hrv_status="Low",
                hrv_floor_ms=43,
                resting_heart_rate_bpm=48,
                resting_hr_ceiling_bpm=46,
                check_in_reasons=("alcohol",),
            )
        },
    )

    qualification = result.action_signal.red_morning_qualifications[0]
    assert qualification.classification == "acute_cause_with_systemic_strain"
    assert qualification.counts_toward_cluster is True
    assert result.action_signal.red_morning_count == 1


def test_endogenous_training_note_counts_even_with_intact_markers_and_debt() -> None:
    as_of = date(2026, 8, 1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=as_of, verdict="Red")],
        red_day_evidence={
            as_of: RedDayEvidence(
                calendar_date=as_of,
                recovery_time_min=2286,
                hrv_ms=52,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=43,
                resting_hr_ceiling_bpm=45,
                check_in_reasons=("training_load",),
            )
        },
    )

    qualification = result.action_signal.red_morning_qualifications[0]
    assert qualification.classification == "endogenous_training_signal"
    assert qualification.counts_toward_cluster is True
    packet = qualification.to_packet()
    assert packet["acuteExogenousReasons"] == []
    assert packet["endogenousTrainingReasons"] == ["training_load"]


def test_one_recent_acute_red_can_still_be_excluded_when_markers_are_intact() -> None:
    as_of = date(2026, 8, 1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=as_of, verdict="Red")],
        red_day_evidence={
            as_of: RedDayEvidence(
                calendar_date=as_of,
                hrv_ms=50,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=44,
                resting_hr_ceiling_bpm=45,
                check_in_reasons=("alcohol",),
            )
        },
    )

    qualification = result.action_signal.red_morning_qualifications[0]
    assert qualification.classification == "explained_by_acute_check_in"
    assert qualification.counts_toward_cluster is False
    packet = result.action_signal.to_packet()
    assert packet["acuteRedExclusionLimit"] == 1
    assert packet["acuteRedExclusionMaxAgeDays"] == 2


def test_acute_exclusion_is_capped_so_habitual_notes_cannot_silence_cluster() -> None:
    as_of = date(2026, 8, 3)
    red_days = [as_of - timedelta(days=offset) for offset in (2, 1, 0)]
    evidence = {
        day: RedDayEvidence(
            calendar_date=day,
            hrv_ms=50,
            hrv_status="Balanced",
            hrv_floor_ms=44,
            resting_heart_rate_bpm=44,
            resting_hr_ceiling_bpm=45,
            check_in_reasons=("alcohol",),
        )
        for day in red_days
    }
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=day, verdict="Red") for day in red_days],
        red_day_evidence=evidence,
    )

    action = result.action_signal
    assert action.red_morning_count == 2
    assert action.triggered is True
    assert [item.classification for item in action.red_morning_qualifications] == [
        "acute_exclusion_cap_reached",
        "acute_exclusion_cap_reached",
        "explained_by_acute_check_in",
    ]


def test_acute_exclusion_decays_before_the_red_window_closes() -> None:
    as_of = date(2026, 8, 6)
    red_days = [as_of - timedelta(days=4), as_of - timedelta(days=3)]
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=day, verdict="Red") for day in red_days],
        red_day_evidence={
            day: RedDayEvidence(
                calendar_date=day,
                hrv_ms=50,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=44,
                resting_hr_ceiling_bpm=45,
                check_in_reasons=("travel",),
            )
            for day in red_days
        },
    )

    action = result.action_signal
    assert action.red_morning_count == 2
    assert action.triggered is True
    assert all(
        item.classification == "acute_check_in_expired"
        for item in action.red_morning_qualifications
    )


@pytest.mark.parametrize(
    ("reasons", "expected_counts"),
    [
        ((), True),
        (("training_load",), True),
        (("deliberate_rest",), True),
        (("alcohol",), False),
        (("illness",), False),
        (("travel",), False),
    ],
)
def test_check_in_qualification_only_hardens_batch_182_behavior(
    reasons: tuple[str, ...], expected_counts: bool
) -> None:
    """A tag that Batch 182 counted still counts; former blanket exclusions may harden."""
    as_of = date(2026, 8, 1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[VerdictDay(calendar_date=as_of, verdict="Red")],
        red_day_evidence={
            as_of: RedDayEvidence(
                calendar_date=as_of,
                hrv_ms=50,
                hrv_status="Balanced",
                hrv_floor_ms=44,
                resting_heart_rate_bpm=44,
                resting_hr_ceiling_bpm=45,
                check_in_reasons=reasons,
            )
        },
    )

    qualification = result.action_signal.red_morning_qualifications[0]
    assert qualification.counts_toward_cluster is expected_counts
    assert result.action_signal.to_packet()["verdictImpact"] == "none"


def test_sustained_marker_deload_is_suppressed_by_scheduled_recovery_block() -> None:
    as_of = date(2026, 8, 1)
    recovery_days = [
        RecoveryDay(
            calendar_date=as_of - timedelta(days=27 - offset),
            readiness_score=50,
            hrv_7_day_avg_ms=50,
            resting_heart_rate_bpm=45,
        )
        for offset in range(28)
    ]
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=recovery_days,
        baselines={
            "readiness_score": BaselineBand(
                metric_key="readiness_score",
                label="Readiness",
                lower_quartile=70,
                upper_quartile=84,
                median=78,
                mean=77,
                sample_count=28,
            )
        },
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        scheduled_recovery_blocks=[
            ScheduledRecoveryBlock(
                name="PN2 W03 RECOVERY",
                block_type="recovery",
                start_date=date(2026, 8, 3),
                end_date=date(2026, 8, 9),
            )
        ],
    )

    action = result.action_signal
    assert action.kind == "deload_proposal"
    assert action.trigger_sources == ("sustained_recovery_marker",)
    assert action.suppressed_by_plan is True
    assert action.triggered is False
    assert "already schedules" in action.reasons[-1]


def test_red_cluster_rearrange_is_suppressed_by_scheduled_recovery_block() -> None:
    as_of = date(2026, 8, 1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recent_verdicts=[
            VerdictDay(calendar_date=as_of - timedelta(days=1), verdict="Red"),
            VerdictDay(calendar_date=as_of, verdict="Red"),
        ],
        scheduled_recovery_blocks=[
            ScheduledRecoveryBlock(
                name="PN2 W03 RECOVERY",
                block_type="recovery",
                start_date=date(2026, 8, 3),
                end_date=date(2026, 8, 9),
            )
        ],
    )

    assert result.action_signal.kind == "rearrange_proposal"
    assert result.action_signal.suppressed_by_plan is True
    assert result.action_signal.triggered is False


# Batch 297: the regular-expression classifier and its tests are retired. The causes
# now come from the notes reader's stored readings; Batch 212's bedroom notes and a
# real cold are tested there (``test_batch_297_notes_reader.py``) and in its eval.


def test_idle_chronic_action_is_not_narrated() -> None:
    """Batch 212: the prompt told the model to explain chronicAction and state its
    human-approval/verdictImpact fields, so it produced exactly that on a morning
    where nothing was triggered. Pinned to the version bump that carries it."""
    from src.services.morning_analysis import PROMPT_VERSION, SYSTEM_PROMPT

    assert PROMPT_VERSION.startswith("morning-analysis-v63")
    assert "chronicAction.triggered is false" in SYSTEM_PROMPT
    assert "internal bookkeeping with nothing to" in SYSTEM_PROMPT
    # The never-soften rule must survive the gate, not be replaced by it.
    assert "never soften or argue it down" in SYSTEM_PROMPT
    # Provenance is offered to the model, so a queried tag can be quoted back.
    assert "matchedText" in SYSTEM_PROMPT


def test_check_in_context_packet_carries_its_basis() -> None:
    """A check-in tag is explainable; a plan-derived one has no prose to quote."""
    from_check_in = RecordedTrainingContext(
        start_date=date(2026, 8, 14),
        end_date=date(2026, 8, 14),
        reason="illness",
        source="morning_check_in",
        matched_text="streaming cold",
    ).to_packet()
    assert from_check_in["matchedText"] == "streaming cold"
    assert (
        from_check_in["basis"] == "his words in the check-in note, as the notes reader quoted them"
    )

    from_plan = RecordedTrainingContext(
        start_date=date(2026, 8, 14),
        end_date=date(2026, 8, 20),
        reason="holiday",
        source="holiday_plan",
    ).to_packet()
    assert "matchedText" not in from_plan
    assert "basis" not in from_plan


# --- Batch 231: the lever follows the data ----------------------------------


_PROD_REM_OUTCOMES_2026_08_27 = {
    # The real stored ranking on the fourth morning the false statement fired.
    "rem_sleep_min": [
        _driver("bedroom_peak_fan_speed", "rem_sleep_min", 0.3449, 10),
        _driver("sleep_stress_avg", "rem_sleep_min", -0.2597, 121),
        _driver(
            "bedroom_warning_minutes",
            "rem_sleep_min",
            -0.2388,
            64,
            "Nights with 60+ min above 19.5C average 4.6 min lower REM sleep "
            "(42 such nights vs 22 without).",
        ),
        _driver("prev_day_training_load", "rem_sleep_min", -0.0783, 115),
    ],
    "sleep_score": [
        _driver("prev_day_training_load", "sleep_score", -0.0464, 115),
    ],
}


def _rem_flag_result(**overrides: object) -> ChronicSuggestionResult:
    kwargs: dict[str, object] = {
        "sleeps": _nights(date(2026, 8, 27), rem_pct=0.10),
        "recovery_days": [],
        "baselines": {},
        "driver_outcomes": _PROD_REM_OUTCOMES_2026_08_27,
        "age": 57,
        "sex": "male",
        "sleep_protocol": {},
        "as_of": date(2026, 8, 27),
    }
    kwargs.update(overrides)
    return build_chronic_pattern_suggestions(**kwargs)  # type: ignore[arg-type]


def test_the_card_never_calls_a_correlation_the_strongest_lever() -> None:
    """The exact sentence Mark read on 2026-08-25, -26, -27 and -28.

    ``prev_day_training_load`` carried -0.0464 over 115 nights in the very object
    that called it the strongest measured lever. Batch 231 stopped it winning;
    Batch 249 finds that on this packet *nothing* wins, because the best
    candidate's interval runs from -0.458 to +0.007 across 64 nights. The card
    says that rather than naming its least weak member.
    """
    result = _rem_flag_result()
    suggestion = next(item for item in result.items if item.metric_key == "rem_sleep_pct")

    assert "strongest measured lever" not in suggestion.summary
    assert "training load" not in suggestion.summary
    assert suggestion.driver is None
    assert "nothing measured tracks it closely enough" in suggestion.summary
    # The advice survives the claim being withdrawn.
    assert suggestion.actions


def test_the_named_driver_and_its_evidence_describe_the_same_measurement() -> None:
    """When a driver does qualify, the summary names it and the evidence sizes it."""
    result = _rem_flag_result(
        driver_outcomes={
            "rem_sleep_min": [
                _driver(
                    "bedroom_warning_minutes",
                    "rem_sleep_min",
                    -0.44,
                    64,
                    "Nights with 60+ min above 19.5C average 4.6 min lower REM sleep "
                    "(42 such nights vs 22 without).",
                ),
            ]
        }
    )
    suggestion = next(item for item in result.items if item.metric_key == "rem_sleep_pct")

    assert suggestion.driver is not None
    assert suggestion.driver.label in suggestion.summary
    assert "not a proven cause" in suggestion.summary
    # Batch 249: the sample and the interval moved out of the summary and into
    # the evidence, past the truncation cap, and no confidence word replaced them.
    assert suggestion.driver.evidence_sentence is not None
    assert any(f"{suggestion.driver.sample_count} nights" in line for line in suggestion.evidence)
    assert any("one side of no effect" in line for line in suggestion.evidence)
    assert "moderate" not in suggestion.summary
    assert suggestion.driver.to_dict()["adjustedCoefficient"] is None
    assert suggestion.driver.to_dict()["intervalLow"] is not None
    assert "confidence" not in suggestion.driver.to_dict()


def test_no_qualifying_driver_names_no_lever_at_all() -> None:
    result = _rem_flag_result(
        driver_outcomes={
            "rem_sleep_min": [
                _driver("prev_day_training_load", "rem_sleep_min", -0.05, 115),
            ]
        }
    )
    suggestion = next(item for item in result.items if item.metric_key == "rem_sleep_pct")

    assert suggestion.driver is None
    assert "nothing measured tracks it closely enough" in suggestion.summary
    # The rotation still runs: a weak driver removes the claim, not the advice.
    assert suggestion.actions


def test_a_confound_survives_the_evidence_cap() -> None:
    """Batch 230 lost a basis to a truncation; a caveat must not go the same way."""
    result = _rem_flag_result(
        driver_outcomes={
            "rem_sleep_min": [
                _driver(
                    "bedroom_fan_ran_minutes",
                    "rem_sleep_min",
                    -0.41,
                    55,
                    "Nights with the fan ran average 10.1 min lower REM sleep "
                    "(31 such nights vs 24 without).",
                ),
            ]
        }
    )
    suggestion = next(item for item in result.items if item.metric_key == "rem_sleep_pct")

    assert suggestion.driver is not None
    assert suggestion.driver.confounds
    assert any("because the room is already warm" in line for line in suggestion.evidence)


def test_a_recorded_habit_removes_the_lever_from_the_issued_card() -> None:
    habits = {"habits": [{"interventionIds": ["room_cool_late_cycles"]}]}
    result = _rem_flag_result(standing_habits=habits)
    suggestion = next(item for item in result.items if item.metric_key == "rem_sleep_pct")

    assert suggestion.rotation is not None
    assert "room_cool_late_cycles" not in suggestion.rotation.intervention_ids
    assert all("pre-cool to" not in action for action in suggestion.actions)


def test_a_persisted_batch_221_assignment_is_still_returned_verbatim() -> None:
    """Batch 221's evidence journal is untouched by the new selection.

    A stored weekly assignment must keep overriding the rotation, habits and
    driver notwithstanding — historical reads must never be rewritten.
    """
    pinned = RemRotation(
        period_label="2026-W35",
        shown=2,
        total=12,
        intervention_ids=("late_training_guard", "evening_light_down"),
        actions=("Keep hard or late rides off the evening.", "Dim screens before bed."),
    )
    result = _rem_flag_result(
        rem_rotation=pinned,
        standing_habits={"habits": [{"interventionIds": ["late_training_guard"]}]},
    )
    suggestion = next(item for item in result.items if item.metric_key == "rem_sleep_pct")

    assert suggestion.rotation == pinned
    assert list(pinned.actions) == suggestion.actions[-2:]


# --- Decision #429: nights away are counted apart from nights at home -------------

_HOLIDAY = RecordedTrainingContext(
    start_date=date(2026, 9, 27),
    end_date=date(2026, 10, 6),
    reason="holiday",
    source="holiday_plan",
)
_HRV_BASELINE = {
    "hrv_7_day_avg_ms": BaselineBand(
        metric_key="hrv_7_day_avg_ms",
        label="7-day average HRV",
        lower_quartile=45,
        upper_quartile=48,
        median=47,
        mean=46,
        sample_count=84,
    )
}
_HRV_OUTCOMES = {
    "recovery_hrv_ms": [
        _driver("bedroom_mean_temp_c", "recovery_hrv_ms", -0.30, 116, adjusted=-0.40),
    ]
}


def _low_hrv_days(as_of: date, low: set[date]) -> list[RecoveryDay]:
    """A synthetic 28-morning 7-day HRV series: 43 on ``low`` mornings, 46 otherwise."""
    return [
        RecoveryDay(
            calendar_date=day,
            hrv_7_day_avg_ms=43 if day in low else 46,
        )
        for day in (as_of - timedelta(days=27 - offset) for offset in range(28))
    ]


def _days(first: date, last: date) -> set[date]:
    return {first + timedelta(days=n) for n in range((last - first).days + 1)}


# The shape of 18 Oct 2026, not its values: 18 low mornings of 28, seven before the
# holiday (21–27 Sep), five on its last nights (2–6 Oct) and six in the week after it,
# while the 7-day average still held its nights (7–12 Oct).
_AS_OF_18_OCT = date(2026, 10, 18)
_LOW_18_OCT = _days(date(2026, 9, 21), date(2026, 9, 27)) | _days(
    date(2026, 10, 2), date(2026, 10, 12)
)


def _hrv_card(**overrides: object) -> tuple[ChronicSuggestion, ChronicSuggestionResult]:
    kwargs: dict[str, object] = {
        "sleeps": _nights(_AS_OF_18_OCT, rem_pct=0.22),  # REM healthy: one card only
        "recovery_days": _low_hrv_days(_AS_OF_18_OCT, _LOW_18_OCT),
        "baselines": _HRV_BASELINE,
        "driver_outcomes": _HRV_OUTCOMES,
        "age": 57,
        "sex": "male",
        "sleep_protocol": {"sealTargetTime": "22:00"},
        "as_of": _AS_OF_18_OCT,
        "recorded_training_context": [_HOLIDAY],
    }
    kwargs.update(overrides)
    result = build_chronic_pattern_suggestions(**kwargs)  # type: ignore[arg-type]
    return next(item for item in result.items if item.metric_key == "hrv_7_day_avg_ms"), result


def test_a_holiday_and_the_week_its_nights_stay_in_the_average_count_as_away() -> None:
    """The 18 Oct 2026 card, rebuilt from its shape: it says where the misses fell."""
    card, result = _hrv_card()

    assert card.title == "Protect recovery markers"
    assert card.evidence[0] == "On 18 of 28 mornings the 7-day average missed personal floor 45."
    assert card.evidence[1] == (
        "11 of those 18 averages still included nights you recorded as away (a holiday "
        "or travel); of the 13 mornings whose whole week was at home, 7 missed it."
    )
    assert card.summary == (
        "7-day average HRV has repeatedly missed its personal baseline, but mostly around "
        "time away: 11 of the 18 missed averages still included nights you recorded as "
        "away. A pattern made mostly of time away says little about home, so no single "
        "lever is named."
    )
    # Temperature is not presented as the thing to change, and neither is anything else.
    assert card.driver is None
    assert all("Bedroom" not in action for action in card.actions)
    assert card.actions == ["Pair the suggestion with today's call; do not chase load."]
    assert card.to_dict()["recordedAway"] == {
        "nightsPerReading": 7,
        "awaySamples": 15,
        "awayMisses": 11,
        "homeSamples": 13,
        "homeMisses": 7,
        "mostMissesAway": True,
        "basis": "holiday nights and travel check-ins; a reading is away if any night in it was",
    }
    # Counted, not subtracted: the tone still reads all 18 of 28.
    assert card.tone == "watch"
    assert result.action_signal.triggered is False


def test_without_a_recorded_holiday_the_same_card_names_its_lever() -> None:
    card, _ = _hrv_card(recorded_training_context=[])

    assert card.driver is not None
    assert card.driver.label == "bedroom temperature"
    assert "bedroom temperature tracks it most closely" in card.summary
    assert "bedroom mean temp c" not in card.summary
    assert len(card.evidence) == 3
    assert card.evidence[0] == "On 18 of 28 mornings the 7-day average missed personal floor 45."
    assert card.to_dict()["recordedAway"] is None
    assert any("Check Bedroom" in action for action in card.actions)


def test_nights_away_before_the_window_still_count_in_a_seven_day_reading() -> None:
    """The service passes away nights from six days before the window for this case."""
    as_of = date(2026, 10, 18)
    first = as_of - timedelta(days=27)
    card, _ = _hrv_card(
        recovery_days=_low_hrv_days(as_of, _days(first, first + timedelta(days=13))),
        recorded_training_context=[],
        away_nights={first - timedelta(days=3)},
    )

    # Mornings 1–4 of the window still average the night three days before it.
    assert card.to_dict()["recordedAway"]["awaySamples"] == 4
    assert card.to_dict()["recordedAway"]["awayMisses"] == 4
    assert card.evidence[1].startswith("4 of those 14 averages still included nights")
    assert card.driver is not None  # 4 of 14 is not most


def test_a_minority_of_misses_away_keeps_the_lever_and_reports_the_split() -> None:
    as_of = date(2026, 8, 27)
    holiday = RecordedTrainingContext(
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 15),
        reason="holiday",
        source="holiday_plan",
    )
    result = _rem_flag_result(
        driver_outcomes={
            "rem_sleep_min": [
                _driver(
                    "bedroom_warning_minutes",
                    "rem_sleep_min",
                    -0.44,
                    64,
                    "Nights with 60+ min above 19.5C average 4.6 min lower REM sleep "
                    "(42 such nights vs 22 without).",
                ),
            ]
        },
        recorded_training_context=[holiday],
        as_of=as_of,
    )
    card = next(item for item in result.items if item.metric_key == "rem_sleep_pct")

    assert card.evidence[0] == "28 of 28 measured nights missed healthy 50–59 range 15–23%."
    assert card.evidence[1] == (
        "5 of those 28 were nights you recorded as away (a holiday or travel); of the 23 "
        "nights at home, 23 missed it."
    )
    assert card.driver is not None
    assert "tracks it most closely" in card.summary
    # The driver's own lines keep their places after the split.
    assert card.evidence[3].startswith("Nights with 60+ min above 19.5C")


def test_a_travel_check_in_marks_its_own_night_and_other_contexts_mark_none() -> None:
    travel_on = date(2026, 8, 20)
    contexts = [
        RecordedTrainingContext(
            start_date=travel_on,
            end_date=travel_on,
            reason="travel",
            source="morning_check_in",
            matched_text="synthetic",
        ),
        RecordedTrainingContext(
            start_date=date(2026, 8, 21),
            end_date=date(2026, 8, 21),
            reason="alcohol",
            source="morning_check_in",
            matched_text="synthetic",
        ),
        RecordedTrainingContext(
            start_date=date(2026, 8, 22),
            end_date=date(2026, 8, 22),
            reason="illness",
            source="symptom_answer",
            matched_text="A cold",
        ),
    ]
    card = next(
        item
        for item in _rem_flag_result(recorded_training_context=contexts).items
        if item.metric_key == "rem_sleep_pct"
    )

    assert card.to_dict()["recordedAway"]["awaySamples"] == 1
    assert card.evidence[1] == (
        "1 of those 28 was a night you recorded as away (a holiday or travel); of the 27 "
        "nights at home, 27 missed it."
    )


def test_away_nights_with_no_miss_among_them_say_so() -> None:
    as_of = date(2026, 10, 18)
    # Lows only in the last two weeks; the holiday's averages all held.
    low = _days(as_of - timedelta(days=13), as_of)
    holiday = RecordedTrainingContext(
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 24),
        reason="holiday",
        source="holiday_plan",
    )
    card, _ = _hrv_card(
        recovery_days=_low_hrv_days(as_of, low), recorded_training_context=[holiday]
    )

    assert card.evidence[1] == (
        "None of those 14 averages included nights you recorded as away (a holiday or "
        "travel); of the 19 mornings whose whole week was at home, 14 missed it."
    )
    assert card.driver is not None


def test_counting_nights_away_removes_no_caution() -> None:
    """A deload signal fed entirely by holiday mornings still fires, at the same tone."""
    as_of = date(2026, 7, 6)
    recovery_days = [
        RecoveryDay(
            calendar_date=as_of - timedelta(days=27 - offset),
            readiness_score=60,
            hrv_7_day_avg_ms=50,
            resting_heart_rate_bpm=45,
        )
        for offset in range(28)
    ]
    holiday = RecordedTrainingContext(
        start_date=as_of - timedelta(days=28),
        end_date=as_of,
        reason="holiday",
        source="holiday_plan",
    )
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=recovery_days,
        baselines={
            "readiness_score": BaselineBand(
                metric_key="readiness_score",
                label="Readiness",
                lower_quartile=70,
                upper_quartile=84,
                median=78,
                mean=77,
                sample_count=28,
            )
        },
        driver_outcomes={},
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
        recorded_training_context=[holiday],
    )
    readiness = next(item for item in result.items if item.metric_key == "readiness_score")

    assert readiness.tone == "protect"
    assert readiness.to_dict()["recordedAway"]["mostMissesAway"] is True
    assert "28 of the 28 misses were nights you recorded as away" in readiness.summary
    assert result.action_signal.triggered is True
    assert result.action_signal.trigger_sources == ("sustained_recovery_marker",)
