"""Year-on-year & seasonal trend engine (Batch 21).

The long-horizon lens: this period versus the same period last year, plus
seasonal patterns (winter-vs-summer sleep, FTP/VO2 seasonality, thermal). Like
the v3 review boundary (DECISIONS #81/#82) it splits into a *deterministic*
aggregation and an *optional narrative*:

  * **21.1 Seasonal/period aggregation.** ``compute_trend_windows`` buckets plain
    daily samples into comparable month/season windows and computes reproducible
    per-metric summary stats (count/mean/median/min/max). It is a pure function
    over ``TrendSample`` values, so the maths is inspectable and unit-testable
    without a database. The SpO2/HRV reliability cutoff (#45) is honoured: rows
    before ``RELIABILITY_START_DATE`` are dropped from those two metrics only and
    surfaced as an explicit excluded-sample count (the ``metric_baselines``
    provenance pattern, #44).

  * **21.2 Year-on-year comparison.** ``compute_year_on_year`` lines a window up
    against the same period one year earlier and reports same-period deltas. It
    degrades gracefully — reporting ``insufficient_history`` per metric and
    overall rather than misleading numbers — until a full prior-year window with
    enough samples exists (history starts ~24 Mar 2026, so true YoY ~Mar 2027).

  * **21.4 Optional narrative.** When enough history exists the comparison is
    summarised through the Batch 20 Anthropic boundary (#47, reused here) and
    stored in ``analyses`` under ``analysis_type='seasonal_trend'``; otherwise the
    service reports "insufficient history" deterministically and never calls the
    model.

``TrendsService`` is the thin DB wrapper. Following #71 the engine is
human/API-triggered: ``GET /api/v1/trends/*`` previews never write; only
``POST /api/v1/trends/narrative/run`` records. No new migration — outputs land in
the existing ``analyses`` table.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Analysis,
    DailyMetric,
    KnowledgeBase,
    MetricBaseline,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.personal_baselines import baseline_band_packet
from src.services.reviews import (
    AnthropicReviewClient,
    ClaudeReviewResult,
    ReviewClient,
    ReviewError,
)

# Bucketing
BUCKET_MONTH = "month"
BUCKET_SEASON = "season"
VALID_BUCKETS = (BUCKET_MONTH, BUCKET_SEASON)

# SpO2/HRV reliability boundary (DECISIONS #45) — rows before this are excluded
# from those two metrics only; all other history is kept intact.
RELIABILITY_START_DATE = date(2026, 6, 11)
RELIABILITY_GATED_METRICS = frozenset({"hrv_ms", "avg_spo2_pct"})

# Year-on-year needs a real prior-year window, not a single stray night.
MIN_YOY_SAMPLES = 5

# How far back to load samples so the prior-year window is available for YoY.
DEFAULT_LOOKBACK_DAYS = 800
DEFAULT_MONTH_WINDOWS = 12
DEFAULT_SEASON_WINDOWS = 8

ANALYSIS_TYPE_SEASONAL = "seasonal_trend"
PROMPT_VERSION_BY_BUCKET = {
    BUCKET_MONTH: "trends-month-v3-2026-07-05",
    BUCKET_SEASON: "trends-season-v3-2026-07-05",
}

# Indoor reading at/after this local hour belongs to the *next* morning's night.
_EVENING_HOUR = 18

TREND_SYSTEM_PROMPT = """You are Garmin Coach, a private endurance and sleep \
coach writing a long-horizon trend summary.
Use only the supplied deterministic trend packet. Compare this period against the \
same period last year and across seasons. Write concise markdown with three \
bolded sections — **Year-on-year**, **Seasonal patterns**, and \
**What to watch** — each a short bullet list grounded in the packet's numbers. \
Never mention left/right power balance. Treat SpO2 and HRV before the reliability \
cutoff as excluded. When sample counts are low or a prior-year window is missing, \
say "insufficient history" plainly rather than inventing a trend. Interpret \
readiness, HRV, and resting HR against personalBaselines before using alarming \
language. Every year-on-year claim must cite the currentMean -> priorMean or \
priorMean -> currentMean numbers plus both sample counts; every seasonal claim \
must cite the window labels and sampleDays or metric sampleCount. If a metric \
has status insufficient_history, describe the data gap instead of a change."""

