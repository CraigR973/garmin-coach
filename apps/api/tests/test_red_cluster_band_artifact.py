"""Batch 270 — a two-day Garmin recalibration must not restructure a build week.

On 21 September 2026 a ``rearrange_proposal`` fired on a cluster of 18, 19 and
21 September and proposed moving Mark's Tuesday VO2 to Saturday. **Two of its
three days are the band excursion Batch 271 detects** — Garmin's floor rose
45 -> 46 for exactly two days while his own reading held, and on the 18th rose.
He declined the proposal, and had predicted the propagation in writing an hour
before it fired.

The series here is production, morning phase, read 2026-09-22. It runs from
28 August because the detector's band reference is 14 days and a fixture shorter
than the window the code reads tests a different regime than production — the
mistake Batch 271 shipped once and the production smoke caught.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.services.chronic_patterns import (
    BAND_ARTIFACT_EXCLUSION_LIMIT,
    CHRONIC_ACTION_RED_THRESHOLD,
    RecoveryDay,
    RedDayEvidence,
    _qualify_red_morning,
    _red_day_evidence,
)

# (day, overnight, weekly, floor, ceiling) — coach.daily_metrics, phase=morning
SERIES: tuple[tuple[date, int, int, int, int], ...] = (
    (date(2026, 8, 28), 43, 49, 44, 56),
    (date(2026, 8, 29), 48, 48, 44, 56),
    (date(2026, 8, 30), 44, 47, 44, 56),
    (date(2026, 8, 31), 47, 47, 44, 56),
    (date(2026, 9, 1), 44, 46, 44, 56),
    (date(2026, 9, 2), 50, 46, 44, 56),
    (date(2026, 9, 3), 51, 47, 44, 56),
    (date(2026, 9, 4), 54, 48, 44, 56),
    (date(2026, 9, 5), 51, 49, 44, 56),
    (date(2026, 9, 6), 49, 49, 44, 56),
    (date(2026, 9, 7), 48, 49, 44, 56),
    (date(2026, 9, 8), 43, 49, 44, 56),
    (date(2026, 9, 9), 49, 49, 44, 56),
    (date(2026, 9, 10), 51, 49, 44, 56),
    (date(2026, 9, 11), 52, 49, 45, 56),
    (date(2026, 9, 12), 48, 48, 45, 56),
    (date(2026, 9, 13), 42, 47, 45, 56),
    (date(2026, 9, 14), 47, 47, 45, 56),
    (date(2026, 9, 15), 42, 47, 45, 56),
    (date(2026, 9, 16), 44, 47, 45, 56),
    (date(2026, 9, 17), 43, 45, 45, 56),
    (date(2026, 9, 18), 48, 45, 46, 56),
    (date(2026, 9, 19), 45, 45, 46, 56),
    (date(2026, 9, 20), 46, 45, 45, 55),
    (date(2026, 9, 21), 37, 44, 45, 55),
    (date(2026, 9, 22), 39, 43, 45, 55),
)

AS_OF = date(2026, 9, 21)
#: The real cluster the 21 September rearrange_proposal fired on.
REAL_CLUSTER = (date(2026, 9, 18), date(2026, 9, 19), date(2026, 9, 21))


def _recovery_days() -> list[RecoveryDay]:
    return [
        RecoveryDay(
            calendar_date=day,
            hrv_7_day_avg_ms=weekly,
            hrv_last_night_avg_ms=overnight,
            hrv_status="unbalanced" if overnight < floor or weekly < floor else "balanced",
            hrv_baseline_low_ms=floor,
            hrv_baseline_high_ms=ceiling,
            resting_heart_rate_bpm=44,
        )
        for day, overnight, weekly, floor, ceiling in SERIES
    ]


def _evidence() -> dict[date, RedDayEvidence]:
    return _red_day_evidence(_recovery_days(), manual_rows=[], baselines={})


def _counted(days: tuple[date, ...], evidence: dict[date, RedDayEvidence]) -> int:
    remaining = BAND_ARTIFACT_EXCLUSION_LIMIT
    counted = 0
    for day in reversed(days):
        q = _qualify_red_morning(
            day,
            evidence.get(day),
            as_of=AS_OF,
            allow_acute_exclusion=True,
            allow_training_debt_exclusion=True,
            allow_band_artifact_exclusion=remaining > 0,
        )
        if q.classification == "garmin_band_artifact":
            remaining -= 1
        if q.counts_toward_cluster:
            counted += 1
    return counted


def test_the_two_excursion_days_are_classified_as_artifacts() -> None:
    evidence = _evidence()
    assert evidence[date(2026, 9, 18)].band_artifact is True
    assert evidence[date(2026, 9, 19)].band_artifact is True
    assert evidence[date(2026, 9, 18)].band_artifact_reason is not None


def test_the_genuine_reds_are_not_artifacts() -> None:
    """21 and 22 Sep: overnight 37 and 39 against a floor that never moved."""
    evidence = _evidence()
    assert evidence[date(2026, 9, 21)].band_artifact is False
    assert evidence[date(2026, 9, 22)].band_artifact is False


def test_the_real_cluster_no_longer_reaches_the_rearrange_threshold() -> None:
    """18, 19, 21 Sep counted 3 and fired a proposal; it must now count 1."""
    counted = _counted(REAL_CLUSTER, _evidence())
    assert counted == 1
    assert counted < CHRONIC_ACTION_RED_THRESHOLD


def test_two_genuine_reds_still_fire() -> None:
    """The rail this batch must not weaken."""
    counted = _counted((date(2026, 9, 21), date(2026, 9, 22)), _evidence())
    assert counted == 2
    assert counted >= CHRONIC_ACTION_RED_THRESHOLD


def test_an_artifact_and_a_genuine_red_together_do_not_fire() -> None:
    counted = _counted((date(2026, 9, 19), date(2026, 9, 21)), _evidence())
    assert counted == 1
    assert counted < CHRONIC_ACTION_RED_THRESHOLD


def test_the_artifact_budget_is_its_own_and_is_capped() -> None:
    """It must not draw on the shared acute/training-debt allowance, and it must
    not be unbounded — a window of all-artifact Reds is likelier a detector fault
    than a vendor event, and should surface rather than be absorbed."""
    evidence = _evidence()
    artifact_days = tuple(day for day, e in sorted(evidence.items()) if e.band_artifact)
    for day in artifact_days:
        capped = _qualify_red_morning(
            day,
            evidence[day],
            as_of=AS_OF,
            allow_acute_exclusion=True,
            allow_training_debt_exclusion=True,
            allow_band_artifact_exclusion=False,
        )
        assert capped.counts_toward_cluster is True
        assert capped.classification == "band_artifact_exclusion_cap_reached"


def test_the_artifact_does_not_spend_a_shared_exclusion() -> None:
    """An artifact day that also carries an acute check-in tag stays an artifact.

    Otherwise a mis-measured Red would consume the one allowance reserved for a
    Red whose strain was real and whose cause was merely explained.
    """
    evidence = _evidence()
    tagged = RedDayEvidence(
        calendar_date=date(2026, 9, 18),
        hrv_ms=evidence[date(2026, 9, 18)].hrv_ms,
        hrv_status="unbalanced",
        hrv_floor_ms=46.0,
        check_in_reasons=("alcohol",),
        band_artifact=True,
        band_artifact_reason="floor moved, reading held",
    )
    q = _qualify_red_morning(
        date(2026, 9, 18),
        tagged,
        as_of=AS_OF,
        allow_acute_exclusion=True,
        allow_training_debt_exclusion=True,
        allow_band_artifact_exclusion=True,
    )
    assert q.classification == "garmin_band_artifact"
    assert q.counts_toward_cluster is False


def test_the_reason_is_inspectable_in_the_packet() -> None:
    evidence = _evidence()
    q = _qualify_red_morning(
        date(2026, 9, 18),
        evidence[date(2026, 9, 18)],
        as_of=AS_OF,
        allow_acute_exclusion=True,
        allow_training_debt_exclusion=True,
    )
    packet = q.to_packet()
    assert packet["garminBandArtifact"]["detected"] is True
    assert packet["garminBandArtifact"]["reason"]
    assert packet["classification"] == "garmin_band_artifact"


def test_a_day_with_no_evidence_still_counts() -> None:
    """Unchanged behaviour: an unexplained Red is not made to vanish."""
    q = _qualify_red_morning(
        AS_OF - timedelta(days=1),
        None,
        as_of=AS_OF,
        allow_acute_exclusion=True,
        allow_training_debt_exclusion=True,
    )
    assert q.counts_toward_cluster is True
    assert q.classification == "unexplained_red"
