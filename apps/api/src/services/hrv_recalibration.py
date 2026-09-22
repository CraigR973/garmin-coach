"""When Garmin moves the goalposts, notice it here (Batch 271).

On 18 and 19 September 2026 Mark's morning verdict was Red, and the reason was
that **Garmin's supplied HRV floor rose from 45 ms to 46 for exactly two days and
came back**. His own reading never deteriorated: on 18 September his overnight
HRV was 48 ms — his highest in six days, and *above* the raised floor — against
good sleep, a flat resting heart rate and a recovery-week training load. The app
had the band's whole history in its own `daily_metrics` rows and nothing read it,
so the only way the movement could be noticed was for Mark to notice it and argue
for it, which is what he did, over three mornings.

This module is that observation, made deterministically at 06:30 instead.

**The comparison is against a trailing reference, not against yesterday.** The
production floor runs 45 (10-17 Sep) -> 46 (18 Sep) -> 46 (19 Sep) -> 45 (20-22
Sep). A day-over-day test sees a movement only once, on the 18th, and would call
the 19th normal — but the 19th is the second Red and the second day the floor sat
a millisecond above everything around it. What is true on both days is that the
band is **above its own trailing median**, so that is what is measured. The same
test is applied to the reading, so "his reading did not move" is measured on the
same footing as "the band did" rather than asserted.

**The source is named, because we keep two different things called a baseline.**
``daily_metrics.hrv_baseline_low_ms`` is *Garmin's* band, supplied with each day's
sync. ``metric_baselines.hrv_7_day_avg_ms`` is *ours*, recomputed nightly by the
``baseline-refresh`` job over an 84-day window (median 47.0, IQR 45-49 as of
2026-09-21). They are not interchangeable and a reader who confuses them will
mistake our own recalculation for the vendor's.

The event is deliberately one signal with one meaning, consumed by the morning
verdict's Red gate (Batch 269) and the chronic Red-cluster classifier (Batch 270),
so the two cannot disagree about what an artifact is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any, Literal, Protocol


class HrvBandRow(Protocol):
    """The four fields this detector reads, whatever row shape carries them.

    ``DailyMetric`` satisfies it, and so does ``chronic_patterns.RecoveryDay`` —
    which matters, because Batch 270 classifies a Red cluster from its own
    28-day ``RecoveryDay`` series and must reach the same verdict as the morning
    verdict does from ``DailyMetric`` rows. A structural type keeps that one
    implementation rather than two that can drift.
    """

    @property
    def calendar_date(self) -> date: ...

    @property
    def hrv_last_night_avg_ms(self) -> int | None: ...

    @property
    def hrv_baseline_low_ms(self) -> int | None: ...

    @property
    def hrv_baseline_high_ms(self) -> int | None: ...


#: Trailing calendar days forming the **band's** reference. Long enough that a
#: two-day excursion cannot move the median that is meant to detect it.
BAND_REFERENCE_WINDOW_DAYS = 14

#: Trailing calendar days forming the **reading's** reference, and deliberately
#: shorter. This is not a tuning preference, it is the difference between two
#: questions. "Has the band left its usual level?" needs a long reference.
#: "Did he deteriorate *this morning*?" is acute, and a long reference answers it
#: wrongly whenever the metric is drifting — which is exactly when a vendor
#: recalibrates. Measured on production: over 14 days Mark's 19 September reading
#: sits 3 ms under its median purely because his HRV had been declining for a
#: fortnight, so the detector called a genuine band artifact a real deterioration
#: and would have stayed silent for the whole drift. Over 7 days the same reading
#: is 1 ms *above* its median, which is the true answer to the acute question.
READING_REFERENCE_WINDOW_DAYS = 7

#: Below this many prior observations the answer is "unknown", never "no
#: movement" — an absent history is not evidence of a stable band.
MIN_REFERENCE_SAMPLES = 5

#: A band excursion this size or larger counts. The floor moves in whole
#: milliseconds, so 1.0 is the smallest movement that can exist.
BAND_MOVEMENT_MS = 1.0

#: How far the reading may sit below its own trailing median and still count as
#: "did not move". Mark's overnight HRV has a day-to-day spread of several ms on
#: a ~45 ms median, so a tolerance smaller than this would call ordinary night-to-
#: night variation a deterioration and suppress nothing.
READING_TOLERANCE_MS = 2.0

#: The vendor whose band this is. Named in the event so nobody reads it as ours.
SOURCE_GARMIN = "garmin_supplied_band"

RecalibrationStatus = Literal[
    "recalibrated",  # band moved against a reading that did not
    "band_and_reading_moved",  # band moved and so did he — not an artifact
    "no_movement",  # band sits at its trailing reference
    "unknown",  # not enough history to say anything
]


@dataclass(frozen=True)
class _Series:
    current: float | None
    reference: float | None
    sample_count: int

    @property
    def delta(self) -> float | None:
        if self.current is None or self.reference is None:
            return None
        return round(self.current - self.reference, 2)


def detect_hrv_recalibration(
    daily_metric: HrvBandRow | None,
    recent_daily_metrics: Sequence[HrvBandRow],
) -> dict[str, Any]:
    """Has Garmin's HRV band moved under a reading that has not?

    ``recent_daily_metrics`` must be morning-phase rows strictly before the
    subject date. ``MorningAnalysisService._acute_physiology_history`` already
    guarantees both; anything else assembling this must do the same, or a morning
    row will one day be compared against a settled one and invent a movement.
    """
    if daily_metric is None:
        return _event("unknown", reason="No daily metric row for the subject date.")

    subject_date = daily_metric.calendar_date

    def window(days: int) -> list[HrvBandRow]:
        start = subject_date - timedelta(days=days)
        return [row for row in recent_daily_metrics if start <= row.calendar_date < subject_date]

    band_history = window(BAND_REFERENCE_WINDOW_DAYS)
    reading_history = window(READING_REFERENCE_WINDOW_DAYS)

    low = _series(daily_metric.hrv_baseline_low_ms, [r.hrv_baseline_low_ms for r in band_history])
    high = _series(
        daily_metric.hrv_baseline_high_ms, [r.hrv_baseline_high_ms for r in band_history]
    )
    reading = _series(
        daily_metric.hrv_last_night_avg_ms,
        [r.hrv_last_night_avg_ms for r in reading_history],
    )

    if low.reference is None or low.sample_count < MIN_REFERENCE_SAMPLES:
        return _event(
            "unknown",
            reason=(
                f"Only {low.sample_count} prior morning rows carry a Garmin HRV floor; "
                f"{MIN_REFERENCE_SAMPLES} are needed before a movement can be called."
            ),
            low=low,
            high=high,
            reading=reading,
        )

    # The trigger is the **floor**, not the band as a whole, because the floor is
    # the number the Red rule actually compares against
    # (``morning_verdict._hrv_below_baseline``). The ceiling is carried in the
    # event for context and its movement is reported, but it cannot by itself
    # make an artifact: on 20 Sep 2026 Garmin moved the ceiling 56 -> 55 while the
    # floor held at 45, and calling that a recalibration would suppress a day the
    # floor had nothing to do with.
    low_delta = low.delta or 0.0
    if abs(low_delta) < BAND_MOVEMENT_MS:
        return _event(
            "no_movement",
            reason=(
                "Garmin's HRV floor is at its trailing reference."
                + (
                    " (The band ceiling has moved, which is recorded but does not"
                    " make an artifact on its own — the Red rule compares against"
                    " the floor.)"
                    if high.delta is not None and abs(high.delta) >= BAND_MOVEMENT_MS
                    else ""
                )
            ),
            low=low,
            high=high,
            reading=reading,
        )

    reading_delta = reading.delta
    reading_held = (
        reading_delta is not None
        and reading.sample_count >= MIN_REFERENCE_SAMPLES
        and reading_delta >= -READING_TOLERANCE_MS
    )
    if not reading_held:
        return _event(
            "band_and_reading_moved",
            reason=(
                "Garmin's HRV floor moved, but his own overnight reading moved with it, "
                "so this is not a measurement artifact."
            ),
            low=low,
            high=high,
            reading=reading,
        )

    direction = "rose" if low_delta > 0 else "fell"
    return _event(
        "recalibrated",
        reason=(
            f"Garmin's HRV floor {direction} to {_ms(low.current)} against a trailing "
            f"{_ms(low.reference)}, while his overnight HRV held at {_ms(reading.current)} "
            f"against a trailing {_ms(reading.reference)}. The threshold moved; he did not."
        ),
        low=low,
        high=high,
        reading=reading,
    )


def is_band_artifact(event: dict[str, Any] | None) -> bool:
    """The single predicate Batches 269 and 270 share.

    Keeping it here rather than letting each consumer test the status string is
    the point of publishing one signal: the Red gate and the cluster classifier
    must not be able to disagree about what an artifact is.
    """
    return isinstance(event, dict) and event.get("status") == "recalibrated"


def _event(
    status: RecalibrationStatus,
    *,
    reason: str,
    low: _Series | None = None,
    high: _Series | None = None,
    reading: _Series | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "source": SOURCE_GARMIN,
        "sourceMeaning": (
            "Garmin supplies this band with each day's sync. It is not the app's own "
            "baseline, which lives in metric_baselines and is recomputed nightly over "
            "84 days by the baseline-refresh job."
        ),
        "reason": reason,
        "bandLow": _series_packet(low),
        "bandHigh": _series_packet(high),
        "overnightReading": _series_packet(reading),
        "bandReferenceWindowDays": BAND_REFERENCE_WINDOW_DAYS,
        "readingReferenceWindowDays": READING_REFERENCE_WINDOW_DAYS,
        "minimumReferenceSamples": MIN_REFERENCE_SAMPLES,
        "readingToleranceMs": READING_TOLERANCE_MS,
    }


def _series_packet(series: _Series | None) -> dict[str, Any]:
    if series is None:
        return {"currentMs": None, "referenceMs": None, "deltaMs": None, "sampleCount": 0}
    return {
        "currentMs": series.current,
        "referenceMs": series.reference,
        "deltaMs": series.delta,
        "sampleCount": series.sample_count,
    }


def _series(current: int | None, history: Sequence[int | None]) -> _Series:
    values = [float(value) for value in history if value is not None]
    return _Series(
        current=float(current) if current is not None else None,
        reference=float(median(values)) if values else None,
        sample_count=len(values),
    )


def _ms(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.0f} ms"
