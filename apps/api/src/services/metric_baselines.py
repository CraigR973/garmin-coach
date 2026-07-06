"""Compute & persist metric baselines from stored DB history.

Companion to ``services/sleep_history.py``: that module seeds baselines from the
84-night xlsx; this one derives the *same* statistical baselines (identical
stats + the #45 SpO2/HRV reliability cutoff) from the gapless Garmin history
already loaded into ``daily_metrics`` + ``sleep`` (PR #27), so a prod holding
real history gets history-derived baselines without the spreadsheet.

Rows are written under a distinct ``db_history`` source so provenance stays
honest (#44) and they never collide with the xlsx ``(user_id, metric_key,
source)`` unique key. The morning "Metrics vs Baselines" read
(``services/morning_analysis.py``) emits one row per persisted baseline,
falling back to the static KB profile bands when the table is empty; this
backfill simply fills the table so the richer history-derived read is used —
the per-day metric→column mapping here mirrors that read's ``current_values``
so "current vs baseline" stays apples-to-apples.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import DailyMetric, KnowledgeBase, MetricBaseline, Sleep
from src.models.profile import Profile
from src.services.sleep_history import BaselineSample, compute_metric_baselines
from src.services.sleep_scoring import age_adjusted_sleep_score_for_row

DB_HISTORY_SOURCE = "db_history"
DEFAULT_WINDOW_DAYS = 84


@dataclass(frozen=True)
class MetricBaselineBackfillResult:
    source: str
    window_start: date | None
    window_end: date | None
    samples_considered: int
    dry_run: bool
    baselines_created: int = 0
    baselines_updated: int = 0
    baselines_unchanged: int = 0
    metric_keys: list[str] = field(default_factory=list)

    def render(self) -> str:
        window = (
            f"{self.window_start.isoformat()} → {self.window_end.isoformat()}"
            if self.window_start and self.window_end
            else "(no history)"
        )
        return "\n".join(
            [
                f"Source: {self.source}",
                f"Window: {window}  ({self.samples_considered} day(s) with data)",
                f"Dry run: {self.dry_run}",
                "Baselines created/updated/unchanged: "
                f"{self.baselines_created}/{self.baselines_updated}/{self.baselines_unchanged}",
                f"Metrics: {', '.join(self.metric_keys) if self.metric_keys else '(none)'}",
            ]
        )


def sample_values(
    sleep: Sleep | None,
    metric: DailyMetric | None,
    *,
    age: int | None = None,
    sex: str | None = None,
) -> Mapping[str, float | int | None]:
    """One day's baseline inputs keyed by ``metric_key``.

    Mirrors ``morning_analysis._metrics_vs_baselines`` ``current_values`` exactly
    so the persisted baseline and the live "current" value are drawn from the
    same columns (RHR coalesces the daily-metric reading over the sleep reading).
    """
    resting_heart_rate = None
    if metric is not None and metric.resting_heart_rate_bpm is not None:
        resting_heart_rate = metric.resting_heart_rate_bpm
    elif sleep is not None:
        resting_heart_rate = sleep.resting_heart_rate_bpm
    age_adjusted_score = age_adjusted_sleep_score_for_row(sleep, age=age, sex=sex)
    return {
        "sleep_score": sleep.score if sleep else None,
        "age_adjusted_sleep_score": age_adjusted_score,
        "readiness_score": metric.readiness_score if metric else None,
        "resting_heart_rate_bpm": resting_heart_rate,
        "body_battery_charge": metric.body_battery_charged if metric else None,
        "average_spo2_pct": sleep.average_spo2_pct if sleep else None,
        "average_respiration": sleep.average_respiration if sleep else None,
        "hrv_7_day_avg_ms": metric.hrv_weekly_avg_ms if metric else None,
    }


class MetricBaselineBackfillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rebuild(
        self,
        profile: Profile,
        *,
        window_days: int | None = DEFAULT_WINDOW_DAYS,
        as_of: date | None = None,
        dry_run: bool = False,
    ) -> MetricBaselineBackfillResult:
        """Recompute the ``db_history`` baselines from stored sleep + daily metrics.

        ``window_days`` is a trailing night count ending at ``as_of`` (or the
        latest available history date); ``None``/``<= 0`` uses all history.
        Idempotent: rows are upserted, so a re-run with the same data is a no-op.
        """
        samples = await self._load_samples(profile.id, window_days=window_days, as_of=as_of)
        baseline_fields = compute_metric_baselines(samples, source=DB_HISTORY_SOURCE)
        window_start = samples[0].calendar_date if samples else None
        window_end = samples[-1].calendar_date if samples else None

        existing = await self._load_existing(profile.id)
        created = 0
        updated = 0
        unchanged = 0
        for fields in baseline_fields:
            metric_key = str(fields["metric_key"])
            baseline = existing.get(metric_key)
            if baseline is None:
                created += 1
                if not dry_run:
                    baseline = MetricBaseline(
                        user_id=profile.id,
                        metric_key=metric_key,
                        source=DB_HISTORY_SOURCE,
                    )
                    self.session.add(baseline)
                    existing[metric_key] = baseline
                    _assign(baseline, fields)
            elif _assign(baseline, fields, apply=not dry_run):
                updated += 1
            else:
                unchanged += 1

        if not dry_run:
            await self.session.commit()

        return MetricBaselineBackfillResult(
            source=DB_HISTORY_SOURCE,
            window_start=window_start,
            window_end=window_end,
            samples_considered=len(samples),
            dry_run=dry_run,
            baselines_created=created,
            baselines_updated=updated,
            baselines_unchanged=unchanged,
            metric_keys=[str(fields["metric_key"]) for fields in baseline_fields],
        )

    async def _load_samples(
        self,
        user_id: uuid.UUID,
        *,
        window_days: int | None,
        as_of: date | None,
    ) -> list[BaselineSample]:
        sleep_rows = (
            (await self.session.execute(select(Sleep).where(Sleep.user_id == user_id)))
            .scalars()
            .all()
        )
        metric_rows = (
            (await self.session.execute(select(DailyMetric).where(DailyMetric.user_id == user_id)))
            .scalars()
            .all()
        )
        sleep_by_date = {row.calendar_date: row for row in sleep_rows}
        metric_by_date = {row.calendar_date: row for row in metric_rows}
        all_dates = sorted(set(sleep_by_date) | set(metric_by_date))
        if not all_dates:
            return []
        age, sex = await self._profile_age_sex(user_id)

        window_end = as_of or all_dates[-1]
        window_start: date | None = None
        if window_days is not None and window_days > 0:
            window_start = window_end - timedelta(days=window_days - 1)

        return [
            BaselineSample(
                calendar_date=day,
                values=sample_values(
                    sleep_by_date.get(day),
                    metric_by_date.get(day),
                    age=age,
                    sex=sex,
                ),
            )
            for day in all_dates
            if day <= window_end and (window_start is None or day >= window_start)
        ]

    async def _profile_age_sex(self, user_id: uuid.UUID) -> tuple[int | None, str | None]:
        row = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == "profile",
                KnowledgeBase.is_active.is_(True),
            )
        )
        content = row.content if row and isinstance(row.content, dict) else {}
        raw_age = content.get("age")
        raw_sex = content.get("sex")
        age = int(raw_age) if isinstance(raw_age, int | float) else None
        sex = raw_sex if isinstance(raw_sex, str) else None
        return age, sex

    async def _load_existing(self, user_id: uuid.UUID) -> dict[str, MetricBaseline]:
        result = await self.session.execute(
            select(MetricBaseline).where(
                MetricBaseline.user_id == user_id,
                MetricBaseline.source == DB_HISTORY_SOURCE,
            )
        )
        return {row.metric_key: row for row in result.scalars().all()}


def _assign(instance: Any, fields: Mapping[str, Any], *, apply: bool = True) -> bool:
    changed = False
    for key, value in fields.items():
        if getattr(instance, key) != value:
            changed = True
            if apply:
                setattr(instance, key, value)
    return changed
