"""Monitoring + insight engine (Batch 17).

Turns the accumulated history into proactive, *deterministic* insight — no LLM
call, matching the Batch 13/14/16 philosophy that plan-shaping/alerting safety
properties should be inspectable, unit-testable arithmetic:

  * **17.1 FTP-drift detection.** ``detect_ftp_drift`` reads the trend in aerobic
    efficiency (power per heartbeat) across recent rides and flags a rising or
    falling fitness signal, surfacing the evidence window it judged on.
  * **17.2 Early-warning drift alerts.** ``detect_early_warning`` watches the
    HRV / sleep / readiness trend and fires *before* a Red verdict when two or
    more of those trends are degrading — so the coach warns ahead of the crash,
    not after it.
  * **17.3 Driver/correlation analysis.** ``compute_drivers`` ranks the candidate
    movers of sleep and recovery by Pearson correlation over the long history,
    so the strongest levers (environment, prior-day load, stress) are visible.

The three pure functions take plain samples so the thresholds and maths are
testable without a database; ``InsightsService`` is a thin DB wrapper that reads
the rows, calls them, and (on the ``/run`` path) records an audit row in
``analyses``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    FanStateReading,
    KnowledgeBase,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.bedroom_overnight import (
    THRESHOLD_CRITICAL_C,
    THRESHOLD_ON_C,
    night_for_local,
    night_window,
    sleep_calendar_date,
    summarize_overnight,
)
from src.services.daily_loop import ANALYSIS_TYPE_MORNING

PROMPT_VERSION = "insights:v1"

AUDIT_TYPE_FTP_DRIFT = "ftp_drift"
AUDIT_TYPE_EARLY_WARNING = "early_warning"
AUDIT_TYPE_DRIVERS = "driver_correlation"

DEFAULT_FTP_WATTS = 280

# --- 17.1 FTP-drift thresholds -------------------------------------------------
FTP_DRIFT_WINDOW_DAYS = 42  # ~6 weeks of rides
FTP_DRIFT_MIN_SAMPLES = 4
FTP_DRIFT_PCT_THRESHOLD = 0.03  # ±3% efficiency change = a meaningful drift

# --- 17.2 Early-warning thresholds ---------------------------------------------
EARLY_WARNING_WINDOW_DAYS = 5
EARLY_WARNING_MIN_DAYS = 3
EARLY_WARNING_MIN_DEGRADING = 2  # ≥2 degrading trends fires the alert
HRV_DECLINE_SLOPE = -0.8  # ms per day
SLEEP_DECLINE_SLOPE = -1.5  # score points per day
READINESS_DECLINE_SLOPE = -2.0  # score points per day

# --- 17.3 Driver/correlation settings ------------------------------------------
DRIVERS_LOOKBACK_DAYS = 120
MIN_CORRELATION_SAMPLES = 8

OUTCOME_SLEEP_SCORE = "sleep_score"
OUTCOME_RECOVERY_HRV = "recovery_hrv_ms"

DRIVER_KEYS = (
    "overnight_low_c",
    "overnight_wind_max_mph",
    "bedroom_warning_minutes",
    "bedroom_critical_minutes",
    "bedroom_fan_ran_minutes",
    "bedroom_peak_fan_speed",
    "prev_day_training_load",
    "daytime_stress_avg",
    "resting_heart_rate_bpm",
    "sleep_stress_avg",
)

BEDROOM_DRIVER_KEYS = (
    "bedroom_warning_minutes",
    "bedroom_critical_minutes",
    "bedroom_fan_ran_minutes",
    "bedroom_peak_fan_speed",
)

_BEDROOM_DRIVER_LABELS = {
    "bedroom_warning_minutes": f"60+ min above {THRESHOLD_ON_C:g}C",
    "bedroom_critical_minutes": f"60+ min above {THRESHOLD_CRITICAL_C:g}C",
    "bedroom_fan_ran_minutes": "the fan ran",
    "bedroom_peak_fan_speed": "fan peaked at speed 5+",
}

_BEDROOM_DRIVER_THRESHOLDS = {
    "bedroom_warning_minutes": 60.0,
    "bedroom_critical_minutes": 60.0,
    "bedroom_fan_ran_minutes": 1.0,
    "bedroom_peak_fan_speed": 5.0,
}

_OUTCOME_SENTENCE_LABELS = {
    OUTCOME_SLEEP_SCORE: ("sleep score", "points", True),
    OUTCOME_RECOVERY_HRV: ("recovery HRV", "ms", True),
    "overnight_awake_min": ("overnight awake time", "min", False),
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Statistics helpers (kept dependency-free)
# ---------------------------------------------------------------------------


def _as_float(value: float | int | None) -> float | None:
    return float(value) if value is not None else None


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _slope(values: Sequence[float]) -> float | None:
    """Least-squares slope of ``values`` against their 0..n-1 index."""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = _mean([float(x) for x in xs])
    mean_y = _mean(values)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    numer = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True))
    return numer / denom


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation coefficient, or ``None`` if undefined."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return float(cov / (var_x**0.5 * var_y**0.5))


# ---------------------------------------------------------------------------
# 17.1 — FTP drift
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PowerHrSample:
    activity_date: date
    avg_power_watts: float | None
    normalized_power_watts: float | None
    avg_heart_rate_bpm: float | None

    @property
    def power(self) -> float | None:
        return self.normalized_power_watts or self.avg_power_watts

    @property
    def efficiency_factor(self) -> float | None:
        """Aerobic efficiency proxy: watts produced per heartbeat."""
        power = self.power
        if power is None or not self.avg_heart_rate_bpm:
            return None
        return power / self.avg_heart_rate_bpm


@dataclass(frozen=True)
class FtpDriftResult:
    status: str  # rising | falling | stable | insufficient_data
    sample_count: int
    window_start: date | None
    window_end: date | None
    baseline_ef: float | None
    recent_ef: float | None
    pct_change: float | None
    current_ftp_watts: int
    suggested_ftp_watts: int | None
    reasons: list[str] = field(default_factory=list)


def detect_ftp_drift(
    samples: Sequence[PowerHrSample],
    *,
    current_ftp_watts: int,
) -> FtpDriftResult:
    """Detect an FTP drift from the trend in ride efficiency (power/HR).

    Splits the valid samples into an earlier baseline half and a more recent
    half; a sustained rise in watts-per-heartbeat at similar effort is the
    signal that the current FTP estimate is stale-low (and vice-versa). The
    evidence window (first/last ride dates + sample count) is surfaced so the
    judgement is inspectable.
    """
    valid = sorted(
        (s for s in samples if s.efficiency_factor is not None),
        key=lambda s: s.activity_date,
    )
    if len(valid) < FTP_DRIFT_MIN_SAMPLES:
        return FtpDriftResult(
            status="insufficient_data",
            sample_count=len(valid),
            window_start=valid[0].activity_date if valid else None,
            window_end=valid[-1].activity_date if valid else None,
            baseline_ef=None,
            recent_ef=None,
            pct_change=None,
            current_ftp_watts=current_ftp_watts,
            suggested_ftp_watts=None,
            reasons=[
                f"Only {len(valid)} rides with power+HR; "
                f"need ≥{FTP_DRIFT_MIN_SAMPLES} to judge drift.",
            ],
        )

    split = len(valid) // 2
    baseline = [s.efficiency_factor for s in valid[:split] if s.efficiency_factor is not None]
    recent = [s.efficiency_factor for s in valid[split:] if s.efficiency_factor is not None]
    baseline_ef = _mean(baseline)
    recent_ef = _mean(recent)
    pct_change = (recent_ef - baseline_ef) / baseline_ef if baseline_ef else 0.0

    reasons: list[str] = []
    if pct_change >= FTP_DRIFT_PCT_THRESHOLD:
        status = "rising"
        suggested = round(current_ftp_watts * (1 + pct_change))
        reasons.append(
            f"Ride efficiency up {pct_change * 100:.1f}% vs the earlier window — "
            f"FTP may have drifted above {current_ftp_watts}W.",
        )
    elif pct_change <= -FTP_DRIFT_PCT_THRESHOLD:
        status = "falling"
        suggested = round(current_ftp_watts * (1 + pct_change))
        reasons.append(
            f"Ride efficiency down {abs(pct_change) * 100:.1f}% vs the earlier window — "
            f"FTP may have drifted below {current_ftp_watts}W.",
        )
    else:
        status = "stable"
        suggested = None
        reasons.append(
            f"Ride efficiency within ±{FTP_DRIFT_PCT_THRESHOLD * 100:.0f}% — "
            f"FTP {current_ftp_watts}W looks current.",
        )

    return FtpDriftResult(
        status=status,
        sample_count=len(valid),
        window_start=valid[0].activity_date,
        window_end=valid[-1].activity_date,
        baseline_ef=round(baseline_ef, 4),
        recent_ef=round(recent_ef, 4),
        pct_change=round(pct_change, 4),
        current_ftp_watts=current_ftp_watts,
        suggested_ftp_watts=suggested,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# 17.2 — Early-warning drift alerts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrendDay:
    day: date
    hrv_ms: float | None
    sleep_score: float | None
    readiness_score: float | None
    verdict: str | None


@dataclass(frozen=True)
class EarlyWarningResult:
    status: str  # early_warning | watch | ok | already_red | insufficient_data
    fired: bool
    window_start: date | None
    window_end: date | None
    hrv_slope: float | None
    sleep_slope: float | None
    readiness_slope: float | None
    degrading_metrics: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def detect_early_warning(days: Sequence[TrendDay]) -> EarlyWarningResult:
    """Fire an early warning when ≥2 recovery trends are degrading before a Red.

    A Red verdict already present in the window means the crash has arrived — the
    warning is no longer "early", so it is reported as ``already_red`` rather than
    a fresh alert. Otherwise the slopes of HRV, sleep score and readiness are
    measured; each that falls steeply enough counts as degrading, and two or more
    degrading trends fire the alert.
    """
    ordered = sorted(days, key=lambda d: d.day)
    if len(ordered) < EARLY_WARNING_MIN_DAYS:
        return EarlyWarningResult(
            status="insufficient_data",
            fired=False,
            window_start=ordered[0].day if ordered else None,
            window_end=ordered[-1].day if ordered else None,
            hrv_slope=None,
            sleep_slope=None,
            readiness_slope=None,
            reasons=[
                f"Only {len(ordered)} days of trend; need ≥{EARLY_WARNING_MIN_DAYS}.",
            ],
        )

    hrv_slope = _slope([d.hrv_ms for d in ordered if d.hrv_ms is not None])
    sleep_slope = _slope([d.sleep_score for d in ordered if d.sleep_score is not None])
    readiness_slope = _slope([d.readiness_score for d in ordered if d.readiness_score is not None])

    degrading: list[str] = []
    reasons: list[str] = []
    if hrv_slope is not None and hrv_slope <= HRV_DECLINE_SLOPE:
        degrading.append("hrv")
        reasons.append(f"HRV trending down ({hrv_slope:.2f} ms/day).")
    if sleep_slope is not None and sleep_slope <= SLEEP_DECLINE_SLOPE:
        degrading.append("sleep")
        reasons.append(f"Sleep score trending down ({sleep_slope:.2f}/day).")
    if readiness_slope is not None and readiness_slope <= READINESS_DECLINE_SLOPE:
        degrading.append("readiness")
        reasons.append(f"Training readiness trending down ({readiness_slope:.2f}/day).")

    has_red = any((d.verdict or "").lower() == "red" for d in ordered)

    if has_red:
        status = "already_red"
        fired = False
        reasons.append("A Red verdict is already present — the warning is not early.")
    elif len(degrading) >= EARLY_WARNING_MIN_DEGRADING:
        status = "early_warning"
        fired = True
    elif degrading:
        status = "watch"
        fired = False
    else:
        status = "ok"
        fired = False
        reasons.append("No degrading recovery trend detected.")

    return EarlyWarningResult(
        status=status,
        fired=fired,
        window_start=ordered[0].day,
        window_end=ordered[-1].day,
        hrv_slope=round(hrv_slope, 4) if hrv_slope is not None else None,
        sleep_slope=round(sleep_slope, 4) if sleep_slope is not None else None,
        readiness_slope=round(readiness_slope, 4) if readiness_slope is not None else None,
        degrading_metrics=degrading,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# 17.3 — Driver/correlation analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriverCorrelation:
    driver: str
    outcome: str
    coefficient: float
    sample_count: int
    summary: str | None = None

    @property
    def direction(self) -> str:
        return "positive" if self.coefficient >= 0 else "negative"


@dataclass(frozen=True)
class BedroomDriverValues:
    wake_date: date
    warning_minutes: float | None
    critical_minutes: float | None
    fan_ran_minutes: float | None
    peak_fan_speed: float | None


def compute_drivers(
    records: Sequence[dict[str, float | None]],
    *,
    outcome_key: str,
    driver_keys: Sequence[str],
    min_samples: int = MIN_CORRELATION_SAMPLES,
) -> list[DriverCorrelation]:
    """Rank candidate drivers by Pearson correlation with an outcome.

    For each driver the pairs where both the driver and the outcome are present
    are correlated; drivers with too few pairs or zero variance are skipped. The
    result is sorted by absolute correlation, strongest mover first.
    """
    results: list[DriverCorrelation] = []
    for driver in driver_keys:
        xs: list[float] = []
        ys: list[float] = []
        for record in records:
            x = record.get(driver)
            y = record.get(outcome_key)
            if x is None or y is None:
                continue
            xs.append(float(x))
            ys.append(float(y))
        if len(xs) < min_samples:
            continue
        coeff = pearson(xs, ys)
        if coeff is None:
            continue
        result = DriverCorrelation(driver, outcome_key, round(coeff, 4), len(xs))
        results.append(
            DriverCorrelation(
                driver=result.driver,
                outcome=result.outcome,
                coefficient=result.coefficient,
                sample_count=result.sample_count,
                summary=driver_sentence(records, result),
            )
        )
    results.sort(key=lambda r: abs(r.coefficient), reverse=True)
    return results


async def bedroom_driver_values_by_date(
    session: AsyncSession, player: Profile, *, start: date, end: date
) -> dict[date, BedroomDriverValues]:
    """Bedroom warning/fan rollups keyed by Garmin's wake-morning sleep date."""
    tz = ZoneInfo(player.timezone or "UTC")
    first_start, _ = night_window(start - timedelta(days=1), tz)
    _, last_end = night_window(end - timedelta(days=1), tz)

    temperatures = (
        (
            await session.execute(
                select(TemperatureReading).where(
                    TemperatureReading.user_id == player.id,
                    TemperatureReading.captured_at_utc >= first_start,
                    TemperatureReading.captured_at_utc < last_end,
                )
            )
        )
        .scalars()
        .all()
    )
    fan_states = (
        (
            await session.execute(
                select(FanStateReading).where(
                    FanStateReading.user_id == player.id,
                    FanStateReading.captured_at_utc >= first_start,
                    FanStateReading.captured_at_utc < last_end,
                )
            )
        )
        .scalars()
        .all()
    )

    temps_by_wake_date: dict[date, list[float | None]] = {}
    fan_by_wake_date: dict[date, list[tuple[bool | None, int | None]]] = {}

    for temp_row in temperatures:
        wake_date = _wake_date_for_utc(temp_row.captured_at_utc, tz)
        if wake_date is None or wake_date < start or wake_date > end:
            continue
        temps_by_wake_date.setdefault(wake_date, []).append(temp_row.temperature_c)

    for fan_row in fan_states:
        wake_date = _wake_date_for_utc(fan_row.captured_at_utc, tz)
        if wake_date is None or wake_date < start or wake_date > end:
            continue
        fan_by_wake_date.setdefault(wake_date, []).append((fan_row.fan_on, fan_row.fan_speed))

    values: dict[date, BedroomDriverValues] = {}
    for wake_date in sorted(set(temps_by_wake_date) | set(fan_by_wake_date)):
        temp_values = temps_by_wake_date.get(wake_date, [])
        fan_values = fan_by_wake_date.get(wake_date, [])
        temp_summary = summarize_overnight(temp_values, []) if temp_values else None
        fan_summary = summarize_overnight([], fan_values) if fan_values else None
        values[wake_date] = BedroomDriverValues(
            wake_date=wake_date,
            warning_minutes=float(temp_summary.warning_minutes) if temp_summary else None,
            critical_minutes=float(temp_summary.critical_minutes) if temp_summary else None,
            fan_ran_minutes=float(fan_summary.fan_ran_minutes) if fan_summary else None,
            peak_fan_speed=float(fan_summary.peak_speed)
            if fan_summary and fan_summary.peak_speed is not None
            else None,
        )
    return values