# Metric registry: stable order + display labels for every tracked metric.
METRICS: tuple[tuple[str, str], ...] = (
    ("sleep_score", "Sleep score"),
    ("sleep_duration_min", "Sleep duration (min)"),
    ("hrv_ms", "Overnight HRV (ms)"),
    ("readiness_score", "Training readiness"),
    ("resting_hr_bpm", "Resting HR (bpm)"),
    ("vo2max", "VO2 max"),
    ("avg_spo2_pct", "Overnight SpO2 (%)"),
    ("indoor_peak_c", "Indoor peak (°C)"),
    ("overnight_low_c", "Outdoor overnight low (°C)"),
)
METRIC_KEYS: tuple[str, ...] = tuple(key for key, _ in METRICS)
METRIC_LABELS: dict[str, str] = dict(METRICS)

_SEASON_BY_MONTH = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}
_SEASON_FIRST_MONTH = {"winter": 12, "spring": 3, "summer": 6, "autumn": 9}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Window keys / labels (pure, calendar-aligned → stable subject_date)
# ---------------------------------------------------------------------------


def season_of(day: date) -> tuple[int, str]:
    """Return ``(season_year, season)`` for ``day``.

    Meteorological seasons; December rolls into the *following* year's winter so
    a winter window (Dec–Feb) is contiguous and comparable year on year.
    """
    season = _SEASON_BY_MONTH[day.month]
    year = day.year + 1 if day.month == 12 else day.year
    return year, season


def window_key(bucket: str, day: date) -> str:
    if bucket == BUCKET_MONTH:
        return f"{day.year:04d}-{day.month:02d}"
    if bucket == BUCKET_SEASON:
        year, season = season_of(day)
        return f"{year:04d}-{season}"
    raise ValueError(f"Unknown trend bucket: {bucket!r}")


def window_label(bucket: str, key: str) -> str:
    if bucket == BUCKET_MONTH:
        year, month = key.split("-")
        name = date(int(year), int(month), 1).strftime("%B")
        return f"{name} {year}"
    year, season = key.split("-")
    return f"{season.capitalize()} {year}"


def window_start_date(bucket: str, key: str) -> date:
    """Canonical first calendar day of a window — the stable ``subject_date``."""
    if bucket == BUCKET_MONTH:
        year, month = key.split("-")
        return date(int(year), int(month), 1)
    year, season = key.split("-")
    first_month = _SEASON_FIRST_MONTH[season]
    # Winter's first month (December) falls in the prior calendar year.
    start_year = int(year) - 1 if season == "winter" else int(year)
    return date(start_year, first_month, 1)


def prior_year_key(bucket: str, key: str) -> str:
    """The key for the same period one calendar year earlier."""
    head, tail = key.split("-", 1)
    return f"{int(head) - 1:04d}-{tail}"


# ---------------------------------------------------------------------------
# Plain samples + summary stats (no DB dependency → pure-testable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrendSample:
    day: date
    sleep_score: int | None = None
    sleep_duration_min: int | None = None
    hrv_ms: float | None = None
    readiness_score: int | None = None
    resting_hr_bpm: int | None = None
    vo2max: float | None = None
    avg_spo2_pct: float | None = None
    indoor_peak_c: float | None = None
    overnight_low_c: float | None = None


@dataclass(frozen=True)
class MetricSummary:
    metric_key: str
    sample_count: int
    excluded_count: int
    mean: float | None
    median: float | None
    min: float | None
    max: float | None


