"""Weekly & monthly deep-review engine (Batch 20).

A periodic narrative deep-dive over the accumulated daily history — the way a
coach reviews a training block. Two halves, following the v3 boundary
(DECISIONS #81):

  * **20.1 Deterministic rollup packet.** ``compute_review_rollup`` aggregates a
    period's sleep, recovery/HRV/readiness, training load + adherence, morning
    verdicts and thermal/environment into a reproducible packet. It is a pure
    function over plain samples, so the maths is inspectable and unit-testable
    without a database. ``ReviewService`` is the thin DB wrapper that reads the
    rows, reuses the Batch 19 strength brief and Batch 17 insights, and attaches
    them to the packet.

  * **20.2 / 20.3 Claude review boundary.** The *narrative* (trends, wins,
    concerns, recommendations) is generated through the thin Anthropic Messages
    boundary reused from Batch 6 (#47) — ``prompt_version`` / ``model_name`` /
    raw response + markdown stored in ``analyses`` under ``analysis_type``
    ``weekly_review`` / ``monthly_review``. The boundary is fakeable in tests
    without ``ANTHROPIC_API_KEY``. The weekly and monthly variants share the
    rollup + boundary machinery, differing only in the period window.

Reviews are human/API-triggered (#71): ``preview`` assembles the packet and
never writes; ``run`` generates the narrative and records it, idempotent per
period. The narrative respects the data-quality guardrails carried in the packet
(no L/R balance, SpO2/HRV reliability window, wrist-HR strength excluded from
recovery, ignore the broken Duration column). No new migration — outputs land in
the existing ``analyses`` table.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.daily_loop import ANALYSIS_TYPE_MORNING
from src.services.insights import EarlyWarningResult, FtpDriftResult, InsightsService
from src.services.strength_brief import StrengthBriefResult, StrengthBriefService

PROMPT_VERSION = "reviews-v1-2026-06-23"
PACKET_VERSION = 1

PERIOD_WEEKLY = "weekly"
PERIOD_MONTHLY = "monthly"
VALID_PERIODS = (PERIOD_WEEKLY, PERIOD_MONTHLY)

ANALYSIS_TYPE_WEEKLY = "weekly_review"
ANALYSIS_TYPE_MONTHLY = "monthly_review"
_ANALYSIS_TYPE_BY_PERIOD = {
    PERIOD_WEEKLY: ANALYSIS_TYPE_WEEKLY,
    PERIOD_MONTHLY: ANALYSIS_TYPE_MONTHLY,
}

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Indoor temperature at/above this is treated as a thermal-disruption night
# (matches the morning-analysis default; the sleep protocol KB can refine it).
THERMAL_DISRUPTION_C = 20.0

SYSTEM_PROMPT = """You are Garmin Coach, a private endurance and sleep coach \
writing a periodic training-block review.
Use only the supplied deterministic rollup packet. Follow every data-quality \
guardrail in the packet. Write concise markdown with four bolded sections — \
**Trends**, **Wins**, **Concerns**, and **Recommendations** — each a short bullet \
list grounded in the packet's numbers. Never mention left/right power balance. \
Treat wrist-HR strength sessions as excluded from recovery/verdict decisions. \
Ignore the broken sleep Duration column. When sample counts are low, say so \
rather than overstating a trend. Recommendations must be concrete and \
actionable for the coming period."""


class ReviewError(RuntimeError):
    """Raised when a review narrative cannot be generated."""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Period windows (calendar-aligned, deterministic → idempotent per period)
# ---------------------------------------------------------------------------


def resolve_period_window(period: str, as_of: date) -> tuple[date, date]:
    """Return the ``(period_start, period_end)`` window for ``period``.

    Weekly is the ISO week (Mon–Sun) containing ``as_of``; monthly is the
    calendar month containing ``as_of``. Calendar alignment gives a stable
    ``subject_date`` (the period start) so ``run`` is idempotent per period.
    """
    if period == PERIOD_WEEKLY:
        start = as_of - timedelta(days=as_of.weekday())
        return start, start + timedelta(days=6)
    if period == PERIOD_MONTHLY:
        start = as_of.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        return start, next_month - timedelta(days=1)
    raise ValueError(f"Unknown review period: {period!r}")