def _wake_date_for_utc(captured_at_utc: datetime, tz: ZoneInfo) -> date | None:
    local = captured_at_utc.replace(tzinfo=UTC).astimezone(tz)
    night = night_for_local(local)
    if night is None:
        return None
    return sleep_calendar_date(night)


def driver_sentence(
    records: Sequence[dict[str, float | None]], correlation: DriverCorrelation
) -> str | None:
    """Plain-language grouped-mean read for bedroom drivers.

    The correlation remains the ranking statistic. This sentence adds a
    human-readable split for the bedroom-derived candidates only, so the API can
    say what the measured nights averaged without introducing a new model.
    """
    threshold = _BEDROOM_DRIVER_THRESHOLDS.get(correlation.driver)
    label = _BEDROOM_DRIVER_LABELS.get(correlation.driver)
    outcome_meta = _OUTCOME_SENTENCE_LABELS.get(correlation.outcome)
    if threshold is None or label is None or outcome_meta is None:
        return None

    exposed: list[float] = []
    baseline: list[float] = []
    for record in records:
        driver_value = record.get(correlation.driver)
        outcome_value = record.get(correlation.outcome)
        if driver_value is None or outcome_value is None:
            continue
        if float(driver_value) >= threshold:
            exposed.append(float(outcome_value))
        else:
            baseline.append(float(outcome_value))

    if not exposed or not baseline:
        return None

    outcome_label, unit, higher_is_better = outcome_meta
    exposed_mean = _mean(exposed)
    baseline_mean = _mean(baseline)
    delta = exposed_mean - baseline_mean
    if abs(delta) < 0.05:
        comparison = f"about the same {outcome_label}"
    else:
        direction = "higher" if delta > 0 else "lower"
        magnitude = _format_delta(abs(delta))
        comparison = f"{magnitude} {unit} {direction} {outcome_label}"
        if not higher_is_better:
            comparison = f"{magnitude} {unit} {'more' if delta > 0 else 'less'} {outcome_label}"

    return f"Nights with {label} average {comparison} ({correlation.sample_count} nights measured)."


