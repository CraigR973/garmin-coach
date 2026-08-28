"""Batch 230 — every figure on the morning brief reconciles from what it shows.

Mark's 2026-08-26 wave was four reports about numbers he could not check. His
watch showed REM **48 min against a displayed 7h33m** — 10.6% — while the brief
said "9.8% of sleep", a share of a total that silently includes 35 min awake.
The metrics table printed HRV **45–49**, printed **50**, and said "in range".
The drain row was the tallest in a table headed "Last night's metrics", carried
no value, and described *today*. And REM rendered "✓ in range" with no age band
anywhere on the brief, while the trends narrative — same day, same data — called
it "not a deficit" and "not a structural concern".

Nothing here changes a measurement. Every case pins what the app is allowed to
*say* about one, and 230.4 pins the denominator so the batch cannot drift into
changing one by accident.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from src.models.coaching import DailyMetric, MetricBaseline, Sleep
from src.models.profile import Profile
from src.services.age_norms import (
    REM_FRAMING_RULE,
    REM_PCT_BASIS,
    SLEEP_STAGE_MINUTES_RULE,
    SLEEP_STAGE_PCT_BASIS,
    SLEEP_STAGE_PCT_BASIS_NOTE,
    age_band_label,
    build_age_comparison,
    measured_sleep_sec,
    rem_sleep_pct_for_row,
    sleep_stage_band,
)
from src.services.morning_analysis import SYSTEM_PROMPT as MORNING_SYSTEM_PROMPT
from src.services.morning_analysis import _age_comparison, _metrics_vs_baselines
from src.services.trends import (
    BUCKET_MONTH,
    TREND_SYSTEM_PROMPT,
    YearOnYearComparison,
    _build_packet,
)

# Mark's night of 2026-08-26, exactly as Garmin stored it and exactly as his two
# screenshots show it: score 79 FAIR, Duration 7h33m, Deep 1h49m, Light 4h56m,
# REM 48m, Awake 35m, 47 restless. Every claim below is checked against the one
# night he audited, not a convenient invention.
_NIGHT = dict(
    duration_sec=27180,
    deep_sleep_sec=6540,
    light_sleep_sec=17760,
    rem_sleep_sec=2880,
    awake_sleep_sec=2100,
    restless_moments_count=47,
    score=79,
)


def _sleep(user_id: uuid.UUID, subject_date: date) -> Sleep:
    return Sleep(user_id=user_id, calendar_date=subject_date, **_NIGHT)


def _baseline(
    user_id: uuid.UUID,
    metric_key: str,
    label: str,
    *,
    median: float,
    lower: float,
    upper: float,
    sample_count: int = 84,
) -> MetricBaseline:
    return MetricBaseline(
        user_id=user_id,
        metric_key=metric_key,
        metric_label=label,
        source="db_history",
        window_start_date=date(2026, 6, 4),
        window_end_date=date(2026, 8, 26),
        sample_count=sample_count,
        excluded_sample_count=0,
        mean_value=median,
        median_value=median,
        lower_quartile_value=lower,
        upper_quartile_value=upper,
    )


def _rem_baseline(user_id: uuid.UUID) -> MetricBaseline:
    """The stored row, to the digit: n=84, median 9.908, IQR 7.504–13.118."""
    return _baseline(
        user_id,
        "rem_sleep_pct",
        "REM sleep",
        median=9.908234126984127,
        lower=7.5041490814023,
        upper=13.11771939725243,
    )


def _knowledge_base() -> dict[str, object]:
    return {"profile": {"age": 57, "sex": "male"}}


# --- 230.1 / 230.3: the REM row says which total, and against which band ------


def test_the_rem_row_carries_both_frames_and_its_basis() -> None:
    """The defect Mark saw: "✓ in range" and nothing else, on the one metric he
    has raised in three separate feedback waves. Personal *and* population, plus
    the denominator, on the row itself — so the read cannot be kinder than the
    evidence by omitting half of it."""
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 26)
    sleep = _sleep(user_id, subject_date)
    age_comparison = _age_comparison(None, sleep, _knowledge_base())

    rows = {
        row["metricKey"]: row
        for row in _metrics_vs_baselines(
            None,
            sleep,
            [_rem_baseline(user_id)],
            None,
            age_comparison=age_comparison,
        )
    }
    rem = rows["rem_sleep_pct"]

    # His own frame: 9.84% against a median of 9.91 — a near-median night.
    assert rem["currentValue"] == rem_sleep_pct_for_row(sleep)
    assert round(rem["currentValue"], 2) == 9.84
    assert rem["deltaVsBaseline"] == -0.07

    # The population frame, from the same computed row the Sleep page renders.
    assert rem["ageFrame"] == {
        "ageBand": "50–59",
        "bandLow": 15,
        "bandHigh": 23,
        "unit": "%",
        "tone": "warn",
        "descriptor": "Below the healthy range for your age",
    }

    # And the denominator, in words, beside the number it divides by.
    assert rem["basis"] == SLEEP_STAGE_PCT_BASIS
    assert "measured sleep" in rem["basis"]
    assert "awake" in rem["basis"]


def test_the_denominator_is_named_in_a_packet_not_only_in_a_constant() -> None:
    """Renamed from Batch 227's `test_the_denominator_is_named_where_the_number_is
    _surfaced`, which asserted only ``REM_PCT_BASIS``'s own wording. The constant
    existed and reached no packet, so the model was handed a bare
    ``9.836065573770492`` and wrote "9.8% of sleep" — and the test whose name
    promised to catch exactly that passed the whole time."""
    user_id = uuid.uuid4()
    sleep = _sleep(user_id, date(2026, 8, 26))

    rows = _metrics_vs_baselines(
        None,
        sleep,
        [_rem_baseline(user_id)],
        None,
        age_comparison=_age_comparison(None, sleep, _knowledge_base()),
    )
    rem = next(row for row in rows if row["metricKey"] == "rem_sleep_pct")

    # The percentage never travels without the total it is a percentage of.
    assert rem["currentValue"] is not None
    assert rem.get("basis")
    # The developer-facing constant still agrees with the shipped one.
    assert "measured sleep" in REM_PCT_BASIS


def test_every_stage_percentage_shares_one_named_denominator() -> None:
    """229.6, folded in: the gap was never REM's alone. The 2026-08-27 brief
    printed Deep 17.3%, Light 63.8%, Awake 8.1% and REM 10.9% on four adjacent
    lines under the identical denominator, and not one of them said so."""
    comparison = build_age_comparison(
        age=57,
        sex="male",
        vo2max=None,
        resting_heart_rate_bpm=None,
        hrv_overnight_ms=None,
        fitness_age=None,
        duration_sec=_NIGHT["duration_sec"],
        deep_sleep_sec=_NIGHT["deep_sleep_sec"],
        light_sleep_sec=_NIGHT["light_sleep_sec"],
        rem_sleep_sec=_NIGHT["rem_sleep_sec"],
        awake_sleep_sec=_NIGHT["awake_sleep_sec"],
        restless_moments_count=_NIGHT["restless_moments_count"],
    ).to_dict()

    assert comparison["sleepStagePctBasis"] == SLEEP_STAGE_PCT_BASIS_NOTE

    measured = measured_sleep_sec(
        _NIGHT["deep_sleep_sec"],
        _NIGHT["light_sleep_sec"],
        _NIGHT["rem_sleep_sec"],
        _NIGHT["awake_sleep_sec"],
    )
    by_key = {row["metricKey"]: row for row in comparison["sleepRows"]}
    for metric_key, stage_sec in (
        ("deep_sleep_pct", _NIGHT["deep_sleep_sec"]),
        ("light_sleep_pct", _NIGHT["light_sleep_sec"]),
        ("rem_sleep_pct", _NIGHT["rem_sleep_sec"]),
        ("awake_sleep_pct", _NIGHT["awake_sleep_sec"]),
    ):
        assert by_key[metric_key]["value"] == round(stage_sec / measured * 100.0, 1)

    # And none of the four divides into what Mark's watch displays: his 48 REM
    # minutes over a shown 7h33m is 10.6%, the app's share of measured sleep 9.8%.
    assert round(_NIGHT["rem_sleep_sec"] / _NIGHT["duration_sec"] * 100, 1) == 10.6
    assert round(_NIGHT["rem_sleep_sec"] / measured * 100, 1) == 9.8


# --- 230.7: the defect class, not this instance ------------------------------


def test_the_morning_and_trends_prompts_cannot_disagree_about_rem() -> None:
    """The real defect is cross-surface. On 2026-08-26 the brief called REM a
    chronic pattern with 21 of 28 nights below the band, while the trends
    narrative — the same day, the same data — concluded "not a deficit", "not a
    structural concern", "No concern here." Two prompts paraphrasing one rule
    will always be one edit from disagreeing again, so both embed the rule
    itself and this pins that they do."""
    assert REM_FRAMING_RULE in MORNING_SYSTEM_PROMPT
    assert REM_FRAMING_RULE in TREND_SYSTEM_PROMPT

    # The conclusions that produced the contradiction are named and forbidden.
    for banned in ('"no concern"', '"not a deficit"', '"not a structural concern"'):
        assert banned in REM_FRAMING_RULE
    assert "normal for him AND below the band" in REM_FRAMING_RULE

    # A value can be both, and the read must say both rather than pick one.
    assert "ALWAYS give the age band too, with its numbers" in REM_FRAMING_RULE

    # 2026-08-27: the brief called the app's own 50–59 band "the Garmin flag …
    # a younger-adult band of 15–23%" while Garmin's actual target of 21–31%
    # sat in the same packet. Dismissing the band by misattributing it.
    assert "never" in REM_FRAMING_RULE
    assert "attribute the app's band to Garmin" in REM_FRAMING_RULE

    # Minutes lead, but only where a night has minutes — a monthly mean has none.
    assert SLEEP_STAGE_MINUTES_RULE in MORNING_SYSTEM_PROMPT
    assert SLEEP_STAGE_MINUTES_RULE not in TREND_SYSTEM_PROMPT


def test_the_trends_packet_carries_rems_own_baseline() -> None:
    """230.2. The prompt told the model to interpret REM against
    ``personalBaselines`` and the packet did not contain it, so the v6 narrative
    cited "median 12.55% in March" — the highest month of the displayed window.
    The same narrative quoted readiness, RHR and HRV correctly, because those
    three were in the key set. The anchor was never a tone failure."""
    user_id = uuid.uuid4()
    player = Profile(id=user_id, display_name="Mark", timezone="Europe/London")
    packet = _build_packet(
        player=player,
        bucket=BUCKET_MONTH,
        comparison=YearOnYearComparison(
            bucket=BUCKET_MONTH,
            status="ok",
            current_key="2026-08",
            prior_key="2025-08",
            current_label="August 2026",
            prior_label="August 2025",
            metrics=[],
            reasons=[],
        ),
        windows=[],
        guardrails=[],
        baselines=[
            _rem_baseline(user_id),
            _baseline(
                user_id,
                "readiness_score",
                "Training readiness",
                median=61,
                lower=42.75,
                upper=71.25,
            ),
        ],
    )

    # The band the prompt is required to state travels with it, so this fix does
    # not repeat the defect it exists to correct — an instruction pointing at a
    # number the packet does not contain.
    assert packet["remAgeBand"] is None  # no profile age passed in this unit case

    rem = packet["personalBaselines"]["rem_sleep_pct"]
    assert rem["median"] == 9.908234126984127
    assert rem["lowerQuartile"] == 7.5041490814023
    assert rem["upperQuartile"] == 13.11771939725243
    assert rem["sampleCount"] == 84
    # The three that were already there stay there.
    assert "readiness_score" in packet["personalBaselines"]

    # And when the profile age is known, the band is the same one the morning
    # read quotes — 15–23% for the 50–59 band — carrying the shared denominator.
    with_band = _build_packet(
        player=player,
        bucket=BUCKET_MONTH,
        comparison=YearOnYearComparison(
            bucket=BUCKET_MONTH,
            status="ok",
            current_key="2026-08",
            prior_key="2025-08",
            current_label="August 2026",
            prior_label="August 2025",
            metrics=[],
            reasons=[],
        ),
        windows=[],
        guardrails=[],
        baselines=[_rem_baseline(user_id)],
        rem_age_band={
            "metricKey": "rem_sleep_pct",
            "ageBand": age_band_label(57),
            "bandLow": sleep_stage_band("rem_sleep_pct", 57, "male")[0],
            "bandHigh": sleep_stage_band("rem_sleep_pct", 57, "male")[1],
            "unit": "%",
            "basis": SLEEP_STAGE_PCT_BASIS_NOTE,
        },
    )
    assert with_band["remAgeBand"]["ageBand"] == "50\u201359"
    assert with_band["remAgeBand"]["bandLow"] == 15
    assert with_band["remAgeBand"]["bandHigh"] == 23
    assert "measured sleep" in with_band["remAgeBand"]["basis"]
    # The trends prompt now points at that field by name.
    assert "remAgeBand" in TREND_SYSTEM_PROMPT


# --- 230.4: the labelling batch does not move a measurement -------------------


def test_the_stage_denominator_is_still_measured_sleep() -> None:
    """Regression, so this batch cannot quietly become the one that swaps it.
    Measured over 429 nights, moving to Garmin's Duration degrades three of four
    stage flags — Light's in-band nights halve (130/429 → 65/429, 77 verdicts
    flipped) and Deep flips 51 — because the Batch 61 bands and the measured-sleep
    denominator are a matched pair. Reopening it is a Batch 61 decision with its
    own DECISIONS entry, and awake cannot share a total-sleep-time denominator
    meaningfully in any case."""
    sleep = _sleep(uuid.uuid4(), date(2026, 8, 26))
    measured = measured_sleep_sec(
        sleep.deep_sleep_sec, sleep.light_sleep_sec, sleep.rem_sleep_sec, sleep.awake_sleep_sec
    )

    assert measured == 29280
    assert measured == sleep.duration_sec + sleep.awake_sleep_sec
    assert rem_sleep_pct_for_row(sleep) == sleep.rem_sleep_sec / measured * 100.0
    # Explicitly *not* Garmin's displayed Duration.
    assert rem_sleep_pct_for_row(sleep) != sleep.rem_sleep_sec / sleep.duration_sec * 100.0


# --- 230.5: the drain row describes a day that has finished ------------------


def _morning_row(user_id: uuid.UUID, subject_date: date) -> DailyMetric:
    return DailyMetric(
        user_id=user_id,
        calendar_date=subject_date,
        phase="morning",
        body_battery_charged=70,
        body_battery_drained=12,
        raw_payload={
            "body_battery": {
                "charged": 70,
                "drained": 12,
                "startTimestampLocal": f"{subject_date.isoformat()}T00:00:00.0",
                "endTimestampLocal": f"{subject_date.isoformat()}T08:08:00.0",
            }
        },
    )


def test_the_drain_row_describes_the_last_finished_day() -> None:
    """Mark's ask. The row was the tallest in the table, held no value, and told
    him to wait for a comparison that was already on the same page in Batch 226's
    prose. Batch 226.2's constraint is real but applies only to *today*:
    yesterday's settled row exists, and `_yesterday_load_packet` has already
    computed its drain — so the table quotes that figure rather than deriving a
    second one, and the two surfaces cannot disagree about one day."""
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 27)
    baselines = [
        _baseline(
            user_id,
            "body_battery_drain",
            "Body Battery drain",
            median=67,
            lower=57.5,
            upper=74.5,
        )
    ]

    rows = {
        row["metricKey"]: row
        for row in _metrics_vs_baselines(
            _morning_row(user_id, subject_date),
            None,
            baselines,
            None,
            closed_day_cost={
                "calendarDate": (subject_date - timedelta(days=1)).isoformat(),
                "bodyBatteryDrained": 73,
            },
        )
    }
    drain = rows["body_battery_drain"]

    assert drain["currentValue"] == 73
    assert drain["deltaVsBaseline"] == 6.0
    assert "unavailableReason" not in drain
    # It says which day, so the row is self-describing under a "Last night's
    # metrics" heading that is otherwise about the night.
    assert drain["basis"] == (
        "Your last finished day (26 Aug) — drain is a whole-day figure, so it is "
        "shown once the day has closed."
    )


def test_batch_224s_withhold_survives_where_there_is_no_finished_day() -> None:
    """The part-day value must still never meet a full-day baseline. Batch 224's
    reason is unchanged, byte for byte, for the case it was written for."""
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 27)
    baselines = [
        _baseline(
            user_id,
            "body_battery_drain",
            "Body Battery drain",
            median=67,
            lower=57.5,
            upper=74.5,
        )
    ]

    for closed_day_cost in (
        None,
        {"calendarDate": "2026-08-26", "bodyBatteryDrained": None},
        # An incomplete Garmin window already gates the value to None upstream.
        {"calendarDate": None, "bodyBatteryDrained": None},
    ):
        rows = {
            row["metricKey"]: row
            for row in _metrics_vs_baselines(
                _morning_row(user_id, subject_date),
                None,
                baselines,
                None,
                closed_day_cost=closed_day_cost,
            )
        }
        drain = rows["body_battery_drain"]
        assert drain["currentValue"] is None
        assert drain["unavailableReason"] == (
            "This drain is still a part-day value at the morning sync; compare it with your "
            "full-day baseline after the day closes."
        )
        assert "basis" not in drain


def test_todays_settled_row_still_wins_over_the_closed_day() -> None:
    """Once the subject date has closed, the row is about the subject date again
    — the closed-day fallback exists for the morning, not instead of Batch 216."""
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 27)
    settled = DailyMetric(
        user_id=user_id,
        calendar_date=subject_date,
        phase="settled",
        body_battery_charged=80,
        body_battery_drained=64,
        raw_payload={
            "body_battery": {
                "charged": 80,
                "drained": 64,
                "startTimestampLocal": f"{subject_date.isoformat()}T00:00:00.0",
                "endTimestampLocal": f"{(subject_date + timedelta(days=1)).isoformat()}T00:00:00.0",
            }
        },
    )
    rows = {
        row["metricKey"]: row
        for row in _metrics_vs_baselines(
            _morning_row(user_id, subject_date),
            None,
            [
                _baseline(
                    user_id,
                    "body_battery_drain",
                    "Body Battery drain",
                    median=67,
                    lower=57.5,
                    upper=74.5,
                )
            ],
            None,
            day_aggregates=settled,
            closed_day_cost={"calendarDate": "2026-08-26", "bodyBatteryDrained": 73},
        )
    }
    assert rows["body_battery_drain"]["currentValue"] == 64
    assert "basis" not in rows["body_battery_drain"]