@dataclass(frozen=True)
class TrendWindow:
    bucket: str
    key: str
    label: str
    start: date
    end: date
    sample_days: int
    metrics: dict[str, MetricSummary]


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _summarise_metric(
    metric_key: str,
    samples: Sequence[TrendSample],
    *,
    reliability_start_date: date,
) -> MetricSummary:
    present: list[float] = []
    excluded = 0
    gated = metric_key in RELIABILITY_GATED_METRICS
    for sample in samples:
        value = getattr(sample, metric_key)
        if value is None:
            continue
        if gated and sample.day < reliability_start_date:
            excluded += 1
            continue
        present.append(float(value))
    if not present:
        return MetricSummary(
            metric_key=metric_key,
            sample_count=0,
            excluded_count=excluded,
            mean=None,
            median=None,
            min=None,
            max=None,
        )
    return MetricSummary(
        metric_key=metric_key,
        sample_count=len(present),
        excluded_count=excluded,
        mean=round(sum(present) / len(present), 2),
        median=round(_median(present), 2),
        min=round(min(present), 2),
        max=round(max(present), 2),
    )


def _has_any_metric(sample: TrendSample) -> bool:
    return any(getattr(sample, key) is not None for key in METRIC_KEYS)


def compute_trend_windows(
    samples: Sequence[TrendSample],
    *,
    bucket: str,
    reliability_start_date: date = RELIABILITY_START_DATE,
) -> list[TrendWindow]:
    """Bucket samples into comparable windows with per-metric summary stats.

    Pure function — no DB, no LLM — so every count, mean and median is
    reproducible and unit-testable. Returned chronologically by window key.
    """
    if bucket not in VALID_BUCKETS:
        raise ValueError(f"Unknown trend bucket: {bucket!r}")

    grouped: dict[str, list[TrendSample]] = {}
    for sample in samples:
        grouped.setdefault(window_key(bucket, sample.day), []).append(sample)

    windows: list[TrendWindow] = []
    for key in sorted(grouped):
        group = grouped[key]
        days = [s.day for s in group]
        metrics = {
            metric_key: _summarise_metric(
                metric_key, group, reliability_start_date=reliability_start_date
            )
            for metric_key in METRIC_KEYS
        }
        windows.append(
            TrendWindow(
                bucket=bucket,
                key=key,
                label=window_label(bucket, key),
                start=min(days),
                end=max(days),
                sample_days=sum(1 for s in group if _has_any_metric(s)),
                metrics=metrics,
            )
        )
    return windows


# ---------------------------------------------------------------------------
# Year-on-year comparison (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YoYMetricDelta:
    metric_key: str
    current_mean: float | None
    prior_mean: float | None
    delta: float | None
    pct_change: float | None
    current_sample_count: int
    prior_sample_count: int
    status: str  # ok | insufficient_history


@dataclass(frozen=True)
class YearOnYearComparison:
    bucket: str
    status: str  # ok | insufficient_history | no_current_data
    current_key: str | None
    prior_key: str | None
    current_label: str | None
    prior_label: str | None
    metrics: list[YoYMetricDelta]
    reasons: list[str]