# ---------------------------------------------------------------------------
# Plain rollup inputs (no DB dependency — testable as pure values)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewDay:
    day: date
    sleep_score: int | None = None
    age_adjusted_sleep_score: int | None = None
    sleep_duration_min: int | None = None
    deep_sleep_min: int | None = None
    rem_sleep_min: int | None = None
    hrv_ms: float | None = None
    readiness_score: int | None = None
    resting_hr_bpm: int | None = None
    body_battery_charged: int | None = None
    verdict: str | None = None


@dataclass(frozen=True)
class ReviewActivity:
    day: date
    activity_type: str
    duration_min: int | None = None
    training_load: float | None = None


@dataclass(frozen=True)
class ReviewAdherence:
    day: date
    status: str | None


@dataclass(frozen=True)
class ReviewThermalNight:
    day: date
    indoor_peak_c: float | None = None
    overnight_low_c: float | None = None


# ---------------------------------------------------------------------------
# Rollup result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SleepRollup:
    nights: int
    avg_score: float | None
    avg_age_adjusted_score: float | None
    avg_duration_min: float | None
    avg_deep_min: float | None
    avg_rem_min: float | None
    trend: str  # increasing | stable | decreasing | insufficient_data


@dataclass(frozen=True)
class RecoveryRollup:
    days: int
    avg_hrv_ms: float | None
    avg_readiness: float | None
    avg_resting_hr_bpm: float | None
    avg_body_battery_charged: float | None
    trend: str


@dataclass(frozen=True)
class LoadRollup:
    activity_count: int
    total_load: float
    total_duration_min: int
    by_type: dict[str, float]


@dataclass(frozen=True)
class AdherenceRollup:
    planned_count: int
    captured_count: int
    status_counts: dict[str, int]


@dataclass(frozen=True)
class VerdictRollup:
    green: int
    amber: int
    red: int
    total: int


@dataclass(frozen=True)
class ThermalRollup:
    nights: int
    avg_indoor_peak_c: float | None
    avg_overnight_low_c: float | None
    disruption_nights: int


@dataclass(frozen=True)
class ReviewRollup:
    period: str
    period_start: date
    period_end: date
    day_count: int
    sleep: SleepRollup
    recovery: RecoveryRollup
    training_load: LoadRollup
    adherence: AdherenceRollup
    verdicts: VerdictRollup
    thermal: ThermalRollup


# ---------------------------------------------------------------------------
# Aggregation helpers (pure)
# ---------------------------------------------------------------------------


def _avg(values: Sequence[float | int | None], *, ndigits: int = 1) -> float | None:
    present = [float(v) for v in values if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present), ndigits)


def _half_trend(
    days: Sequence[ReviewDay],
    key: str,
    *,
    higher_is_better: bool = True,
    min_each_half: int = 2,
) -> str:
    """Compare the first vs second half of the window for ``key``.

    Deterministic and DB-free. Needs at least ``min_each_half`` present values
    in *each* half to judge a direction, otherwise ``insufficient_data``.
    """
    ordered = sorted(days, key=lambda d: d.day)
    mid = len(ordered) // 2
    first = [getattr(d, key) for d in ordered[:mid]]
    second = [getattr(d, key) for d in ordered[mid:]]
    first_present = [float(v) for v in first if v is not None]
    second_present = [float(v) for v in second if v is not None]
    if len(first_present) < min_each_half or len(second_present) < min_each_half:
        return "insufficient_data"
    first_mean = sum(first_present) / len(first_present)
    second_mean = sum(second_present) / len(second_present)
    if first_mean == 0:
        return "stable"
    change = (second_mean - first_mean) / abs(first_mean)
    if abs(change) <= 0.05:
        return "stable"
    rising = change > 0
    improving = rising if higher_is_better else not rising
    return "increasing" if improving else "decreasing"