def _format_delta(value: float) -> str:
    rounded = round(value, 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:g}"


@dataclass
class DriversReport:
    outcomes: dict[str, list[DriverCorrelation]]
    record_count: int
    window_start: date | None
    window_end: date | None


# ---------------------------------------------------------------------------
# DB service
# ---------------------------------------------------------------------------


class InsightsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _ftp_watts(self, user_id: uuid.UUID) -> int:
        section = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == "profile",
                KnowledgeBase.is_active.is_(True),
            )
        )
        if section and isinstance(section.content, dict):
            ftp = section.content.get("ftpWatts")
            if isinstance(ftp, int) and ftp > 0:
                return ftp
        return DEFAULT_FTP_WATTS

    async def ftp_drift(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
        window_days: int = FTP_DRIFT_WINDOW_DAYS,
    ) -> FtpDriftResult:
        end = as_of or date.today()
        start = end - timedelta(days=window_days)
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == player.id,
                        Activity.avg_power_watts.is_not(None),
                        Activity.avg_heart_rate_bpm.is_not(None),
                        Activity.start_utc >= datetime(start.year, start.month, start.day),
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        samples = [
            PowerHrSample(
                activity_date=row.start_utc.date(),
                avg_power_watts=float(row.avg_power_watts)
                if row.avg_power_watts is not None
                else None,
                normalized_power_watts=float(row.normalized_power_watts)
                if row.normalized_power_watts is not None
                else None,
                avg_heart_rate_bpm=float(row.avg_heart_rate_bpm)
                if row.avg_heart_rate_bpm is not None
                else None,
            )
            for row in rows
            if row.start_utc.date() <= end
        ]
        ftp = await self._ftp_watts(player.id)
        return detect_ftp_drift(samples, current_ftp_watts=ftp)

    async def early_warning(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
        window_days: int = EARLY_WARNING_WINDOW_DAYS,
    ) -> EarlyWarningResult:
        end = as_of or date.today()
        start = end - timedelta(days=window_days - 1)
        metrics = (
            (
                await self.session.execute(
                    select(DailyMetric).where(
                        DailyMetric.user_id == player.id,
                        DailyMetric.calendar_date >= start,
                        DailyMetric.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        sleeps = (
            (
                await self.session.execute(
                    select(Sleep).where(
                        Sleep.user_id == player.id,
                        Sleep.calendar_date >= start,
                        Sleep.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        analyses = (
            (
                await self.session.execute(
                    select(Analysis).where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == ANALYSIS_TYPE_MORNING,
                        Analysis.subject_date >= start,
                        Analysis.subject_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        metric_by_date = {m.calendar_date: m for m in metrics}
        sleep_by_date = {s.calendar_date: s for s in sleeps}
        verdict_by_date = {a.subject_date: a.verdict for a in analyses}
        all_dates = sorted(set(metric_by_date) | set(sleep_by_date) | set(verdict_by_date))
        days = [
            TrendDay(
                day=day,
                hrv_ms=_as_float(
                    metric_by_date[day].hrv_last_night_avg_ms if day in metric_by_date else None
                ),
                sleep_score=_as_float(sleep_by_date[day].score if day in sleep_by_date else None),
                readiness_score=_as_float(
                    metric_by_date[day].readiness_score if day in metric_by_date else None
                ),
                verdict=verdict_by_date.get(day),
            )
            for day in all_dates
        ]
        return detect_early_warning(days)

    async def _driver_records(
        self, player: Profile, *, start: date, end: date
    ) -> list[dict[str, float | None]]:
        metrics = (
            (
                await self.session.execute(
                    select(DailyMetric).where(
                        DailyMetric.user_id == player.id,
                        DailyMetric.calendar_date >= start,
                        DailyMetric.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        sleeps = (
            (
                await self.session.execute(
                    select(Sleep).where(
                        Sleep.user_id == player.id,
                        Sleep.calendar_date >= start,
                        Sleep.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        weather = (
            (
                await self.session.execute(
                    select(WeatherDaily).where(
                        WeatherDaily.user_id == player.id,
                        WeatherDaily.calendar_date >= start,
                        WeatherDaily.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        activities = (
            (
                await self.session.execute(
                    select(Activity).where(
                        Activity.user_id == player.id,
                        Activity.training_load.is_not(None),
                        Activity.start_utc
                        >= datetime(start.year, start.month, start.day) - timedelta(days=1),
                    )
                )
            )
            .scalars()
            .all()
        )
        metric_by_date = {m.calendar_date: m for m in metrics}
        sleep_by_date = {s.calendar_date: s for s in sleeps}
        weather_by_date = {w.calendar_date: w for w in weather}
        bedroom_by_date = await bedroom_driver_values_by_date(
            self.session, player, start=start, end=end
        )
        load_by_date: dict[date, float] = {}
        for activity in activities:
            day = activity.start_utc.date()
            load_by_date[day] = load_by_date.get(day, 0.0) + float(activity.training_load or 0.0)

        records: list[dict[str, float | None]] = []
        for day in sorted(set(metric_by_date) | set(sleep_by_date)):
            metric = metric_by_date.get(day)
            sleep = sleep_by_date.get(day)
            weather_row = weather_by_date.get(day)
            bedroom = bedroom_by_date.get(day)
            prev_load = load_by_date.get(day - timedelta(days=1))
            records.append(
                {
                    OUTCOME_SLEEP_SCORE: float(sleep.score)
                    if sleep and sleep.score is not None
                    else None,
                    OUTCOME_RECOVERY_HRV: float(metric.hrv_last_night_avg_ms)
                    if metric and metric.hrv_last_night_avg_ms is not None
                    else None,
                    "overnight_low_c": float(weather_row.overnight_low_c)
                    if weather_row and weather_row.overnight_low_c is not None
                    else None,
                    "overnight_wind_max_mph": float(weather_row.overnight_wind_max_mph)
                    if weather_row and weather_row.overnight_wind_max_mph is not None
                    else None,
                    "bedroom_warning_minutes": bedroom.warning_minutes if bedroom else None,
                    "bedroom_critical_minutes": bedroom.critical_minutes if bedroom else None,
                    "bedroom_fan_ran_minutes": bedroom.fan_ran_minutes if bedroom else None,
                    "bedroom_peak_fan_speed": bedroom.peak_fan_speed if bedroom else None,
                    "prev_day_training_load": prev_load,
                    "daytime_stress_avg": float(metric.stress_avg)
                    if metric and metric.stress_avg is not None
                    else None,
                    "resting_heart_rate_bpm": float(metric.resting_heart_rate_bpm)
                    if metric and metric.resting_heart_rate_bpm is not None
                    else None,
                    "sleep_stress_avg": float(sleep.avg_sleep_stress)
                    if sleep and sleep.avg_sleep_stress is not None
                    else None,
                }
            )
        return records

    async def drivers(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
        lookback_days: int = DRIVERS_LOOKBACK_DAYS,
    ) -> DriversReport:
        end = as_of or date.today()
        start = end - timedelta(days=lookback_days)
        records = await self._driver_records(player, start=start, end=end)
        outcomes = {
            OUTCOME_SLEEP_SCORE: compute_drivers(
                records, outcome_key=OUTCOME_SLEEP_SCORE, driver_keys=DRIVER_KEYS
            ),
            OUTCOME_RECOVERY_HRV: compute_drivers(
                records, outcome_key=OUTCOME_RECOVERY_HRV, driver_keys=DRIVER_KEYS
            ),
        }
        return DriversReport(
            outcomes=outcomes,
            record_count=len(records),
            window_start=start if records else None,
            window_end=end if records else None,
        )

    async def record_drivers(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
        commit: bool = True,
    ) -> DriversReport:
        """Compute the driver correlations and cache them in the ``analyses`` audit row.

        Batch 62.2: the 120-day driver correlation is deterministic per synced day,
        so the morning pipeline computes it once and stores it. ``_envelope`` then
        reads it back via :meth:`cached_drivers` instead of recomputing on every
        open. Idempotent per ``subject_date`` (reuses the ``driver_correlation``
        audit row) and only records once there is enough history, mirroring the
        gate in :meth:`run`.
        """
        today = as_of or date.today()
        report = await self.drivers(player, as_of=today)
        if report.record_count >= MIN_CORRELATION_SAMPLES and not await self._already_recorded(
            player, AUDIT_TYPE_DRIVERS, today
        ):
            self._record_audit(
                player,
                AUDIT_TYPE_DRIVERS,
                today,
                _drivers_packet(report),
                _drivers_markdown(report),
            )
            if commit:
                await self.session.commit()
        return report

    async def cached_drivers(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
    ) -> DriversReport:
        """Return the cached driver report for the day, falling back to live compute.

        Batch 62.2 read-through: on the hot ``GET /api/v1/daily-loop`` path, prefer
        the packet the morning pipeline already stored for ``as_of``; recompute live
        only when it is missing (a new user, a failed sync, or a past ``subjectDate``
        with no stored row). The cache is an optimisation, never a correctness
        dependency — the fallback returns the identical report.
        """
        today = as_of or date.today()
        packet = await self.session.scalar(
            select(Analysis.context_packet)
            .where(
                Analysis.user_id == player.id,
                Analysis.analysis_type == AUDIT_TYPE_DRIVERS,
                Analysis.subject_date == today,
            )
            .order_by(Analysis.generated_at_utc.desc())
            .limit(1)
        )
        if isinstance(packet, dict) and "outcomes" in packet:
            return _drivers_report_from_packet(packet)
        return await self.drivers(player, as_of=today)

    async def _already_recorded(
        self, player: Profile, analysis_type: str, subject_date: date
    ) -> bool:
        existing = await self.session.scalar(
            select(Analysis.id).where(
                Analysis.user_id == player.id,
                Analysis.analysis_type == analysis_type,
                Analysis.subject_date == subject_date,
            )
        )
        return existing is not None

    def _record_audit(
        self,
        player: Profile,
        analysis_type: str,
        subject_date: date,
        context_packet: dict[str, Any],
        markdown: str,
        *,
        verdict: str | None = None,
    ) -> None:
        self.session.add(
            Analysis(
                user_id=player.id,
                activity_id=None,
                analysis_type=analysis_type,
                subject_date=subject_date,
                generated_at_utc=_utcnow(),
                prompt_version=PROMPT_VERSION,
                model_name=None,
                verdict=verdict,
                context_packet=context_packet,
                output_markdown=markdown,
                raw_response={},
            )
        )

    async def run(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Compute all three insights and audit the actionable ones.

        Idempotent per ``subject_date``: an insight already recorded for the day
        is not duplicated. FTP drift is audited only when it actually drifted, the
        early warning only when it fired, and drivers whenever there is enough
        history — so the audit log stays a record of *findings*, not noise.
        """
        today = as_of or date.today()
        drift = await self.ftp_drift(player, as_of=today)
        warning = await self.early_warning(player, as_of=today)
        drivers_report = await self.drivers(player, as_of=today)

        recorded: list[str] = []

        if drift.status in {"rising", "falling"} and not await self._already_recorded(
            player, AUDIT_TYPE_FTP_DRIFT, today
        ):
            self._record_audit(
                player,
                AUDIT_TYPE_FTP_DRIFT,
                today,
                _ftp_drift_packet(drift),
                "\n".join(drift.reasons),
            )
            recorded.append(AUDIT_TYPE_FTP_DRIFT)

        if warning.fired and not await self._already_recorded(
            player, AUDIT_TYPE_EARLY_WARNING, today
        ):
            self._record_audit(
                player,
                AUDIT_TYPE_EARLY_WARNING,
                today,
                _early_warning_packet(warning),
                "Early warning: " + "; ".join(warning.reasons),
            )
            recorded.append(AUDIT_TYPE_EARLY_WARNING)

        if (
            drivers_report.record_count >= MIN_CORRELATION_SAMPLES
            and not await self._already_recorded(player, AUDIT_TYPE_DRIVERS, today)
        ):
            self._record_audit(
                player,
                AUDIT_TYPE_DRIVERS,
                today,
                _drivers_packet(drivers_report),
                _drivers_markdown(drivers_report),
            )
            recorded.append(AUDIT_TYPE_DRIVERS)

        if commit:
            await self.session.commit()
        return {
            "ftpDrift": drift,
            "earlyWarning": warning,
            "drivers": drivers_report,
            "recorded": recorded,
        }


def _ftp_drift_packet(drift: FtpDriftResult) -> dict[str, Any]:
    return {
        "status": drift.status,
        "sampleCount": drift.sample_count,
        "windowStart": drift.window_start.isoformat() if drift.window_start else None,
        "windowEnd": drift.window_end.isoformat() if drift.window_end else None,
        "baselineEf": drift.baseline_ef,
        "recentEf": drift.recent_ef,
        "pctChange": drift.pct_change,
        "currentFtpWatts": drift.current_ftp_watts,
        "suggestedFtpWatts": drift.suggested_ftp_watts,
        "reasons": drift.reasons,
    }


def _early_warning_packet(warning: EarlyWarningResult) -> dict[str, Any]:
    return {
        "status": warning.status,
        "fired": warning.fired,
        "windowStart": warning.window_start.isoformat() if warning.window_start else None,
        "windowEnd": warning.window_end.isoformat() if warning.window_end else None,
        "hrvSlope": warning.hrv_slope,
        "sleepSlope": warning.sleep_slope,
        "readinessSlope": warning.readiness_slope,
        "degradingMetrics": warning.degrading_metrics,
        "reasons": warning.reasons,
    }


def _drivers_packet(report: DriversReport) -> dict[str, Any]:
    return {
        "recordCount": report.record_count,
        "windowStart": report.window_start.isoformat() if report.window_start else None,
        "windowEnd": report.window_end.isoformat() if report.window_end else None,
        "outcomes": {
            outcome: [
                {
                    "driver": c.driver,
                    "coefficient": c.coefficient,
                    "direction": c.direction,
                    "sampleCount": c.sample_count,
                    "summary": c.summary,
                }
                for c in correlations
            ]
            for outcome, correlations in report.outcomes.items()
        },
    }


def _drivers_report_from_packet(packet: dict[str, Any]) -> DriversReport:
    """Rebuild a :class:`DriversReport` from a stored ``_drivers_packet`` dict.

    The inverse of :func:`_drivers_packet`; ``direction`` is a derived property on
    :class:`DriverCorrelation`, so it is recomputed from the coefficient rather than
    read back. Used by :meth:`InsightsService.cached_drivers`.
    """

    def _parse_date(value: Any) -> date | None:
        return date.fromisoformat(value) if isinstance(value, str) else None

    outcomes: dict[str, list[DriverCorrelation]] = {}
    for outcome, correlations in (packet.get("outcomes") or {}).items():
        outcomes[outcome] = [
            DriverCorrelation(
                driver=c["driver"],
                outcome=outcome,
                coefficient=c["coefficient"],
                sample_count=c["sampleCount"],
                summary=c.get("summary"),
            )
            for c in correlations
        ]
    return DriversReport(
        outcomes=outcomes,
        record_count=int(packet.get("recordCount", 0)),
        window_start=_parse_date(packet.get("windowStart")),
        window_end=_parse_date(packet.get("windowEnd")),
    )


def _drivers_markdown(report: DriversReport) -> str:
    lines = [f"Driver analysis over {report.record_count} nights."]
    for outcome, correlations in report.outcomes.items():
        if not correlations:
            continue
        top = correlations[0]
        lines.append(
            f"- Strongest mover of {outcome}: {top.driver} ({top.direction}, r={top.coefficient}).",
        )
    return "\n".join(lines)
