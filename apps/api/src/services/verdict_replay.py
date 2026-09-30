"""Replay every stored morning through the ladder and the graded verdict (Batch 295).

Batch 269 answered "what would this change have done?" with a one-off replay. This
keeps that tool in the repo, so every future verdict change can be judged the same
way before it ships, and so Batch 296 can compare the two every morning.

**Each morning is replayed from the inputs it actually saw** (the review, SE-2). The
stored morning packet holds that morning's own readings: Garmin's daily metrics, the
sleep row, his check-in, the plan as it stood, yesterday's load and the rest-day
context. Everything that needs history — his HRV and resting-heart-rate normal, his
usual sleep and feel, the personal baselines the ladder reads — is rebuilt from rows
dated *before* that morning. Nothing reads today's baselines.

For each morning the report carries three colours:

* **shown** — the colour the stored read gave Mark, chosen by the same rule the rest
  of the app counts (``delivered_verdict``);
* **ladder** — the current ladder (``morning_verdict``) on the same inputs, so a
  difference is the grading and not a change made since;
* **graded** — the graded verdict (``verdict_grading``).

Read-only: it loads projected columns and packet sections only, and writes nothing.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import Any

from sqlalchemy import literal_column, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    Analysis,
    DailyMetric,
    Dispute,
    ManualEntry,
    MetricBaseline,
    PlanBlock,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile
from src.services.daily_metric_phase import prefer_morning
from src.services.delivered_verdict import delivered_rows
from src.services.morning_verdict import morning_verdict
from src.services.sleep_history import (
    BASELINE_SPECS,
    BaselineSample,
    compute_metric_baselines,
)
from src.services.verdict_grading import (
    ACTION_AS_PLANNED,
    ACTION_HOLD_TARGETS,
    ACTION_OFF_THE_BIKE,
    ACTION_RECOVERY,
    ACTION_SHORTENED_Z2,
    DOMAINS,
    THRESHOLDS,
    GradedVerdict,
    PlannedSession,
    block_flags,
    build_grading_inputs,
    grade,
    readiness_lower_quartile,
)

#: The ladder's cut on an Amber morning, for the old-action column.
ACTION_AMBER_CUT = "amber_cut"

#: History the replay reads before the first morning it replays.
HISTORY_DAYS = 84
#: The ladder's own baselines, rebuilt as of each morning.
LADDER_BASELINE_KEYS = (
    "resting_heart_rate_bpm",
    "readiness_score",
    "average_spo2_pct",
    "average_respiration",
)
HARD_WORKOUT_TYPES = frozenset({"bike_vo2", "bike_sweet_spot", "bike_threshold"})


@dataclass(frozen=True, slots=True)
class MorningRead:
    """One stored morning read, projected to what the replay needs."""

    id: uuid.UUID
    subject_date: date
    generated_at_utc: datetime
    created_at: datetime
    verdict: str | None
    daily_metrics: Any
    sleep: Any
    manual_entries: Any
    planned_workouts: Any
    yesterday_load: Any
    rest_day: Any
    readiness_trend: Any
    age_adjusted: Any
    #: Batch 296: a graded morning's own engine, acute rail, held flag and references.
    engine: Any = None
    acute: Any = None
    held: Any = None
    references: Any = None


@dataclass(frozen=True, slots=True)
class ReplayedMorning:
    subject_date: date
    shown: str | None
    ladder: str
    ladder_reasons: tuple[str, ...]
    ladder_bike_rest: bool
    ladder_training_rest: bool
    ladder_hold: bool
    graded: GradedVerdict
    sessions: tuple[PlannedSession, ...]
    old_actions: tuple[str, ...]
    rest_day: bool
    recovery_class_block: bool
    shown_held: bool = False
    #: Batch 296: the engine that decided the shown colour ("graded" after the switch).
    shown_engine: str | None = None
    #: The ladder's full packet for the morning, as production would have built it.
    ladder_packet: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def reproduces_production(self) -> bool | None:
        """For a graded morning, whether the replay gives back exactly what Mark saw."""
        if self.shown_engine != "graded":
            return None
        return self.shown_label == self.graded_label

    @property
    def shown_label(self) -> str | None:
        return "Green (held)" if self.shown_held and self.shown == "Green" else self.shown

    @property
    def changed(self) -> bool:
        return self.ladder != self.graded.status or self.ladder_hold != self.graded.held

    @property
    def graded_label(self) -> str:
        return self.graded.label

    @property
    def ladder_label(self) -> str:
        return "Green (held)" if self.ladder_hold and self.ladder == "Green" else self.ladder


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    subject_date: date
    title: str | None
    on_target: int | None
    work_intervals: int | None
    under: int | None
    faded: int | None


@dataclass(frozen=True, slots=True)
class NextMorning:
    subject_date: date
    flagged: bool
    hrv_delta_ms: float | None
    rhr_delta_bpm: float | None


@dataclass(slots=True)
class ReplayReport:
    start: date
    end: date
    mornings: list[ReplayedMorning] = field(default_factory=list)
    executions_on_eased_mornings: list[ExecutionRecord] = field(default_factory=list)
    executions_elsewhere: list[ExecutionRecord] = field(default_factory=list)
    next_mornings: list[NextMorning] = field(default_factory=list)
    dissents: list[date] = field(default_factory=list)


class VerdictReplayService:
    """Replays stored mornings; reads only."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replay(
        self,
        player: Profile,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> ReplayReport:
        reads = await self._morning_reads(player.id, start=start, end=end)
        delivered = delivered_rows(reads, timezone_name=player.timezone)
        days = sorted(delivered)
        report = ReplayReport(
            start=days[0] if days else (start or date.today()),
            end=days[-1] if days else (end or date.today()),
        )
        if not days:
            return report
        history_start = days[0] - timedelta(days=HISTORY_DAYS + 7)
        metrics, baseline_metrics = await self._daily_metrics(player.id, history_start, days[-1])
        sleeps = await self._sleeps(player.id, history_start, days[-1])
        feels = await self._morning_feels(player.id, history_start, days[-1])
        blocks = await self._plan_blocks(player.id, history_start, days[-1])
        for day in days:
            report.mornings.append(
                replay_morning(
                    delivered[day],
                    metrics=metrics,
                    baseline_metrics=baseline_metrics,
                    sleeps=sleeps,
                    feels=feels,
                    blocks=blocks,
                )
            )
        await self._outcome_proxies(player, report, metrics)
        return report

    # -- loading -------------------------------------------------------------------------

    async def _morning_reads(
        self, user_id: uuid.UUID, *, start: date | None, end: date | None
    ) -> list[MorningRead]:
        document = (
            select(
                Analysis.context_packet.op("||", return_type=JSONB)(
                    literal_column("'{}'::jsonb", type_=JSONB)
                ).label("document")
            )
            .correlate(Analysis)
            .offset(0)
            .lateral("morning_document")
        )
        packet = document.c.document
        query = (
            select(
                Analysis.id,
                Analysis.subject_date,
                Analysis.generated_at_utc,
                Analysis.created_at,
                Analysis.verdict,
                packet[("dailyMetrics",)].label("daily_metrics"),
                packet[("sleep",)].label("sleep"),
                packet[("manualEntries",)].label("manual_entries"),
                packet[("plannedWorkouts",)].label("planned_workouts"),
                packet[("yesterdayLoad",)].label("yesterday_load"),
                packet[("restDay",)].label("rest_day"),
                packet[("verdict", "readinessBaselineTrend")].label("readiness_trend"),
                packet[("verdict", "ageAdjustedSleepScore")].label("age_adjusted"),
                packet[("verdict", "engine")].label("engine"),
                packet[("verdict", "acutePhysiology")].label("acute"),
                packet[("verdict", "held")].label("held"),
                packet[("verdict", "graded", "references")].label("references"),
            )
            .select_from(Analysis)
            .join(document, true())
            .where(Analysis.user_id == user_id, Analysis.analysis_type == "morning")
        )
        if start is not None:
            query = query.where(Analysis.subject_date >= start)
        if end is not None:
            query = query.where(Analysis.subject_date <= end)
        rows = (await self.session.execute(query)).all()
        return [
            MorningRead(
                id=row.id,
                subject_date=row.subject_date,
                generated_at_utc=row.generated_at_utc,
                created_at=row.created_at,
                verdict=row.verdict,
                daily_metrics=row.daily_metrics,
                sleep=row.sleep,
                manual_entries=row.manual_entries,
                planned_workouts=row.planned_workouts,
                yesterday_load=row.yesterday_load,
                rest_day=row.rest_day,
                readiness_trend=row.readiness_trend,
                age_adjusted=row.age_adjusted,
                engine=row.engine,
                acute=row.acute,
                held=row.held,
                references=row.references,
            )
            for row in rows
        ]

    async def _daily_metrics(
        self, user_id: uuid.UUID, start: date, end: date
    ) -> tuple[dict[date, DailyMetric], dict[date, DailyMetric]]:
        """``(wake rows, wake-else-settled rows)`` by date."""
        rows = (
            (
                await self.session.execute(
                    select(DailyMetric)
                    .options(
                        load_only(
                            DailyMetric.calendar_date,
                            DailyMetric.phase,
                            DailyMetric.hrv_last_night_avg_ms,
                            DailyMetric.hrv_weekly_avg_ms,
                            DailyMetric.resting_heart_rate_bpm,
                            DailyMetric.hrv_baseline_low_ms,
                            DailyMetric.hrv_baseline_high_ms,
                            DailyMetric.readiness_score,
                            raiseload=True,
                        )
                    )
                    .where(
                        DailyMetric.user_id == user_id,
                        DailyMetric.calendar_date >= start,
                        DailyMetric.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        wake = {row.calendar_date: row for row in rows if row.phase == DAILY_METRIC_PHASE_MORNING}
        return wake, {row.calendar_date: row for row in prefer_morning(rows)}

    async def _sleeps(self, user_id: uuid.UUID, start: date, end: date) -> dict[date, Sleep]:
        rows = (
            (
                await self.session.execute(
                    select(Sleep)
                    .options(
                        load_only(
                            Sleep.calendar_date,
                            Sleep.duration_sec,
                            Sleep.resting_heart_rate_bpm,
                            Sleep.average_spo2_pct,
                            Sleep.lowest_spo2_pct,
                            Sleep.average_respiration,
                            raiseload=True,
                        )
                    )
                    .where(
                        Sleep.user_id == user_id,
                        Sleep.calendar_date >= start,
                        Sleep.calendar_date <= end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.calendar_date: row for row in rows}

    async def _morning_feels(self, user_id: uuid.UUID, start: date, end: date) -> dict[date, int]:
        rows = (
            await self.session.execute(
                select(
                    ManualEntry.entry_date, ManualEntry.entry_at_utc, ManualEntry.subjective_score
                )
                .where(
                    ManualEntry.user_id == user_id,
                    ManualEntry.entry_date >= start,
                    ManualEntry.entry_date <= end,
                    ManualEntry.planned_workout_id.is_(None),
                    ManualEntry.activity_id.is_(None),
                    ManualEntry.subjective_score.is_not(None),
                )
                .order_by(ManualEntry.entry_date, ManualEntry.entry_at_utc)
            )
        ).all()
        # The newest scored morning check-in of each day, as the verdict reads it.
        return {row.entry_date: int(row.subjective_score) for row in rows}

    async def _plan_blocks(self, user_id: uuid.UUID, start: date, end: date) -> list[PlanBlock]:
        return list(
            (
                await self.session.execute(
                    select(PlanBlock).where(
                        PlanBlock.user_id == user_id,
                        PlanBlock.start_date <= end,
                        PlanBlock.end_date >= start,
                    )
                )
            )
            .scalars()
            .all()
        )

    # -- the outcome proxies (295.6): directional, one person, about 100 mornings --------

    async def _outcome_proxies(
        self,
        player: Profile,
        report: ReplayReport,
        metrics: Mapping[date, DailyMetric],
    ) -> None:
        rows = (
            await self.session.execute(
                select(
                    Analysis.subject_date,
                    Analysis.generated_at_utc,
                    Analysis.planned_workout_id,
                    PlannedWorkout.title,
                    PlannedWorkout.workout_type,
                    Analysis.context_packet[("execution", "onTargetCount")]
                    .as_string()
                    .label("on_target"),
                    Analysis.context_packet[("execution", "workIntervalCount")]
                    .as_string()
                    .label("work_intervals"),
                    Analysis.context_packet[("execution", "underCount")].as_string().label("under"),
                    Analysis.context_packet[("execution", "fadedCount")].as_string().label("faded"),
                )
                .join(PlannedWorkout, PlannedWorkout.id == Analysis.planned_workout_id)
                .where(
                    Analysis.user_id == player.id,
                    Analysis.analysis_type == "post_workout",
                    Analysis.subject_date >= report.start,
                    Analysis.subject_date <= report.end,
                )
                .order_by(Analysis.generated_at_utc)
            )
        ).all()
        latest: dict[tuple[date, uuid.UUID], Any] = {}
        for row in rows:
            latest[(row.subject_date, row.planned_workout_id)] = row
        eased_ids = {
            (morning.subject_date, action.session_id)
            for morning in report.mornings
            for action in morning.graded.actions
            if action.is_hard and action.action not in {ACTION_AS_PLANNED, ACTION_HOLD_TARGETS}
        }
        flagged_days = {
            morning.subject_date
            for morning in report.mornings
            if morning.graded.status != "Green" or morning.graded.held
        }
        for (day, workout_id), row in sorted(latest.items(), key=lambda item: item[0][0]):
            if row.workout_type not in HARD_WORKOUT_TYPES:
                continue
            record = ExecutionRecord(
                subject_date=day,
                title=row.title,
                on_target=_int(row.on_target),
                work_intervals=_int(row.work_intervals),
                under=_int(row.under),
                faded=_int(row.faded),
            )
            if (day, str(workout_id)) in eased_ids:
                report.executions_on_eased_mornings.append(record)
            else:
                report.executions_elsewhere.append(record)
            report.next_mornings.append(_next_morning(day, metrics, flagged=day in flagged_days))
        dissents = (
            await self.session.execute(
                select(Dispute.subject_date).where(
                    Dispute.user_id == player.id,
                    Dispute.kind == "dissent",
                    Dispute.subject_date >= report.start,
                    Dispute.subject_date <= report.end,
                )
            )
        ).all()
        report.dissents = sorted(row.subject_date for row in dissents)


# -- one morning -------------------------------------------------------------------------


def replay_morning(
    read: MorningRead,
    *,
    metrics: Mapping[date, DailyMetric],
    sleeps: Mapping[date, Sleep],
    feels: Mapping[date, int],
    blocks: Sequence[PlanBlock],
    baseline_metrics: Mapping[date, DailyMetric] | None = None,
) -> ReplayedMorning:
    """One morning, from its stored packet and the rows dated before it.

    ``metrics`` are wake (morning-phase) rows only, as the live acute rail reads
    them; ``baseline_metrics`` prefer the wake row and fall back to the settled one,
    as the nightly baseline job does.
    """
    day = read.subject_date
    daily_metric = _daily_metric_from_packet(day, read.daily_metrics)
    sleep = _sleep_from_packet(day, read.sleep)
    manual_entries = _manual_entries_from_packet(day, read.manual_entries)
    planned = _planned_workouts_from_packet(day, read.planned_workouts)
    rest_day = read.rest_day if isinstance(read.rest_day, Mapping) else {}
    window_start = day - timedelta(days=HISTORY_DAYS)
    recent_metrics = [row for d, row in metrics.items() if window_start <= d < day]
    recent_sleeps = [row for d, row in sleeps.items() if window_start <= d < day]
    baselines = _as_of_baselines(day, baseline_metrics or metrics, sleeps)
    dm = read.daily_metrics if isinstance(read.daily_metrics, Mapping) else {}
    age_adjusted = _int(read.age_adjusted)
    # Batch 297: a symptom his note supplied, as the stored rail recorded it.
    stored_acute = read.acute if isinstance(read.acute, Mapping) else {}
    stored_symptoms = stored_acute.get("symptoms")
    notes_symptom = (
        stored_symptoms
        if isinstance(stored_symptoms, Mapping) and stored_symptoms.get("source") == "notes"
        else {}
    )
    ladder = morning_verdict(
        notes_symptom_answer=(
            str(notes_symptom["answer"]) if notes_symptom.get("answer") else None
        ),
        notes_symptom_words=(str(notes_symptom["words"]) if notes_symptom.get("words") else None),
        daily_metric=daily_metric,
        sleep=sleep,
        age_adjusted_sleep_score=age_adjusted,
        manual_entries=manual_entries,
        planned_workouts=planned,
        baselines=baselines,
        yesterday_load=read.yesterday_load if isinstance(read.yesterday_load, Mapping) else None,
        training_load={
            "acuteChronicLoadRatio": _float(dm.get("acuteChronicLoadRatio")),
            "recoveryTimeMin": _int(dm.get("recoveryTimeMin")),
        },
        readiness_baseline_trend=(
            read.readiness_trend if isinstance(read.readiness_trend, Mapping) else None
        ),
        rest_day=rest_day,
        recent_daily_metrics=recent_metrics,
        recent_sleeps=recent_sleeps,
        enforce_data_sufficiency=True,
    )
    # Batch 296: a morning the graded verdict decided is replayed from production's own
    # acute rail and readiness reference, so the replay reproduces it exactly. Before
    # the switch the stored rail was the older code's, so today's is recomputed.
    graded_morning = read.engine == "graded"
    acute = (
        read.acute
        if graded_morning and isinstance(read.acute, Mapping)
        else ladder["acutePhysiology"]
    )
    references = read.references if isinstance(read.references, Mapping) else {}
    is_rest_day = bool(rest_day.get("isRestDay"))
    _, recovery_class = block_flags(day, blocks)
    readiness_baseline = baselines.get("readiness_score")
    inputs = build_grading_inputs(
        subject_date=day,
        acute=acute,
        last_night_hrv_ms=(
            float(daily_metric.hrv_last_night_avg_ms)
            if daily_metric is not None and daily_metric.hrv_last_night_avg_ms is not None
            else None
        ),
        hrv_history={
            d: float(row.hrv_last_night_avg_ms)
            for d, row in metrics.items()
            if row.hrv_last_night_avg_ms is not None
        },
        sleep_score_raw=sleep.score if sleep is not None else None,
        sleep_score_age_adjusted=age_adjusted,
        sleep_minutes=(
            sleep.duration_sec / 60 if sleep is not None and sleep.duration_sec else None
        ),
        sleep_minutes_history={
            d: row.duration_sec / 60 for d, row in sleeps.items() if row.duration_sec
        },
        acwr=_float(dm.get("acuteChronicLoadRatio")),
        recovery_time_min=_float(dm.get("recoveryTimeMin")),
        yesterday_load=(
            str(read.yesterday_load.get("status"))
            if isinstance(read.yesterday_load, Mapping)
            and read.yesterday_load.get("status") is not None
            else None
        ),
        feel=_int(ladder.get("subjectiveScore")),
        feel_history=feels,
        readiness_level=daily_metric.readiness_level if daily_metric else None,
        readiness_score=(
            float(daily_metric.readiness_score)
            if daily_metric is not None and daily_metric.readiness_score is not None
            else None
        ),
        readiness_lower_quartile=(
            _float(references.get("readinessLowerQuartile"))
            if graded_morning
            else readiness_lower_quartile(readiness_baseline)
        ),
        planned_workouts=planned,
        rest_day=is_rest_day,
        blocks=blocks,
        notes_feel_notch=(int(references.get("notesFeelNotch") or 0) if graded_morning else 0),
        notes_feel_words=(
            str(references["notesFeelWords"])
            if graded_morning and references.get("notesFeelWords")
            else None
        ),
    )
    if graded_morning:
        # The plan blocks can be edited after the morning; the flags it was graded
        # with are stored beside the colour.
        stored_week = references.get("inRecoveryWeek")
        stored_block = references.get("recoveryClassBlock")
        inputs = replace(
            inputs,
            in_recovery_week=(
                stored_week if isinstance(stored_week, bool) else inputs.in_recovery_week
            ),
            recovery_class_block=(
                stored_block if isinstance(stored_block, bool) else inputs.recovery_class_block
            ),
        )
        recovery_class = inputs.recovery_class_block
    sessions = inputs.sessions
    graded = grade(inputs)
    hold = (
        isinstance(ladder.get("hrvGradedResponse"), Mapping)
        and ladder["hrvGradedResponse"].get("tier") == "hold"
    )
    return ReplayedMorning(
        subject_date=day,
        shown=_normal(read.verdict),
        shown_held=read.held is True,
        shown_engine=read.engine if isinstance(read.engine, str) else None,
        ladder=str(ladder["status"]),
        ladder_reasons=tuple(str(reason) for reason in ladder.get("reasons", [])),
        ladder_bike_rest=acute.get("requiresBikeRest") is True,
        ladder_training_rest=acute.get("requiresTrainingRest") is True,
        ladder_hold=bool(hold and ladder["status"] == "Green"),
        graded=graded,
        sessions=sessions,
        old_actions=tuple(
            ()
            if is_rest_day
            else (
                _ladder_action(
                    str(ladder["status"]),
                    session,
                    bike_rest=acute.get("requiresBikeRest") is True,
                    training_rest=acute.get("requiresTrainingRest") is True,
                    hold=bool(hold),
                )
                for session in sessions
            )
        ),
        rest_day=is_rest_day,
        recovery_class_block=recovery_class,
        ladder_packet=ladder,
    )


# -- reconstruction ----------------------------------------------------------------------


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normal(value: str | None) -> str | None:
    if not value:
        return None
    return {"green": "Green", "amber": "Amber", "red": "Red"}.get(value.strip().lower())


def _daily_metric_from_packet(day: date, packet: Any) -> DailyMetric | None:
    if not isinstance(packet, Mapping):
        return None
    return DailyMetric(
        calendar_date=day,
        phase=DAILY_METRIC_PHASE_MORNING,
        readiness_score=_int(packet.get("readinessScore")),
        readiness_level=packet.get("readinessLevel"),
        recovery_time_min=_int(packet.get("recoveryTimeMin")),
        hrv_last_night_avg_ms=_int(packet.get("hrvLastNightAvgMs")),
        hrv_weekly_avg_ms=_int(packet.get("hrvWeeklyAvgMs")),
        hrv_status=packet.get("hrvStatus"),
        hrv_baseline_low_ms=_int(packet.get("hrvBaselineLowMs")),
        hrv_baseline_high_ms=_int(packet.get("hrvBaselineHighMs")),
        resting_heart_rate_bpm=_int(packet.get("restingHeartRateBpm")),
        raw_payload={},
    )


def _sleep_from_packet(day: date, packet: Any) -> Sleep | None:
    if not isinstance(packet, Mapping):
        return None
    duration = _int(packet.get("timeAsleepMin") or packet.get("durationMin"))
    return Sleep(
        calendar_date=day,
        score=_int(packet.get("score")),
        duration_sec=duration * 60 if duration is not None else None,
        hrv_status=packet.get("hrvStatus"),
        avg_overnight_hrv_ms=_int(packet.get("avgOvernightHrvMs")),
        average_spo2_pct=_float(packet.get("averageSpo2Pct")),
        lowest_spo2_pct=_float(packet.get("lowestSpo2Pct")),
        average_respiration=_float(packet.get("averageRespiration")),
        resting_heart_rate_bpm=_int(packet.get("restingHeartRateBpm")),
        factors_json={},
        raw_payload={},
    )


def _manual_entries_from_packet(day: date, packet: Any) -> list[ManualEntry]:
    if not isinstance(packet, list):
        return []
    entries: list[ManualEntry] = []
    for item in packet:
        if not isinstance(item, Mapping):
            continue
        entries.append(
            ManualEntry(
                entry_date=day,
                subjective_score=_int(item.get("subjectiveScore")),
                symptoms=item.get("symptoms") if isinstance(item.get("symptoms"), str) else None,
                feel=item.get("feel"),
                notes=item.get("notes"),
            )
        )
    return entries


def _planned_workouts_from_packet(day: date, packet: Any) -> list[PlannedWorkout]:
    if not isinstance(packet, list):
        return []
    workouts: list[PlannedWorkout] = []
    for item in packet:
        if not isinstance(item, Mapping):
            continue
        raw_id = item.get("id")
        try:
            workout_id = uuid.UUID(str(raw_id)) if raw_id else None
        except ValueError:
            workout_id = None
        workouts.append(
            PlannedWorkout(
                id=workout_id,
                workout_date=day,
                version=_int(item.get("version")) or 1,
                title=item.get("title"),
                workout_type=item.get("workoutType"),
                status=item.get("status"),
                is_active=True,
                planned_duration_min=_int(item.get("plannedDurationMin")),
                intensity_target=item.get("intensityTarget"),
                structured_workout=(
                    dict(item["structuredWorkout"])
                    if isinstance(item.get("structuredWorkout"), Mapping)
                    else {}
                ),
                source=item.get("source"),
            )
        )
    return workouts


def _as_of_baselines(
    day: date,
    metrics: Mapping[date, DailyMetric],
    sleeps: Mapping[date, Sleep],
) -> dict[str, MetricBaseline]:
    """The ladder's personal baselines as they stood before this morning.

    The same 84-night window and the same core (``compute_metric_baselines``) the
    nightly job uses, ending the night before, so a replay never reads today's
    baselines (SE-2).
    """

    start = day - timedelta(days=HISTORY_DAYS)
    samples: list[BaselineSample] = []
    for d in sorted(set(metrics) | set(sleeps)):
        if not start <= d < day:
            continue
        metric = metrics.get(d)
        sleep = sleeps.get(d)
        resting = (
            metric.resting_heart_rate_bpm
            if metric is not None and metric.resting_heart_rate_bpm is not None
            else sleep.resting_heart_rate_bpm
            if sleep is not None
            else None
        )
        samples.append(
            BaselineSample(
                calendar_date=d,
                values={
                    "readiness_score": metric.readiness_score if metric is not None else None,
                    "resting_heart_rate_bpm": resting,
                    "average_spo2_pct": sleep.average_spo2_pct if sleep is not None else None,
                    "average_respiration": (
                        sleep.average_respiration if sleep is not None else None
                    ),
                },
            )
        )
    specs = [spec for spec in BASELINE_SPECS if spec.metric_key in LADDER_BASELINE_KEYS]
    baselines: dict[str, MetricBaseline] = {}
    for fields in compute_metric_baselines(samples, source="replay_as_of", specs=specs):
        baselines[str(fields["metric_key"])] = MetricBaseline(
            metric_key=fields["metric_key"],
            metric_label=fields["metric_label"],
            source=fields["source"],
            window_start_date=fields["window_start_date"],
            window_end_date=fields["window_end_date"],
            sample_count=fields["sample_count"],
            excluded_sample_count=fields["excluded_sample_count"],
            mean_value=fields["mean_value"],
            median_value=fields["median_value"],
            lower_quartile_value=fields["lower_quartile_value"],
            upper_quartile_value=fields["upper_quartile_value"],
            raw_payload={},
        )
    return baselines


def _ladder_action(
    status: str,
    session: PlannedSession,
    *,
    bike_rest: bool,
    training_rest: bool,
    hold: bool,
) -> str:
    if training_rest:
        return "no_training"
    if not session.is_bike:
        return ACTION_AS_PLANNED
    if bike_rest:
        return ACTION_OFF_THE_BIKE
    if status == "Red":
        return ACTION_RECOVERY if session.is_hard else ACTION_SHORTENED_Z2
    if status == "Amber":
        return ACTION_AMBER_CUT
    return ACTION_HOLD_TARGETS if hold else ACTION_AS_PLANNED


def _next_morning(day: date, metrics: Mapping[date, DailyMetric], *, flagged: bool) -> NextMorning:
    """Next morning's HRV and resting HR against his 84-day median before it."""

    following = day + timedelta(days=1)
    row = metrics.get(following)
    window = [
        other
        for d, other in metrics.items()
        if following - timedelta(days=HISTORY_DAYS) <= d < following
    ]
    hrv_values = [
        float(other.hrv_last_night_avg_ms)
        for other in window
        if other.hrv_last_night_avg_ms is not None
    ]
    rhr_values = [
        float(other.resting_heart_rate_bpm)
        for other in window
        if other.resting_heart_rate_bpm is not None
    ]
    hrv_delta = (
        float(row.hrv_last_night_avg_ms) - median(hrv_values)
        if row is not None and row.hrv_last_night_avg_ms is not None and len(hrv_values) >= 21
        else None
    )
    rhr_delta = (
        float(row.resting_heart_rate_bpm) - median(rhr_values)
        if row is not None and row.resting_heart_rate_bpm is not None and len(rhr_values) >= 21
        else None
    )
    return NextMorning(
        subject_date=day, flagged=flagged, hrv_delta_ms=hrv_delta, rhr_delta_bpm=rhr_delta
    )


# -- the report --------------------------------------------------------------------------

_SHORT = {"none": "·", "mild": "mild", "marked": "MARKED"}
_KEY_ORDER = (
    "as_planned",
    "hold_targets",
    "move_or_hold",
    "ease_hard",
    "amber_cut",
    "shortened_zone2",
    "recovery",
    "off_the_bike",
    "no_training",
)


def _counts(values: Sequence[str | None]) -> str:
    counter = Counter(value or "none" for value in values)
    order = ("Green", "Green (held)", "Amber", "Red")
    return ", ".join(f"{counter.get(key, 0)} {key}" for key in order)


def red_rate(report: ReplayReport) -> float:
    if not report.mornings:
        return 0.0
    return sum(1 for m in report.mornings if m.graded.status == "Red") / len(report.mornings)


def floor_violations(report: ReplayReport) -> list[date]:
    """Mornings where a floor applies and the graded verdict weakens it."""

    violations: list[date] = []
    for morning in report.mornings:
        acute_floor = morning.ladder_bike_rest or morning.ladder_training_rest
        if not acute_floor and morning.graded.floor is None:
            continue
        weaker = (
            (morning.ladder_bike_rest and morning.graded.floor not in {"bike_rest", "no_training"})
            or (morning.ladder_training_rest and morning.graded.floor != "no_training")
            or (
                morning.ladder == "Red"
                and morning.graded.floor is not None
                and morning.graded.status != "Red"
            )
        )
        if weaker:
            violations.append(morning.subject_date)
    return violations


def render_markdown(report: ReplayReport, *, generated: str) -> str:
    """The committed replay report (295.9)."""

    mornings = report.mornings
    lines: list[str] = []
    add = lines.append
    add(f"# Graded verdict replay, {report.start:%-d %b} – {report.end:%-d %b %Y}")
    add("")
    add(
        f"{generated} · read-only replay of {len(mornings)} stored mornings "
        "through today's ladder and the graded verdict, each from the inputs it saw."
    )
    add("")
    add("## Totals")
    add("")
    add(f"- **Shown to Mark:** {_counts([m.shown_label for m in mornings])}")
    add(f"- **Today's ladder:** {_counts([m.ladder_label for m in mornings])}")
    add(f"- **Graded:** {_counts([m.graded_label for m in mornings])}")
    changed = [m for m in mornings if m.changed]
    add(f"- **Changed (ladder → graded):** {len(changed)} of {len(mornings)} mornings")
    graded_mornings = [m for m in mornings if m.reproduces_production is not None]
    if graded_mornings:
        drifted = [m for m in graded_mornings if not m.reproduces_production]
        add(
            f"- **Replay reproduces production:** {len(graded_mornings) - len(drifted)} of "
            f"{len(graded_mornings)} graded mornings"
            + (
                " — DRIFTED on " + ", ".join(f"{m.subject_date:%-d %b}" for m in drifted)
                if drifted
                else ""
            )
        )
    rate = red_rate(report)
    add(f"- **Red rate, graded:** {rate:.0%} ({sum(m.graded.status == 'Red' for m in mornings)})")
    violations = floor_violations(report)
    add(
        "- **Floors:** "
        + (
            "no morning is less cautious where a floor applies."
            if not violations
            else "WEAKENED on " + ", ".join(f"{d:%-d %b}" for d in violations)
        )
    )
    add("")
    add("### Ladder → graded")
    add("")
    matrix = Counter((m.ladder_label, m.graded_label) for m in mornings)
    order = ("Green", "Green (held)", "Amber", "Red")
    add("| Ladder \\ graded | " + " | ".join(order) + " |")
    add("|---|" + "---|" * len(order))
    for row in order:
        add(
            f"| {row} | " + " | ".join(str(matrix.get((row, col), 0) or "") for col in order) + " |"
        )
    add("")
    add("### What drives the graded colour")
    add("")
    for domain in DOMAINS:
        marked = sum(1 for m in mornings if m.graded.domain(domain).rating == "marked")
        mild = sum(1 for m in mornings if m.graded.domain(domain).rating == "mild")
        confirmed = sum(1 for m in mornings if m.graded.domain(domain).confirmed_by_readiness)
        add(
            f"- **{domain.capitalize()}:** marked {marked}, mild {mild}"
            + (f" (readiness confirmed {confirmed})" if confirmed else "")
        )
    floors = Counter(m.graded.floor for m in mornings if m.graded.floor)
    add(
        "- **Floors:** "
        + (", ".join(f"{name} {count}" for name, count in sorted(floors.items())) or "none")
    )
    add(f"- **Rough check-ins:** {sum(m.graded.rough_check_in for m in mornings)}")
    add(f"- **Age-credit guard:** {sum(m.graded.age_credit_guard_applied for m in mornings)}")
    add(f"- **Missing-data floor:** {sum(m.graded.missing_data_floor_applied for m in mornings)}")
    reds = [m for m in mornings if m.graded.status == "Red"]
    if rate > 0.1:
        causes = Counter(
            domain.domain for m in reds for domain in m.graded.domains if domain.rating == "marked"
        )
        add(
            "- **Red is above one morning in ten.** The domains marked on its Red mornings: "
            + ", ".join(f"{name} {count}" for name, count in causes.most_common())
        )
    add("")
    add("### Key sessions (VO₂, threshold-type, long ride)")
    add("")
    old: Counter[str] = Counter()
    new: Counter[str] = Counter()
    for m in mornings:
        for session, old_action, action in zip(
            m.sessions, m.old_actions or ("",) * len(m.sessions), m.graded.actions, strict=False
        ):
            if not session.is_key or m.rest_day:
                continue
            old[old_action] += 1
            new[action.action] += 1
    add("| Outcome | Ladder | Graded |")
    add("|---|---|---|")
    for key in _KEY_ORDER:
        if old.get(key) or new.get(key):
            add(f"| {key.replace('_', ' ')} | {old.get(key, 0)} | {new.get(key, 0)} |")
    add(f"| **key sessions planned** | {sum(old.values())} | {sum(new.values())} |")
    add("")
    add("## Every changed morning")
    add("")
    for m in changed:
        add(f"**{m.subject_date:%a %-d %b}** — ladder {m.ladder_label} → graded {m.graded_label}")
        for reason in m.graded.reasons:
            add(f"- {reason}")
        if not m.graded.reasons:
            add("- No domain is raised.")
        add(f"- Ladder's reasons: {'; '.join(m.ladder_reasons) or 'none'}")
        add("")
    add("## Every morning")
    add("")
    add("| Date | Shown | Ladder | Graded | Auto | Sleep | Load | Feel | Floor |")
    add("|---|---|---|---|---|---|---|---|---|")
    for m in mornings:
        ratings = [_SHORT[m.graded.domain(d).rating] for d in DOMAINS]
        add(
            f"| {m.subject_date:%-d %b} | {m.shown_label or '–'} | {m.ladder_label} | "
            f"{m.graded_label} | " + " | ".join(ratings) + f" | {m.graded.floor or ''} |"
        )
    add("")
    add("## Outcome proxies — directional only")
    add("")
    add("One person, about 100 mornings: these suggest, they do not prove.")
    add("")
    eased = report.executions_on_eased_mornings
    elsewhere = report.executions_elsewhere
    add(
        f"- **Hard sessions ridden on mornings the graded verdict would ease or move:** "
        f"{len(eased)}."
    )
    for record in eased:
        add(
            f"  - {record.subject_date:%-d %b} {record.title}: {record.on_target} of "
            f"{record.work_intervals} work intervals on target, {record.under} under, "
            f"{record.faded} faded"
        )
    share = _on_target_share(eased)
    other_share = _on_target_share(elsewhere)
    add(
        f"- **On-target share:** {share} on those mornings, {other_share} across the other "
        f"{len(elsewhere)} hard sessions."
    )
    flagged = [n for n in report.next_mornings if n.flagged]
    clear = [n for n in report.next_mornings if not n.flagged]
    add(
        "- **The morning after a hard session:** HRV "
        f"{_mean_or_dash([n.hrv_delta_ms for n in flagged])} ms and resting HR "
        f"{_mean_or_dash([n.rhr_delta_bpm for n in flagged])} bpm against his median when "
        f"that morning was flagged ({len(flagged)}); HRV "
        f"{_mean_or_dash([n.hrv_delta_ms for n in clear])} ms and resting HR "
        f"{_mean_or_dash([n.rhr_delta_bpm for n in clear])} bpm when it was not ({len(clear)})."
    )
    add(
        f"- **Dissents recorded:** {len(report.dissents)}"
        + (": " + ", ".join(f"{d:%-d %b}" for d in report.dissents) if report.dissents else "")
    )
    add("")
    add("## The lines")
    add("")
    add("| Line | Value | Source | Why |")
    add("|---|---|---|---|")
    for item in THRESHOLDS.values():
        add(f"| `{item.key}` | {item.value:g} {item.units} | {item.source} | {item.reason} |")
    add("")
    return "\n".join(lines)


def _on_target_share(records: Sequence[ExecutionRecord]) -> str:
    on_target = sum(record.on_target or 0 for record in records)
    total = sum(record.work_intervals or 0 for record in records)
    return f"{on_target}/{total} ({on_target / total:.0%})" if total else "–"


def _mean_or_dash(values: Sequence[float | None]) -> str:
    present = [value for value in values if value is not None]
    return f"{mean(present):+.1f}" if present else "–"


__all__ = [
    "ACTION_AMBER_CUT",
    "MorningRead",
    "ReplayReport",
    "ReplayedMorning",
    "VerdictReplayService",
    "floor_violations",
    "red_rate",
    "render_markdown",
    "replay_morning",
]
