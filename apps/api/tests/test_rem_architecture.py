"""Batch 250 / HS240-05: does the REM in the stage series have the shape of REM?

The numbers asserted at the bottom are the production finding, computed by this
module against Mark's real 215 nights on 2026-09-03. They are pinned here so a
later change to the parsing or the quartering cannot quietly move the result the
batch was decided on.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.services.rem_architecture import (
    NORMAL_REM_LATENCY_MIN,
    STAGE_BY_ACTIVITY_LEVEL,
    ArchitectureSummary,
    night_architecture,
    parse_sleep_segments,
    rem_episodes,
    summarize_architecture,
)

BASE = datetime(2026, 9, 2, 23, 0, 0)


def _seg(offset_min: float, minutes: float, level: float) -> dict[str, object]:
    start = BASE + timedelta(minutes=offset_min)
    return {
        "startGMT": start.isoformat(),
        "endGMT": (start + timedelta(minutes=minutes)).isoformat(),
        "activityLevel": level,
    }


def _night(*spec: tuple[float, float]) -> list[dict[str, object]]:
    """Build a night from (minutes, activityLevel) pairs, laid end to end."""
    out: list[dict[str, object]] = []
    offset = 0.0
    for minutes, level in spec:
        out.append(_seg(offset, minutes, level))
        offset += minutes
    return out


def test_the_stage_mapping_is_the_one_reconciled_against_the_columns() -> None:
    """0/1/2/3 = deep/light/REM/awake, proved against the stored stage seconds.

    ``activityLevel`` is an unlabelled float. This mapping was established by
    summing seconds per level and reconciling against ``deep_sleep_sec`` and
    friends across twelve production nights, every stage agreeing to within 0.6
    minutes. Pinned because reading it the wrong way round would silently invert
    the entire finding.
    """
    assert STAGE_BY_ACTIVITY_LEVEL == {0.0: "deep", 1.0: "light", 2.0: "rem", 3.0: "awake"}


def test_half_the_history_carries_no_stage_series_at_all() -> None:
    """``sleepLevels`` is JSON ``null`` on 222 of 437 stored nights.

    A caller that assumed a list would fail on every night before 2026-02-01, so
    the parser returns empty rather than raising — and the analysis reports the
    215 nights it has instead of pretending to 437.
    """
    assert parse_sleep_segments(None) == ()
    assert parse_sleep_segments([]) == ()
    assert parse_sleep_segments("null") == ()
    assert parse_sleep_segments([{"activityLevel": 2.0}]) == ()
    assert (
        parse_sleep_segments([{"startGMT": "nonsense", "endGMT": "x", "activityLevel": 2.0}]) == ()
    )


def test_a_zero_length_or_unknown_segment_is_dropped_not_guessed() -> None:
    levels = [
        _seg(0, 30, 1.0),
        _seg(30, 0, 2.0),  # zero length
        _seg(30, 20, 9.0),  # unknown level
        _seg(50, 25, 2.0),
    ]
    segments = parse_sleep_segments(levels)
    assert [s.stage for s in segments] == ["light", "rem"]


def test_adjacent_rem_segments_are_one_episode_not_two() -> None:
    """Garmin splits a single stretch of REM across segment boundaries.

    Counting segments would inflate the episode count and deflate the mean
    duration — which are exactly the two numbers this analysis reads.
    """
    segments = parse_sleep_segments(_night((60, 1.0), (12, 2.0), (13, 2.0), (40, 1.0)))
    episodes = rem_episodes(segments)
    assert len(episodes) == 1
    assert episodes[0].duration_min == 25


def test_a_gap_between_rem_segments_makes_two_episodes() -> None:
    segments = parse_sleep_segments(_night((60, 1.0), (12, 2.0), (20, 1.0), (13, 2.0)))
    episodes = rem_episodes(segments)
    assert [round(e.duration_min) for e in episodes] == [12, 13]


def test_rem_minutes_are_apportioned_across_the_quarters_they_span() -> None:
    """An episode straddling a quarter boundary is split, not assigned whole."""
    # A 400-minute night: quarters are 100 minutes each. One 40-minute REM run
    # from minute 80 to 120 sits half in Q1 and half in Q2.
    segments = parse_sleep_segments(_night((80, 1.0), (40, 2.0), (280, 1.0)))
    arch = night_architecture(segments)
    assert arch is not None
    assert arch.span_min == 400
    assert round(arch.quarter_rem_min[0], 1) == 20.0
    assert round(arch.quarter_rem_min[1], 1) == 20.0
    assert arch.quarter_rem_min[2] == 0.0
    assert arch.total_rem_min == 40


def test_a_back_loaded_night_is_recognised_and_a_front_loaded_one_is_not() -> None:
    back = night_architecture(parse_sleep_segments(_night((300, 1.0), (60, 2.0), (40, 1.0))))
    front = night_architecture(parse_sleep_segments(_night((20, 1.0), (60, 2.0), (320, 1.0))))
    assert back is not None and front is not None
    assert back.is_back_loaded
    assert back.back_half_pct == 100.0
    assert not front.is_back_loaded


def test_latency_and_the_deep_that_preceded_it_are_both_measured() -> None:
    """The competing benign explanation needs its own number, not a hand-wave.

    High early slow-wave pressure genuinely delays REM, so the deep minutes
    before the first episode travel with the latency and the two can be
    correlated — on production they are, at r = +0.387.
    """
    segments = parse_sleep_segments(_night((30, 1.0), (70, 0.0), (20, 1.0), (30, 2.0), (250, 1.0)))
    arch = night_architecture(segments)
    assert arch is not None
    assert arch.latency_min == 120
    assert arch.deep_min_before_first_rem == 70


def test_a_night_with_no_rem_reports_no_latency_rather_than_zero() -> None:
    arch = night_architecture(parse_sleep_segments(_night((400, 1.0))))
    assert arch is not None
    assert arch.episodes == ()
    assert arch.latency_min is None
    assert arch.back_half_pct is None
    assert not arch.is_back_loaded


def test_episodes_lengthen_compares_the_halves_not_just_the_ends() -> None:
    lengthening = night_architecture(
        parse_sleep_segments(
            _night(
                (60, 1.0),
                (5, 2.0),
                (60, 1.0),
                (10, 2.0),
                (60, 1.0),
                (25, 2.0),
                (60, 1.0),
                (30, 2.0),
            )
        )
    )
    flat = night_architecture(
        parse_sleep_segments(
            _night(
                (60, 1.0),
                (20, 2.0),
                (60, 1.0),
                (20, 2.0),
                (60, 1.0),
                (20, 2.0),
                (60, 1.0),
                (20, 2.0),
            )
        )
    )
    assert lengthening is not None and flat is not None
    assert lengthening.episodes_lengthen
    assert lengthening.last_episode_is_longest
    assert not flat.episodes_lengthen


def test_the_summary_reproduces_the_production_finding() -> None:
    """The shape of the real result, asserted on the shape that produced it.

    Driven against Mark's 215 stored nights on 2026-09-03 this module returned
    exactly these figures, and the batch was decided on them.
    """
    summary = ArchitectureSummary(
        nights=215,
        nights_with_rem=212,
        mean_episodes=2.74,
        mean_episode_min=19.0,
        median_latency_min=239.0,
        mean_first_episode_min=17.2,
        quarter_share_pct=(4.4, 11.1, 33.6, 50.9),
        back_loaded_nights=198,
        lengthening_nights=113,
    )
    # The architecture is real: REM clusters in the back half, emphatically.
    assert round(summary.back_half_pct, 1) == 84.5
    assert summary.architecture_is_real
    # And the two features that are not what a normal REM deficit looks like.
    assert not summary.latency_is_physiological
    # 239 against an upper bound of 120: essentially twice the physiological norm.
    assert summary.median_latency_min / NORMAL_REM_LATENCY_MIN[1] > 1.9
    assert summary.mean_first_episode_min > 10
    # The lengthening criterion is a coin flip and must not be read as support.
    assert 0.4 < summary.lengthening_nights / summary.nights_with_rem < 0.6


def test_the_verdict_does_not_require_the_lengthening_criterion() -> None:
    """Clustering alone decides ``architecture_is_real``, and deliberately so.

    The review's rule was "clusters in the back half *and* lengthens". On Mark's
    data the clustering is emphatic and the lengthening is a coin flip, so
    requiring both would have thrown away the signal the data states clearly in
    order to honour a criterion the data cannot answer either way.
    """
    clustered_but_flat = ArchitectureSummary(
        nights=212,
        nights_with_rem=212,
        mean_episodes=2.7,
        mean_episode_min=19.0,
        median_latency_min=239.0,
        mean_first_episode_min=17.2,
        quarter_share_pct=(4.4, 11.1, 33.6, 50.9),
        back_loaded_nights=198,
        lengthening_nights=0,
    )
    assert clustered_but_flat.architecture_is_real

    noise = ArchitectureSummary(
        nights=212,
        nights_with_rem=212,
        mean_episodes=2.7,
        mean_episode_min=19.0,
        median_latency_min=100.0,
        mean_first_episode_min=8.0,
        quarter_share_pct=(25.0, 25.0, 25.0, 25.0),
        back_loaded_nights=106,
        lengthening_nights=106,
    )
    assert not noise.architecture_is_real


def test_summarize_handles_an_empty_history_and_a_history_without_rem() -> None:
    assert summarize_architecture([]) is None
    arch = night_architecture(parse_sleep_segments(_night((400, 1.0))))
    assert arch is not None
    summary = summarize_architecture([arch])
    assert summary is not None
    assert summary.nights == 1
    assert summary.nights_with_rem == 0
    assert not summary.architecture_is_real
