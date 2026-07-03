"""Block-to-block progression proposal engine (Batch 47).

The pure core turns the last completed block's observable outcome into a
recommendation for the next generated block. It is advisory only: the block
generator can use it as a seed for a draft, but locking that draft remains the
only path that mutates the owned plan.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity, Analysis, ManualEntry, PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.daily_loop import ANALYSIS_TYPE_MORNING
from src.services.insights import InsightsService

ANALYSIS_TYPE_POST_WORKOUT = "post_workout"
FULL_BLOCK_WEEKS = 13
MIN_PLANNED_WORKOUTS = 8
MIN_WORK_INTERVALS = 4

DONE_ADHERENCE_STATUSES = {"completed", "modified", "done", "did_something_else"}
MISSED_ADHERENCE_STATUSES = {"skipped", "missed", "not_done"}


@dataclass(frozen=True)
class ExecutionGradeSummary:
    work_intervals: int = 0
    on: int = 0
    over: int = 0
    under: int = 0

    @property
    def hit_rate(self) -> float | None:
        if self.work_intervals == 0:
            return None
        return round((self.on + self.over) / self.work_intervals, 3)

    @property
    def over_rate(self) -> float | None:
        if self.work_intervals == 0:
            return None
        return round(self.over / self.work_intervals, 3)

    @property
    def under_rate(self) -> float | None:
        if self.work_intervals == 0:
            return None
        return round(self.under / self.work_intervals, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workIntervals": self.work_intervals,
            "on": self.on,
            "over": self.over,
            "under": self.under,
            "hitRate": self.hit_rate,
            "overRate": self.over_rate,
            "underRate": self.under_rate,
        }


@dataclass(frozen=True)
class BlockOutcome:
    block_start: date | None
    block_end: date | None
    week_count: int
    planned_workouts: int
    planned_duration_min: int
    achieved_sessions: int
    achieved_duration_min: int
    achieved_load: float
    adherence_captured: int
    adherence_done: int
    adherence_missed: int
    execution: ExecutionGradeSummary
    ftp_drift_status: str
    current_ftp_watts: int
    suggested_ftp_watts: int | None
    verdict_trend: str
    verdict_counts: dict[str, int] = field(default_factory=dict)
    insufficient_reason: str | None = None

    @property
    def complete(self) -> bool:
        return self.insufficient_reason is None

    @property
    def adherence_rate(self) -> float | None:
        denominator = self.adherence_captured or self.planned_workouts
        if denominator == 0:
            return None
        return round(self.adherence_done / denominator, 3)

    @property
    def load_completion_ratio(self) -> float | None:
        if self.planned_duration_min <= 0:
            return None
        return round(self.achieved_duration_min / self.planned_duration_min, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockStart": self.block_start.isoformat() if self.block_start else None,
            "blockEnd": self.block_end.isoformat() if self.block_end else None,
            "weekCount": self.week_count,
            "complete": self.complete,
            "insufficientReason": self.insufficient_reason,
            "plannedWorkouts": self.planned_workouts,
            "plannedDurationMin": self.planned_duration_min,
            "achievedSessions": self.achieved_sessions,
            "achievedDurationMin": self.achieved_duration_min,
            "achievedLoad": round(self.achieved_load, 1),
            "loadCompletionRatio": self.load_completion_ratio,
            "adherenceCaptured": self.adherence_captured,
            "adherenceDone": self.adherence_done,
            "adherenceMissed": self.adherence_missed,
            "adherenceRate": self.adherence_rate,
            "execution": self.execution.to_dict(),
            "ftpDriftStatus": self.ftp_drift_status,
            "currentFtpWatts": self.current_ftp_watts,
            "suggestedFtpWatts": self.suggested_ftp_watts,
            "verdictTrend": self.verdict_trend,
            "verdictCounts": self.verdict_counts,
        }


@dataclass(frozen=True)
class NextBlockProposal:
    status: str
    source: str
    current_ftp_watts: int
    recommended_ftp_watts: int
    ftp_change_watts: int
    focus: str
    structural_nudge: str | None
    summary: str
    evidence: list[str]
    outcome: BlockOutcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "currentFtpWatts": self.current_ftp_watts,
            "recommendedFtpWatts": self.recommended_ftp_watts,
            "ftpChangeWatts": self.ftp_change_watts,
            "focus": self.focus,
            "structuralNudge": self.structural_nudge,
            "summary": self.summary,
            "evidence": self.evidence,
            "outcome": self.outcome.to_dict(),
        }


def propose_next_block(outcome: BlockOutcome) -> NextBlockProposal:
    """Map a completed block outcome to an advisory next-block seed."""
    if not outcome.complete:
        reason = outcome.insufficient_reason or "Not enough completed block history yet."
        return NextBlockProposal(
            status="fallback",
            source="static_default",
            current_ftp_watts=outcome.current_ftp_watts,
            recommended_ftp_watts=outcome.current_ftp_watts,
            ftp_change_watts=0,
            focus="Use the standard 13-week 2121 progression.",
            structural_nudge=None,
            summary=reason,
            evidence=[reason],
            outcome=outcome,
        )

    execution = outcome.execution
    hit_rate = execution.hit_rate or 0.0
    over_rate = execution.over_rate or 0.0
    under_rate = execution.under_rate or 0.0
    adherence_rate = outcome.adherence_rate if outcome.adherence_rate is not None else 1.0

    recommended_ftp = outcome.current_ftp_watts
    evidence: list[str] = []
    focus = "Progress aerobic capacity and quality bike work."
    structural_nudge: str | None = None

    if execution.work_intervals >= MIN_WORK_INTERVALS:
        evidence.append(
            f"Work intervals: {execution.on} on / {execution.over} over / "
            f"{execution.under} under ({hit_rate * 100:.0f}% hit-or-over)."
        )
    else:
        evidence.append("Too few interval execution grades to move FTP from execution alone.")

    if outcome.adherence_rate is not None:
        evidence.append(
            f"Adherence captured {outcome.adherence_done}/{outcome.adherence_captured}."
        )
    if outcome.load_completion_ratio is not None:
        evidence.append(
            f"Achieved duration was {outcome.load_completion_ratio * 100:.0f}% of planned duration."
        )
    evidence.append(f"FTP drift is {outcome.ftp_drift_status}.")
    evidence.append(f"Recovery/verdict trend is {outcome.verdict_trend}.")

    if (
        execution.work_intervals >= MIN_WORK_INTERVALS
        and hit_rate >= 0.75
        and over_rate >= 0.30
        and adherence_rate >= 0.75
        and outcome.ftp_drift_status == "rising"
    ):
        recommended_ftp = outcome.suggested_ftp_watts or round(outcome.current_ftp_watts * 1.03)
        focus = "Carry the build forward with a slightly higher FTP seed."
        summary = "Last block looks ready for a measured FTP bump."
    elif (
        execution.work_intervals >= MIN_WORK_INTERVALS
        and under_rate >= 0.35
        and outcome.ftp_drift_status == "falling"
    ):
        recommended_ftp = outcome.suggested_ftp_watts or round(outcome.current_ftp_watts * 0.97)
        focus = "Repeat the key build emphasis before progressing intensity."
        summary = "Last block points to holding back the next FTP seed."
    elif under_rate >= 0.45 or adherence_rate < 0.60:
        focus = "Repeat the key build emphasis and protect completion before adding load."
        summary = "Last block was not absorbed cleanly enough to progress FTP."
    else:
        summary = "Last block supports holding FTP and progressing the standard template."

    if outcome.verdict_trend == "degraded":
        structural_nudge = "Bias the next block toward recovery spacing if fatigue appears early."
    elif outcome.verdict_counts.get("red", 0) >= 2:
        structural_nudge = "Keep hard-session spacing conservative after repeated Red mornings."

    recommended_ftp = max(1, int(recommended_ftp))
    return NextBlockProposal(
        status="ready",
        source="last_completed_block",
        current_ftp_watts=outcome.current_ftp_watts,
        recommended_ftp_watts=recommended_ftp,
        ftp_change_watts=recommended_ftp - outcome.current_ftp_watts,
        focus=focus,
        structural_nudge=structural_nudge,
        summary=summary,
        evidence=evidence,
        outcome=outcome,
    )


def execution_summary_from_packets(packets: Sequence[Mapping[str, Any]]) -> ExecutionGradeSummary:
    on = over = under = total = 0
    for packet in packets:
        intervals = packet.get("intervals")
        if not isinstance(intervals, list):
            continue
        for interval in intervals:
            if not isinstance(interval, Mapping) or interval.get("role") != "work":
                continue
            grade = interval.get("adherence")
            if grade not in {"on", "over", "under"}:
                continue
            total += 1
            if grade == "on":
                on += 1
            elif grade == "over":
                over += 1
            else:
                under += 1
    return ExecutionGradeSummary(work_intervals=total, on=on, over=over, under=under)


def verdict_trend(verdicts: Sequence[str | None]) -> tuple[str, dict[str, int]]:
    normalized = [(v or "").strip().lower() for v in verdicts if v]
    counts = {"green": 0, "amber": 0, "red": 0}
    for verdict in normalized:
        if verdict in counts:
            counts[verdict] += 1
    if len(normalized) < 4:
        return "insufficient_data", counts
    mid = len(normalized) // 2
    first_score = _verdict_load(normalized[:mid])
    second_score = _verdict_load(normalized[mid:])
    if second_score - first_score >= 0.25:
        return "degraded", counts
    if first_score - second_score >= 0.25:
        return "improved", counts
    return "stable", counts


def _verdict_load(values: Sequence[str]) -> float:
    weights = {"green": 0.0, "amber": 1.0, "red": 2.0}
    present = [weights[v] for v in values if v in weights]
    if not present:
        return 0.0
    return sum(present) / len(present)


class BlockProgressionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def proposal_for_next_block(
        self,
        user: Profile,
        *,
        start_date: date,
        current_ftp_watts: int,
    ) -> NextBlockProposal:
        blocks = await self._completed_weeks(user.id, before=start_date)
        block_start = min((row.start_date for row in blocks), default=None)
        block_end = max((row.end_date for row in blocks), default=None)
        if len(blocks) < FULL_BLOCK_WEEKS or block_start is None or block_end is None:
            outcome = BlockOutcome(
                block_start=block_start,
                block_end=block_end,
                week_count=len(blocks),
                planned_workouts=0,
                planned_duration_min=0,
                achieved_sessions=0,
                achieved_duration_min=0,
                achieved_load=0.0,
                adherence_captured=0,
                adherence_done=0,
                adherence_missed=0,
                execution=ExecutionGradeSummary(),
                ftp_drift_status="insufficient_data",
                current_ftp_watts=current_ftp_watts,
                suggested_ftp_watts=None,
                verdict_trend="insufficient_data",
                insufficient_reason=(
                    f"Only {len(blocks)} completed plan weeks found; "
                    f"need {FULL_BLOCK_WEEKS} before seeding from block history."
                ),
            )
            return propose_next_block(outcome)

        workouts = await self._planned_workouts(user.id, block_start, block_end)
        adherence = await self._adherence(user.id, block_start, block_end)
        activities = await self._activities(user.id, block_start, block_end)
        packet_rows = await self._post_workout_packets(user.id, block_start, block_end)
        morning_verdicts = await self._morning_verdicts(user.id, block_start, block_end)
        trend, counts = verdict_trend(morning_verdicts)
        ftp_drift = await InsightsService(self.session).ftp_drift(user, as_of=block_end)

        planned_duration = sum(int(row.planned_duration_min or 0) for row in workouts)
        achieved_duration = sum(int((row.duration_sec or 0) / 60) for row in activities)
        achieved_load = sum(float(row.training_load or 0.0) for row in activities)
        done = missed = 0
        for entry in adherence:
            status = (entry.adherence_status or "").strip().lower()
            if status in DONE_ADHERENCE_STATUSES:
                done += 1
            elif status in MISSED_ADHERENCE_STATUSES:
                missed += 1

        reason = None
        if len(workouts) < MIN_PLANNED_WORKOUTS:
            reason = (
                f"Only {len(workouts)} planned workouts found in the completed block; "
                f"need {MIN_PLANNED_WORKOUTS} to seed the next block."
            )

        outcome = BlockOutcome(
            block_start=block_start,
            block_end=block_end,
            week_count=len(blocks),
            planned_workouts=len(workouts),
            planned_duration_min=planned_duration,
            achieved_sessions=len(activities),
            achieved_duration_min=achieved_duration,
            achieved_load=achieved_load,
            adherence_captured=len(adherence),
            adherence_done=done,
            adherence_missed=missed,
            execution=execution_summary_from_packets(packet_rows),
            ftp_drift_status=ftp_drift.status,
            current_ftp_watts=current_ftp_watts,
            suggested_ftp_watts=ftp_drift.suggested_ftp_watts,
            verdict_trend=trend,
            verdict_counts=counts,
            insufficient_reason=reason,
        )
        return propose_next_block(outcome)

    async def _completed_weeks(self, user_id: uuid.UUID, *, before: date) -> list[PlanBlock]:
        rows = (
            (
                await self.session.execute(
                    select(PlanBlock)
                    .where(PlanBlock.user_id == user_id, PlanBlock.end_date < before)
                    .order_by(PlanBlock.end_date.desc())
                    .limit(FULL_BLOCK_WEEKS)
                )
            )
            .scalars()
            .all()
        )
        return sorted(rows, key=lambda row: row.start_date)

    async def _planned_workouts(
        self, user_id: uuid.UUID, start: date, end: date
    ) -> list[PlannedWorkout]:
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout).where(
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
        return list(rows)

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

    async def _post_workout_packets(
        self, user_id: uuid.UUID, start: date, end: date
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_POST_WORKOUT,
                        Analysis.subject_date >= start,
                        Analysis.subject_date <= end,
                    )
                    .order_by(Analysis.generated_at_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return [dict(row.context_packet or {}) for row in rows]

    async def _morning_verdicts(
        self, user_id: uuid.UUID, start: date, end: date
    ) -> list[str | None]:
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
                    .order_by(Analysis.subject_date.asc(), Analysis.generated_at_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        latest_by_date: dict[date, str | None] = {}
        for row in rows:
            latest_by_date[row.subject_date] = row.verdict
        return [latest_by_date[day] for day in sorted(latest_by_date)]