def compute_review_rollup(
    days: Sequence[ReviewDay],
    activities: Sequence[ReviewActivity],
    adherence: Sequence[ReviewAdherence],
    thermal: Sequence[ReviewThermalNight],
    *,
    period: str,
    period_start: date,
    period_end: date,
    planned_count: int,
    thermal_disruption_c: float = THERMAL_DISRUPTION_C,
) -> ReviewRollup:
    """Aggregate a period's daily samples into a deterministic rollup.

    Pure function over plain samples — no DB, no LLM — so every average, count
    and trend is reproducible and unit-testable.
    """
    sleep_nights = [
        d for d in days if d.sleep_score is not None or d.sleep_duration_min is not None
    ]
    sleep = SleepRollup(
        nights=len(sleep_nights),
        avg_score=_avg([d.sleep_score for d in days]),
        avg_age_adjusted_score=_avg([d.age_adjusted_sleep_score for d in days]),
        avg_duration_min=_avg([d.sleep_duration_min for d in days]),
        avg_deep_min=_avg([d.deep_sleep_min for d in days]),
        avg_rem_min=_avg([d.rem_sleep_min for d in days]),
        trend=_half_trend(days, "sleep_score", higher_is_better=True),
    )

    recovery_days = [d for d in days if d.hrv_ms is not None or d.readiness_score is not None]
    recovery = RecoveryRollup(
        days=len(recovery_days),
        avg_hrv_ms=_avg([d.hrv_ms for d in days]),
        avg_readiness=_avg([d.readiness_score for d in days]),
        avg_resting_hr_bpm=_avg([d.resting_hr_bpm for d in days]),
        avg_body_battery_charged=_avg([d.body_battery_charged for d in days]),
        trend=_half_trend(days, "readiness_score", higher_is_better=True),
    )

    by_type: dict[str, float] = {}
    total_load = 0.0
    total_duration = 0
    for activity in activities:
        load = float(activity.training_load or 0.0)
        total_load += load
        total_duration += int(activity.duration_min or 0)
        by_type[activity.activity_type] = round(by_type.get(activity.activity_type, 0.0) + load, 2)
    load_rollup = LoadRollup(
        activity_count=len(activities),
        total_load=round(total_load, 2),
        total_duration_min=total_duration,
        by_type=by_type,
    )

    status_counts: dict[str, int] = {}
    captured = 0
    for row in adherence:
        if row.status is None:
            continue
        captured += 1
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    adherence_rollup = AdherenceRollup(
        planned_count=planned_count,
        captured_count=captured,
        status_counts=status_counts,
    )

    green = amber = red = 0
    for d in days:
        verdict = (d.verdict or "").strip().lower()
        if verdict == "green":
            green += 1
        elif verdict == "amber":
            amber += 1
        elif verdict == "red":
            red += 1
    verdicts = VerdictRollup(green=green, amber=amber, red=red, total=green + amber + red)

    thermal_rollup = ThermalRollup(
        nights=len(thermal),
        avg_indoor_peak_c=_avg([t.indoor_peak_c for t in thermal]),
        avg_overnight_low_c=_avg([t.overnight_low_c for t in thermal]),
        disruption_nights=sum(
            1
            for t in thermal
            if t.indoor_peak_c is not None and t.indoor_peak_c >= thermal_disruption_c
        ),
    )

    return ReviewRollup(
        period=period,
        period_start=period_start,
        period_end=period_end,
        day_count=(period_end - period_start).days + 1,
        sleep=sleep,
        recovery=recovery,
        training_load=load_rollup,
        adherence=adherence_rollup,
        verdicts=verdicts,
        thermal=thermal_rollup,
    )


# ---------------------------------------------------------------------------
# Claude review boundary (#47 pattern, reused for weekly + monthly)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaudeReviewResult:
    output_markdown: str
    raw_response: dict[str, Any]
    model_name: str | None


class ReviewClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeReviewResult:
        """Generate the review narrative for an assembled rollup packet."""