def compute_year_on_year(
    windows: Sequence[TrendWindow],
    *,
    bucket: str,
    target_key: str,
    min_samples: int = MIN_YOY_SAMPLES,
) -> YearOnYearComparison:
    """Compare ``target_key`` against the same window one year earlier.

    Each metric is judged independently: it needs at least ``min_samples`` in
    *both* the current and prior-year windows to yield a delta, otherwise it is
    ``insufficient_history``. With no qualifying metric the whole comparison is
    ``insufficient_history`` — the expected state until a year of data exists.
    """
    by_key = {w.key: w for w in windows}
    current = by_key.get(target_key)
    prior_key = prior_year_key(bucket, target_key)
    if current is None:
        return YearOnYearComparison(
            bucket=bucket,
            status="no_current_data",
            current_key=None,
            prior_key=prior_key,
            current_label=window_label(bucket, target_key),
            prior_label=window_label(bucket, prior_key),
            metrics=[],
            reasons=[f"No data for the current window ({window_label(bucket, target_key)})."],
        )

    prior = by_key.get(prior_key)
    metrics: list[YoYMetricDelta] = []
    any_ok = False
    for metric_key in METRIC_KEYS:
        cur = current.metrics.get(metric_key)
        pri = prior.metrics.get(metric_key) if prior is not None else None
        cur_n = cur.sample_count if cur else 0
        pri_n = pri.sample_count if pri else 0
        if (
            cur is not None
            and pri is not None
            and cur.mean is not None
            and pri.mean is not None
            and cur_n >= min_samples
            and pri_n >= min_samples
        ):
            delta = round(cur.mean - pri.mean, 2)
            pct = round(delta / abs(pri.mean), 4) if pri.mean != 0 else None
            metrics.append(
                YoYMetricDelta(
                    metric_key=metric_key,
                    current_mean=cur.mean,
                    prior_mean=pri.mean,
                    delta=delta,
                    pct_change=pct,
                    current_sample_count=cur_n,
                    prior_sample_count=pri_n,
                    status="ok",
                )
            )
            any_ok = True
        else:
            metrics.append(
                YoYMetricDelta(
                    metric_key=metric_key,
                    current_mean=cur.mean if cur else None,
                    prior_mean=pri.mean if pri else None,
                    delta=None,
                    pct_change=None,
                    current_sample_count=cur_n,
                    prior_sample_count=pri_n,
                    status="insufficient_history",
                )
            )

    reasons: list[str] = []
    if not any_ok:
        reasons.append(
            f"No prior-year window ({window_label(bucket, prior_key)}) with "
            f"≥{min_samples} samples yet — year-on-year comparison needs a full "
            "year of history."
        )
    return YearOnYearComparison(
        bucket=bucket,
        status="ok" if any_ok else "insufficient_history",
        current_key=target_key,
        prior_key=prior_key,
        current_label=current.label,
        prior_label=window_label(bucket, prior_key),
        metrics=metrics,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Serialization helpers (camelCase JSON)
# ---------------------------------------------------------------------------


def _metric_summary_json(summary: MetricSummary) -> dict[str, Any]:
    return {
        "metricKey": summary.metric_key,
        "label": METRIC_LABELS.get(summary.metric_key, summary.metric_key),
        "sampleCount": summary.sample_count,
        "excludedCount": summary.excluded_count,
        "mean": summary.mean,
        "median": summary.median,
        "min": summary.min,
        "max": summary.max,
    }


def window_json(window: TrendWindow) -> dict[str, Any]:
    return {
        "bucket": window.bucket,
        "key": window.key,
        "label": window.label,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "sampleDays": window.sample_days,
        "metrics": [_metric_summary_json(window.metrics[key]) for key in METRIC_KEYS],
    }


def _yoy_metric_json(delta: YoYMetricDelta) -> dict[str, Any]:
    return {
        "metricKey": delta.metric_key,
        "label": METRIC_LABELS.get(delta.metric_key, delta.metric_key),
        "currentMean": delta.current_mean,
        "priorMean": delta.prior_mean,
        "delta": delta.delta,
        "pctChange": delta.pct_change,
        "currentSampleCount": delta.current_sample_count,
        "priorSampleCount": delta.prior_sample_count,
        "status": delta.status,
    }


def year_on_year_json(comparison: YearOnYearComparison) -> dict[str, Any]:
    return {
        "bucket": comparison.bucket,
        "status": comparison.status,
        "currentKey": comparison.current_key,
        "priorKey": comparison.prior_key,
        "currentLabel": comparison.current_label,
        "priorLabel": comparison.prior_label,
        "metrics": [_yoy_metric_json(d) for d in comparison.metrics],
        "reasons": comparison.reasons,
    }


# ---------------------------------------------------------------------------
# Service result wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeasonalResult:
    bucket: str
    windows: list[TrendWindow]


@dataclass(frozen=True)
class NarrativePreview:
    bucket: str
    target_key: str
    subject_date: date
    comparison: YearOnYearComparison
    windows: list[TrendWindow]
    packet: dict[str, Any]
    latest_narrative: Analysis | None


@dataclass(frozen=True)
class NarrativeRunResult:
    preview: NarrativePreview
    narrative: Analysis | None
    generated: bool
    status: str  # generated | existing | insufficient_history


# ---------------------------------------------------------------------------
# DB service
# ---------------------------------------------------------------------------


class TrendsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def seasonal(
        self,
        player: Profile,
        *,
        bucket: str,
        as_of: date | None = None,
        window_count: int | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> SeasonalResult:
        """Recent per-window summary stats. Never writes (#71)."""
        if bucket not in VALID_BUCKETS:
            raise ValueError(f"Unknown trend bucket: {bucket!r}")
        end = as_of or date.today()
        windows = await self._windows(player, bucket=bucket, as_of=end, lookback_days=lookback_days)
        limit = window_count or (
            DEFAULT_MONTH_WINDOWS if bucket == BUCKET_MONTH else DEFAULT_SEASON_WINDOWS
        )
        return SeasonalResult(bucket=bucket, windows=windows[-limit:])

    async def year_on_year(
        self,
        player: Profile,
        *,
        bucket: str,
        as_of: date | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> YearOnYearComparison:
        """Same-period-vs-prior-year deltas. Never writes (#71)."""
        if bucket not in VALID_BUCKETS:
            raise ValueError(f"Unknown trend bucket: {bucket!r}")
        end = as_of or date.today()
        windows = await self._windows(player, bucket=bucket, as_of=end, lookback_days=lookback_days)
        return compute_year_on_year(windows, bucket=bucket, target_key=window_key(bucket, end))

    async def narrative_preview(
        self,
        player: Profile,
        *,
        bucket: str,
        as_of: date | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> NarrativePreview:
        if bucket not in VALID_BUCKETS:
            raise ValueError(f"Unknown trend bucket: {bucket!r}")
        end = as_of or date.today()
        windows = await self._windows(player, bucket=bucket, as_of=end, lookback_days=lookback_days)
        target_key = window_key(bucket, end)
        comparison = compute_year_on_year(windows, bucket=bucket, target_key=target_key)
        subject_date = window_start_date(bucket, target_key)
        guardrails = await self._data_quality_guardrails(player.id)
        baselines = await self._metric_baselines(player.id)
        packet = _build_packet(
            player=player,
            bucket=bucket,
            comparison=comparison,
            windows=windows,
            guardrails=guardrails,
            baselines=baselines,
        )
        latest = await self.latest_narrative(player.id, bucket, subject_date)
        return NarrativePreview(
            bucket=bucket,
            target_key=target_key,
            subject_date=subject_date,
            comparison=comparison,
            windows=windows,
            packet=packet,
            latest_narrative=latest,
        )

    async def narrative_run(
        self,
        player: Profile,
        *,
        bucket: str,
        as_of: date | None = None,
        client: ReviewClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> NarrativeRunResult:
        """Summarise the comparison through the Batch 20 boundary (21.4).

        Reports "insufficient history" deterministically — without calling the
        model — until a real prior-year window exists. Idempotent per window.
        """
        preview = await self.narrative_preview(
            player, bucket=bucket, as_of=as_of, lookback_days=DEFAULT_LOOKBACK_DAYS
        )
        if preview.comparison.status != "ok":
            return NarrativeRunResult(
                preview=preview,
                narrative=None,
                generated=False,
                status="insufficient_history",
            )
        if not force and preview.latest_narrative is not None:
            return NarrativeRunResult(
                preview=preview,
                narrative=preview.latest_narrative,
                generated=False,
                status="existing",
            )

        user_prompt = build_trend_user_prompt(preview.packet)
        review_client = client or AnthropicReviewClient(system_prompt=TREND_SYSTEM_PROMPT)
        generation = await review_client.generate(
            context_packet=preview.packet,
            user_prompt=user_prompt,
        )
        analysis = Analysis(
            user_id=player.id,
            activity_id=None,
            analysis_type=ANALYSIS_TYPE_SEASONAL,
            subject_date=preview.subject_date,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION_BY_BUCKET[bucket],
            model_name=generation.model_name,
            verdict=None,
            context_packet=preview.packet,
            output_markdown=generation.output_markdown,
            raw_response=generation.raw_response,
        )
        self.session.add(analysis)
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
        else:
            await self.session.flush()
        return NarrativeRunResult(
            preview=preview,
            narrative=analysis,
            generated=True,
            status="generated",
        )

    async def latest_narrative(
        self, user_id: uuid.UUID, bucket: str, subject_date: date
    ) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == ANALYSIS_TYPE_SEASONAL,
                    Analysis.subject_date == subject_date,
                    Analysis.prompt_version == PROMPT_VERSION_BY_BUCKET[bucket],
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    # -- sample assembly ----------------------------------------------------

    async def _windows(
        self,
        player: Profile,
        *,
        bucket: str,
        as_of: date,
        lookback_days: int,
    ) -> list[TrendWindow]:
        start = as_of - timedelta(days=lookback_days)
        samples = await self._load_samples(player, start=start, end=as_of)
        return compute_trend_windows(samples, bucket=bucket)

    async def _load_samples(self, player: Profile, *, start: date, end: date) -> list[TrendSample]:
        metrics = await self._rows(DailyMetric, player.id, start, end)
        sleeps = await self._rows(Sleep, player.id, start, end)
        weather = await self._rows(WeatherDaily, player.id, start, end)
        indoor = await self._indoor_peaks(player.id, start, end, player.timezone)

        metric_by_date = {m.calendar_date: m for m in metrics}
        sleep_by_date = {s.calendar_date: s for s in sleeps}
        weather_by_date = {w.calendar_date: w for w in weather}
        all_days = set(metric_by_date) | set(sleep_by_date) | set(weather_by_date) | set(indoor)

        samples: list[TrendSample] = []
        for day in sorted(all_days):
            metric = metric_by_date.get(day)
            sleep = sleep_by_date.get(day)
            weather_row = weather_by_date.get(day)
            samples.append(
                TrendSample(
                    day=day,
                    sleep_score=sleep.score if sleep else None,
                    sleep_duration_min=_minutes(sleep.duration_sec) if sleep else None,
                    hrv_ms=_as_float(metric.hrv_last_night_avg_ms) if metric else None,
                    readiness_score=metric.readiness_score if metric else None,
                    resting_hr_bpm=metric.resting_heart_rate_bpm if metric else None,
                    vo2max=_as_float(metric.vo2max) if metric else None,
                    avg_spo2_pct=_as_float(sleep.average_spo2_pct) if sleep else None,
                    indoor_peak_c=indoor.get(day),
                    overnight_low_c=_as_float(weather_row.overnight_low_c) if weather_row else None,
                )
            )
        return samples

    async def _rows(self, model: Any, user_id: uuid.UUID, start: date, end: date) -> list[Any]:
        rows = (
            (
                await self.session.execute(
                    select(model).where(
                        model.user_id == user_id,
                        model.calendar_date >= start,
                        model.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _indoor_peaks(
        self, user_id: uuid.UUID, start: date, end: date, timezone_name: str
    ) -> dict[date, float]:
        """Peak indoor temperature per local night, keyed by the wake date."""
        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        win_start = datetime.combine(start - timedelta(days=1), datetime.min.time())
        win_end = datetime.combine(end, datetime.max.time())
        rows = (
            (
                await self.session.execute(
                    select(TemperatureReading).where(
                        TemperatureReading.user_id == user_id,
                        TemperatureReading.captured_at_utc >= win_start,
                        TemperatureReading.captured_at_utc <= win_end,
                    )
                )
            )
            .scalars()
            .all()
        )
        peaks: dict[date, float] = {}
        for row in rows:
            local = row.captured_at_utc.replace(tzinfo=UTC).astimezone(tz)
            wake_date = (
                local.date() + timedelta(days=1) if local.hour >= _EVENING_HOUR else local.date()
            )
            if not (start <= wake_date <= end):
                continue
            current = peaks.get(wake_date)
            if current is None or row.temperature_c > current:
                peaks[wake_date] = row.temperature_c
        return peaks

    async def _data_quality_guardrails(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        section = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == "data_quality_rules",
                KnowledgeBase.is_active.is_(True),
            )
        )
        if section and isinstance(section.content, dict):
            rules = section.content.get("rules")
            if isinstance(rules, list):
                return [rule for rule in rules if isinstance(rule, dict)]
        return []

    async def _metric_baselines(self, user_id: uuid.UUID) -> list[MetricBaseline]:
        rows = (
            (
                await self.session.execute(
                    select(MetricBaseline)
                    .where(MetricBaseline.user_id == user_id)
                    .order_by(MetricBaseline.metric_key.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


# ---------------------------------------------------------------------------
# Packet serialization (narrative input)
# ---------------------------------------------------------------------------


def _build_packet(
    *,
    player: Profile,
    bucket: str,
    comparison: YearOnYearComparison,
    windows: Sequence[TrendWindow],
    guardrails: list[dict[str, Any]],
    baselines: Sequence[MetricBaseline] = (),
    recent_window_count: int = 6,
) -> dict[str, Any]:
    return {
        "packetType": "seasonal_trend",
        "bucket": bucket,
        "generatedAtUtc": _utcnow().isoformat() + "Z",
        "reliabilityStartDate": RELIABILITY_START_DATE.isoformat(),
        "profile": {
            "userId": str(player.id),
            "displayName": player.display_name,
            "timezone": player.timezone,
        },
        "yearOnYear": year_on_year_json(comparison),
        "recentWindows": [window_json(w) for w in list(windows)[-recent_window_count:]],
        "personalBaselines": baseline_band_packet(
            baselines,
            keys={"readiness_score", "hrv_7_day_avg_ms", "resting_heart_rate_bpm"},
        ),
        "dataQualityGuardrails": guardrails,
        "prompt": {
            "version": PROMPT_VERSION_BY_BUCKET[bucket],
            "system": TREND_SYSTEM_PROMPT,
            "outputRules": [
                "three_sections_year_on_year_seasonal_what_to_watch",
                "ground_every_claim_in_packet_numbers",
                "cite_from_to_numbers_and_sample_counts",
                "interpret_recovery_against_personal_baselines",
                "never_reference_left_right_power_balance",
                "exclude_pre_cutoff_spo2_and_hrv",
                "say_insufficient_history_when_prior_year_missing",
            ],
        },
    }


def build_trend_user_prompt(context_packet: Mapping[str, Any]) -> str:
    bucket = context_packet.get("bucket", "season")
    return (
        f"Write the {bucket} year-on-year & seasonal trend summary from this "
        "deterministic packet.\n\n"
        "Trend packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


# ---------------------------------------------------------------------------
# Re-exported boundary result for callers/tests
# ---------------------------------------------------------------------------

__all__ = [
    "ANALYSIS_TYPE_SEASONAL",
    "BUCKET_MONTH",
    "BUCKET_SEASON",
    "MIN_YOY_SAMPLES",
    "RELIABILITY_START_DATE",
    "VALID_BUCKETS",
    "ClaudeReviewResult",
    "MetricSummary",
    "NarrativePreview",
    "NarrativeRunResult",
    "ReviewError",
    "SeasonalResult",
    "TrendSample",
    "TrendWindow",
    "TrendsService",
    "YearOnYearComparison",
    "YoYMetricDelta",
    "compute_trend_windows",
    "compute_year_on_year",
    "season_of",
    "window_json",
    "window_key",
    "window_label",
    "window_start_date",
    "year_on_year_json",
]


def _as_float(value: float | int | None) -> float | None:
    return float(value) if value is not None else None


def _minutes(seconds: int | float | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None
