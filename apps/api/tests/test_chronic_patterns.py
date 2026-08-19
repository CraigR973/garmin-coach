from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.services.chronic_patterns import (
    BaselineBand,
    RecordedTrainingContext,
    RecoveryDay,
    RedDayEvidence,
    ScheduledRecoveryBlock,
    SleepNight,
    VerdictDay,
    build_chronic_pattern_suggestions,
    classify_check_in_cause_matches,
    classify_check_in_causes,
)
from src.services.insights import DriverCorrelation


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
    as_of = date(2026, 7, 5)
    drivers = [
        DriverCorrelation(
            driver="prev_day_training_load",
            outcome="sleep_score",
            coefficient=-0.61,
            sample_count=18,
            summary="Higher load nights averaged 5 points lower sleep score.",
        )
    ]

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.13),
        recovery_days=[],
        baselines={},
        sleep_drivers=drivers,
        age=57,
        sex="male",
        sleep_protocol={"bedtime": "23:15", "sealTargetTime": "22:00"},
        as_of=as_of,
    )

    assert result.status == "active"
    suggestion = result.items[0]
    assert suggestion.metric_key == "rem_sleep_pct"
    assert suggestion.driver is not None
    assert suggestion.driver.driver == "prev_day_training_load"
    assert "high-load" in suggestion.actions[0]
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
        sleep_drivers=[],
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=week_one,
    )
    second = build_chronic_pattern_suggestions(
        sleeps=_nights(week_two, rem_pct=0.13),
        recovery_days=[],
        baselines={},
        sleep_drivers=[],
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
        sleep_drivers=[],
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
    )

    assert result.status == "active"
    readiness = next(item for item in result.items if item.metric_key == "readiness_score")
    assert readiness.rotation is None
    assert (
        "Pair the suggestion with the existing Green/Amber/Red read; do not chase load."
        in readiness.actions
    )
    assert result.action_signal.triggered is True
    assert result.action_signal.trigger_sources == ("sustained_recovery_marker",)
    assert result.action_signal.recovery_markers == ("readiness_score",)


def test_insufficient_history_is_explicit() -> None:
    as_of = date(2026, 7, 5)

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.13, count=6),
        recovery_days=[],
        baselines={},
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        "sleep_drivers": [],
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
        sleep_drivers=[],
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


def test_acute_check_in_cannot_override_systemic_markers() -> None:
    as_of = date(2026, 8, 1)
    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.22),
        recovery_days=[],
        baselines={},
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        sleep_drivers=[],
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
        sleep_drivers=[],
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


def test_check_in_cause_classifier_captures_marks_words_and_respects_negation() -> None:
    assert classify_check_in_causes(
        "Have a bit of a hangover today",
        "Was out last night drinking, around 13 UK units.",
    ) == ("alcohol",)
    assert classify_check_in_causes(
        None,
        "Presumably due to a harder day's training yesterday and cumulative 3 day training load.",
    ) == ("training_load",)
    assert classify_check_in_causes(None, "No alcohol and not feeling ill.") == ()


# --- Batch 212: the classifier reads prose, so over-match is a coaching defect ---

# Mark's own words, copied verbatim from `coach.manual_entries` for the two
# mornings that produced the phantom "illness context" he queried on 2026-08-14.
# Both are about his bedroom. Neither may ever tag illness again.
MARK_2026_08_14_NOTE = (
    "Tried sleeping with just single sheet rather than quilt which made big "
    "difference and experiment worked with very good sleep up until 05:45. Only "
    "downside was weather changed and with windows open and just sheet meant more "
    "awake from this time as felt cold from drafts."
)
MARK_2026_08_15_NOTE = (
    "Did good job cooling room to 17° but tried experiment of sleeping just with "
    "thin quilt cover instead of quilt again. Also kept one window on each side of "
    "room open 10cm with blind out from windowsill. This backfired as too cold and "
    "at 02:50 had to change to quilt. Not sure if due to temp or draught as wind "
    "was at angle cold air coming more directly into room."
)


@pytest.mark.parametrize(
    ("feel", "notes"),
    [
        ("Feel good this morning", MARK_2026_08_14_NOTE),
        ("Overall good sleep in circumstances in notes.", MARK_2026_08_15_NOTE),
    ],
)
def test_a_cold_bedroom_is_never_an_illness(feel: str, notes: str) -> None:
    """The regression Mark actually hit: both notes classified as `illness`."""
    assert classify_check_in_causes(feel, notes) == ()


@pytest.mark.parametrize(
    "notes",
    [
        "Woke up with a head cold.",
        "Streaming cold all day, throat is raw.",
        "Think I've caught a cold from the grandkids.",
        "Feeling properly unwell today.",
        "Off with a chest infection.",
        "Man flu, apparently.",
        "Was sick twice in the night.",
    ],
)
def test_genuine_illness_phrasings_still_tag(notes: str) -> None:
    assert classify_check_in_causes(None, notes) == ("illness",)


@pytest.mark.parametrize(
    ("cause", "notes"),
    [
        # One negative control per cause family — the neighbouring subject most
        # likely to appear in a real recovery note for each.
        ("illness", "Room was cold so slept badly, and the wind was cold too."),
        ("illness", "Bit sick of this weather to be honest."),
        ("alcohol", "Been drinking plenty of water and lots of squash all day."),
        ("alcohol", "Drank a lot of water before bed."),
        ("travel", "Slept in my own bed as usual, no travel this week."),
        ("deliberate_rest", "Busy day but no rest at all."),
        ("training_load", "Easy spin, nothing hard about it."),
    ],
)
def test_cause_family_negative_controls(cause: str, notes: str) -> None:
    assert cause not in classify_check_in_causes(None, notes)


def test_alcohol_still_tags_when_the_drink_is_alcoholic() -> None:
    """The hydration guard must not blunt the real signal."""
    assert classify_check_in_causes(None, "Was drinking wine with dinner.") == ("alcohol",)
    assert classify_check_in_causes(None, "Drank a couple of beers.") == ("alcohol",)


def test_matched_phrase_is_carried_so_a_tag_can_explain_itself() -> None:
    """Provenance: the coach could not say *why* the illness tag existed."""
    matches = classify_check_in_cause_matches(None, "Woke up with a streaming cold.")
    assert matches == (("illness", "streaming cold"),)
    assert classify_check_in_causes(None, "Woke up with a streaming cold.") == ("illness",)


def test_idle_chronic_action_is_not_narrated() -> None:
    """Batch 212: the prompt told the model to explain chronicAction and state its
    human-approval/verdictImpact fields, so it produced exactly that on a morning
    where nothing was triggered. Pinned to the version bump that carries it."""
    from src.services.morning_analysis import PROMPT_VERSION, SYSTEM_PROMPT

    assert PROMPT_VERSION.startswith("morning-analysis-v32")
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
    assert from_check_in["basis"] == "phrase matched in the check-in note"

    from_plan = RecordedTrainingContext(
        start_date=date(2026, 8, 14),
        end_date=date(2026, 8, 20),
        reason="holiday",
        source="holiday_plan",
    ).to_packet()
    assert "matchedText" not in from_plan
    assert "basis" not in from_plan