class AnthropicReviewClient:
    """Thin HTTP boundary for Anthropic Messages (no SDK dependency, #47)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model_name = model_name or settings.anthropic_model
        self.max_tokens = max_tokens or settings.anthropic_max_tokens

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeReviewResult:
        if not self.api_key:
            raise ReviewError("ANTHROPIC_API_KEY is not configured.")

        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=payload)
            response.raise_for_status()
            raw = response.json()

        if not isinstance(raw, dict):
            raise ReviewError("Claude response was not a JSON object.")

        text_parts: list[str] = []
        content = raw.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
        output = "\n\n".join(text_parts).strip()
        if not output:
            raise ReviewError("Claude response did not contain text output.")

        model = raw.get("model")
        return ClaudeReviewResult(
            output_markdown=output,
            raw_response=raw,
            model_name=model if isinstance(model, str) else self.model_name,
        )


def build_review_user_prompt(context_packet: Mapping[str, Any]) -> str:
    period = context_packet.get("period", "weekly")
    return (
        f"Write the {period} Garmin Coach review from this deterministic rollup packet.\n\n"
        "Rollup packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


# ---------------------------------------------------------------------------
# Service result wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewPreview:
    period: str
    period_start: date
    period_end: date
    rollup: ReviewRollup
    strength_brief: StrengthBriefResult
    ftp_drift: FtpDriftResult
    early_warning: EarlyWarningResult
    packet: dict[str, Any]
    latest_review: Analysis | None


@dataclass(frozen=True)
class ReviewRunResult:
    preview: ReviewPreview
    review: Analysis
    generated: bool


# ---------------------------------------------------------------------------
# DB service
# ---------------------------------------------------------------------------


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def preview(
        self,
        player: Profile,
        period: str,
        *,
        as_of: date | None = None,
    ) -> ReviewPreview:
        """Assemble the deterministic rollup packet. Never writes (#71)."""
        if period not in VALID_PERIODS:
            raise ValueError(f"Unknown review period: {period!r}")
        end_anchor = as_of or date.today()
        period_start, period_end = resolve_period_window(period, end_anchor)

        rollup = await self._build_rollup(player, period, period_start, period_end)
        strength = await StrengthBriefService(self.session).brief(player, as_of=period_end)
        insights = InsightsService(self.session)
        ftp_drift = await insights.ftp_drift(player, as_of=period_end)
        early_warning = await insights.early_warning(player, as_of=period_end)
        guardrails = await self._data_quality_guardrails(player.id)

        packet = _build_packet(
            player=player,
            rollup=rollup,
            strength=strength,
            ftp_drift=ftp_drift,
            early_warning=early_warning,
            guardrails=guardrails,
        )
        latest_review = await self.latest_review(player.id, period, period_start)
        return ReviewPreview(
            period=period,
            period_start=period_start,
            period_end=period_end,
            rollup=rollup,
            strength_brief=strength,
            ftp_drift=ftp_drift,
            early_warning=early_warning,
            packet=packet,
            latest_review=latest_review,
        )

    async def run(
        self,
        player: Profile,
        period: str,
        *,
        as_of: date | None = None,
        client: ReviewClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> ReviewRunResult:
        """Generate the narrative and store it. Idempotent per period (#71)."""
        preview = await self.preview(player, period, as_of=as_of)
        if not force and preview.latest_review is not None:
            return ReviewRunResult(preview=preview, review=preview.latest_review, generated=False)

        user_prompt = build_review_user_prompt(preview.packet)
        review_client = client or AnthropicReviewClient()
        generation = await review_client.generate(
            context_packet=preview.packet,
            user_prompt=user_prompt,
        )
        analysis = Analysis(
            user_id=player.id,
            activity_id=None,
            analysis_type=_ANALYSIS_TYPE_BY_PERIOD[period],
            subject_date=preview.period_start,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION,
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
        return ReviewRunResult(preview=preview, review=analysis, generated=True)

    async def latest_review(
        self, user_id: uuid.UUID, period: str, period_start: date
    ) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == _ANALYSIS_TYPE_BY_PERIOD[period],
                    Analysis.subject_date == period_start,
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    # -- rollup assembly ----------------------------------------------------

    async def _build_rollup(
        self,
        player: Profile,
        period: str,
        period_start: date,
        period_end: date,
    ) -> ReviewRollup:
        metrics = await self._daily_metrics(player.id, period_start, period_end)
        sleeps = await self._sleeps(player.id, period_start, period_end)
        verdicts = await self._verdicts(player.id, period_start, period_end)
        activities = await self._activities(player.id, period_start, period_end)
        adherence_rows = await self._adherence(player.id, period_start, period_end)
        planned_count = await self._planned_count(player.id, period_start, period_end)
        weather = await self._weather(player.id, period_start, period_end)
        temps = await self._temperature_peaks(player.id, period_start, period_end, player.timezone)

        metric_by_date = {m.calendar_date: m for m in metrics}
        sleep_by_date = {s.calendar_date: s for s in sleeps}
        all_days = sorted(set(metric_by_date) | set(sleep_by_date) | set(verdicts))
        days = [
            ReviewDay(
                day=day,
                sleep_score=sleep_by_date[day].score if day in sleep_by_date else None,
                age_adjusted_sleep_score=(
                    sleep_by_date[day].age_adjusted_score if day in sleep_by_date else None
                ),
                sleep_duration_min=(
                    _minutes(sleep_by_date[day].duration_sec) if day in sleep_by_date else None
                ),
                deep_sleep_min=(
                    _minutes(sleep_by_date[day].deep_sleep_sec) if day in sleep_by_date else None
                ),
                rem_sleep_min=(
                    _minutes(sleep_by_date[day].rem_sleep_sec) if day in sleep_by_date else None
                ),
                hrv_ms=(
                    _as_float(metric_by_date[day].hrv_last_night_avg_ms)
                    if day in metric_by_date
                    else None
                ),
                readiness_score=(
                    metric_by_date[day].readiness_score if day in metric_by_date else None
                ),
                resting_hr_bpm=(
                    metric_by_date[day].resting_heart_rate_bpm if day in metric_by_date else None
                ),
                body_battery_charged=(
                    metric_by_date[day].body_battery_charged if day in metric_by_date else None
                ),
                verdict=verdicts.get(day),
            )
            for day in all_days
        ]

        review_activities = [
            ReviewActivity(
                day=row.start_utc.date(),
                activity_type=row.activity_type or "unknown",
                duration_min=_minutes(row.duration_sec),
                training_load=(float(row.training_load) if row.training_load is not None else None),
            )
            for row in activities
        ]
        review_adherence = [
            ReviewAdherence(day=row.entry_date, status=row.adherence_status)
            for row in adherence_rows
        ]

        weather_low_by_date = {w.calendar_date: w.overnight_low_c for w in weather}
        thermal_nights = [
            ReviewThermalNight(
                day=day,
                indoor_peak_c=temps.get(day),
                overnight_low_c=weather_low_by_date.get(day),
            )
            for day in sorted(set(temps) | set(weather_low_by_date))
        ]

        return compute_review_rollup(
            days,
            review_activities,
            review_adherence,
            thermal_nights,
            period=period,
            period_start=period_start,
            period_end=period_end,
            planned_count=planned_count,
        )

    async def _daily_metrics(self, user_id: uuid.UUID, start: date, end: date) -> list[DailyMetric]:
        rows = (
            (
                await self.session.execute(
                    select(DailyMetric).where(
                        DailyMetric.user_id == user_id,
                        DailyMetric.calendar_date >= start,
                        DailyMetric.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _sleeps(self, user_id: uuid.UUID, start: date, end: date) -> list[Sleep]:
        rows = (
            (
                await self.session.execute(
                    select(Sleep).where(
                        Sleep.user_id == user_id,
                        Sleep.calendar_date >= start,
                        Sleep.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _verdicts(self, user_id: uuid.UUID, start: date, end: date) -> dict[date, str | None]:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_MORNING,
                        Analysis.subject_date >= start,
                        Analysis.subject_date <= end,
                    )
                    .order_by(Analysis.generated_at_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        # Later rows overwrite earlier ones → the freshest verdict per day wins.
        return {row.subject_date: row.verdict for row in rows}

    async def _activities(self, user_id: uuid.UUID, start: date, end: date) -> list[Activity]:
        start_dt = datetime(start.year, start.month, start.day)
        end_dt = datetime(end.year, end.month, end.day) + timedelta(days=1)
        rows = (
            (
                await self.session.execute(
                    select(Activity).where(
                        Activity.user_id == user_id,
                        Activity.start_utc >= start_dt,
                        Activity.start_utc < end_dt,
                    )
                )
            )
            .scalars()
            .all()
        )
        return [row for row in rows if start <= row.start_utc.date() <= end]

    async def _adherence(self, user_id: uuid.UUID, start: date, end: date) -> list[ManualEntry]:
        rows = (
            (
                await self.session.execute(
                    select(ManualEntry).where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.planned_workout_id.is_not(None),
                        ManualEntry.entry_date >= start,
                        ManualEntry.entry_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _planned_count(self, user_id: uuid.UUID, start: date, end: date) -> int:
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout.workout_date).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date >= start,
                        PlannedWorkout.workout_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return len(set(rows))

    async def _weather(self, user_id: uuid.UUID, start: date, end: date) -> list[WeatherDaily]:
        rows = (
            (
                await self.session.execute(
                    select(WeatherDaily).where(
                        WeatherDaily.user_id == user_id,
                        WeatherDaily.calendar_date >= start,
                        WeatherDaily.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _temperature_peaks(
        self, user_id: uuid.UUID, start: date, end: date, timezone_name: str
    ) -> dict[date, float]:
        """Peak indoor temperature per local night, keyed by the wake date."""
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        # Cover the overnight windows feeding each in-range wake date.
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
            # An evening/overnight reading is attributed to the next morning's date.
            wake_date = local.date() + timedelta(days=1) if local.hour >= 18 else local.date()
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


# ---------------------------------------------------------------------------
# Packet serialization
# ---------------------------------------------------------------------------


def _build_packet(
    *,
    player: Profile,
    rollup: ReviewRollup,
    strength: StrengthBriefResult,
    ftp_drift: FtpDriftResult,
    early_warning: EarlyWarningResult,
    guardrails: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "packetType": "deep_review",
        "packetVersion": PACKET_VERSION,
        "period": rollup.period,
        "periodStart": rollup.period_start.isoformat(),
        "periodEnd": rollup.period_end.isoformat(),
        "dayCount": rollup.day_count,
        "generatedAtUtc": _utcnow().isoformat() + "Z",
        "profile": {
            "userId": str(player.id),
            "displayName": player.display_name,
            "timezone": player.timezone,
        },
        "rollup": rollup_packet(rollup),
        "strengthBrief": _strength_packet(strength),
        "insights": {
            "ftpDrift": {
                "status": ftp_drift.status,
                "sampleCount": ftp_drift.sample_count,
                "pctChange": ftp_drift.pct_change,
                "currentFtpWatts": ftp_drift.current_ftp_watts,
                "suggestedFtpWatts": ftp_drift.suggested_ftp_watts,
            },
            "earlyWarning": {
                "status": early_warning.status,
                "fired": early_warning.fired,
                "degradingMetrics": early_warning.degrading_metrics,
            },
        },
        "dataQualityGuardrails": guardrails,
        "prompt": {
            "version": PROMPT_VERSION,
            "system": SYSTEM_PROMPT,
            "outputRules": [
                "four_sections_trends_wins_concerns_recommendations",
                "ground_every_claim_in_packet_numbers",
                "never_reference_left_right_power_balance",
                "exclude_wrist_hr_strength_from_recovery",
                "ignore_broken_sleep_duration_column",
                "flag_low_sample_counts",
            ],
        },
    }


def rollup_packet(rollup: ReviewRollup) -> dict[str, Any]:
    return {
        "sleep": {
            "nights": rollup.sleep.nights,
            "avgScore": rollup.sleep.avg_score,
            "avgAgeAdjustedScore": rollup.sleep.avg_age_adjusted_score,
            "avgDurationMin": rollup.sleep.avg_duration_min,
            "avgDeepMin": rollup.sleep.avg_deep_min,
            "avgRemMin": rollup.sleep.avg_rem_min,
            "trend": rollup.sleep.trend,
        },
        "recovery": {
            "days": rollup.recovery.days,
            "avgHrvMs": rollup.recovery.avg_hrv_ms,
            "avgReadiness": rollup.recovery.avg_readiness,
            "avgRestingHrBpm": rollup.recovery.avg_resting_hr_bpm,
            "avgBodyBatteryCharged": rollup.recovery.avg_body_battery_charged,
            "trend": rollup.recovery.trend,
        },
        "trainingLoad": {
            "activityCount": rollup.training_load.activity_count,
            "totalLoad": rollup.training_load.total_load,
            "totalDurationMin": rollup.training_load.total_duration_min,
            "byType": rollup.training_load.by_type,
        },
        "adherence": {
            "plannedCount": rollup.adherence.planned_count,
            "capturedCount": rollup.adherence.captured_count,
            "statusCounts": rollup.adherence.status_counts,
        },
        "verdicts": {
            "green": rollup.verdicts.green,
            "amber": rollup.verdicts.amber,
            "red": rollup.verdicts.red,
            "total": rollup.verdicts.total,
        },
        "thermal": {
            "nights": rollup.thermal.nights,
            "avgIndoorPeakC": rollup.thermal.avg_indoor_peak_c,
            "avgOvernightLowC": rollup.thermal.avg_overnight_low_c,
            "disruptionNights": rollup.thermal.disruption_nights,
        },
    }


def _strength_packet(strength: StrengthBriefResult) -> dict[str, Any]:
    return {
        "trend": strength.trend,
        "trendReason": strength.trend_reason,
        "sessions4w": strength.window_4w.session_count,
        "sessionsPerWeek4w": strength.window_4w.sessions_per_week,
        "sessions12w": strength.window_12w.session_count,
    }


def _as_float(value: float | int | None) -> float | None:
    return float(value) if value is not None else None


def _minutes(seconds: int | float | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None
