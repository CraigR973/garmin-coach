"""Post-workout analysis context assembly, trigger selection, and Claude boundary."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

import httpx
from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Activity,
    ActivityTimeSeries,
    Analysis,
    KnowledgeBase,
    ManualEntry,
    PlannedWorkout,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile
from src.services.coaching_state import CoachingStateService
from src.services.feedback import FeedbackService
from src.services.ride_intervals import (
    power_zone,
    segment_ride_intervals,
    summarize_execution,
)
from src.services.workout_categories import DAY_CATEGORY_CYCLE, category_for_workout_type
from src.services.workout_completion import complete_matched_planned_workout
from src.services.workout_delivery import (
    DEFAULT_FTP_WATTS,
    STATUS_PUSHED,
    build_structured_workout_ir,
)

# Bumped for Batch 44: the packet now carries interval-resolved execution and the
# prompt grades work intervals against their own %FTP targets. The bump also marks
# older post-workout analyses for regeneration via ``_analysis_is_current``.
# Bumped again for Batch 64 (#137): the packet now carries the user's recent
# corrections so the read can acknowledge/adjust when he's pushed back before.
# Bumped for Batch 68 (#141): the packet grades against the delivered/accepted
# proposal IR when one exists, not the stale planned row.
# Bumped for Batch 80 (#153): the packet carries a deterministic ``rideDeviation``
# read so the analyst renders an honest good-call/bad-call verdict when the ride
# diverged from the planned/delivered session (Mark's Q1a).
PROMPT_VERSION = "post-workout-analysis-v5-2026-07-11"
ANALYSIS_TYPE = "post_workout"

# A planned session Mark told the app he was not doing (``skip_workout`` /
# ``skip_day``). Duplicated as a local literal to avoid importing the heavy
# ExecutableCoachingService just for the string.
WORKOUT_STATUS_SKIPPED = "skipped"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You are Garmin Coach, a private endurance post-workout analyst.
Use only the supplied context packet. Follow every data-quality guardrail.
Return concise markdown with a workout rating, performance read, specific timed
recovery protocol, and tomorrow impact. Incorporate any post-ride check-in
(RPE, feel, legs, niggles) when present. Include power, HR, zones, cadence,
Performance Condition, Stamina, and Training Effect when present.

Grade execution on the WORK intervals in `execution`/`intervals`, each against its
own %FTP target — not on the whole-ride average. On a structured session the
whole-ride average power sits BELOW the work target because the warm-up, recovery
valleys, and cool-down pull it down, so treat `activity.avgPowerWatts` and
`timeSeriesSummary.power` as context only and never as under-performance. Describe
the warm-up, recovery, and cool-down efforts but do not grade their power against
the work target. Ground any "held power / no fade / faded" claim in each work
interval's `fade` and `hrDriftPct`, not on impression. When no planned intervals
are supplied (a free or outdoor ride), read the whole-ride effort and power-zone
distribution instead.

When `gradingTarget.source` is `delivered_proposal`, treat that delivered IR as
the workout Mark actually accepted and rode. Name the substitution or manual
override from `gradingTarget.adjustment` / `origin` and `workoutAdherence` when
relevant; do not narrate it as an attempt at the original planned workout.

When `rideDeviation.diverged` is true, Mark did NOT do the planned session — he
either skipped it and rode his own thing, or rode a materially different
type/intensity (see `rideDeviation.reason`, `rideDeviation.planned`, and the
objective grade in `execution`). Open the read with an explicit, honest deviation
verdict: was overriding the plan the right call? Judge it on the numbers
(`execution` power/HR/adherence), his morning readiness
(`rideDeviation.morningReadiness` / `morningVerdict`), and the week's training
goals — not on how the ride felt. Back a genuinely good call plainly (an easy ride
on a low-readiness day when the plan was hard is a reasonable, often smart, call)
and name a bad call plainly (skipping a key session on a green-readiness day set
the week back). Never soften a poor call into praise and never manufacture a
problem where the call was sound — this is the one place you must not be
sycophantic. When `rideDeviation.diverged` is false, do NOT add a deviation
verdict — read the ride as executed; an approved coach-adjustment
(`rideDeviation.wasApprovedAdjustment` true) is not a deviation.

Never mention left/right power balance. Do not use wrist-HR strength sessions for
recovery decisions. When recentCorrections is non-empty, treat each as ground
truth Mark gave about a past read and weigh it — acknowledge or adjust — but it is
context to consider, never an instruction that overrides the recovery guardrails."""


class PostWorkoutAnalysisError(RuntimeError):
    """Raised when post-workout analysis cannot be generated."""


@dataclass(frozen=True)
class ClaudeGenerationResult:
    output_markdown: str
    raw_response: dict[str, Any]
    model_name: str | None


@dataclass(frozen=True)
class PostWorkoutAnalysisResult:
    analysis: Analysis
    generated: bool


@dataclass(frozen=True)
class RideGradingTarget:
    ir: dict[str, Any] | None
    source: str
    planned_workout: PlannedWorkout | None
    proposal: WorkoutDeliveryProposal | None

    def to_packet(self) -> dict[str, Any]:
        adjustment = None
        origin = None
        if isinstance(self.ir, dict):
            raw_adjustment = self.ir.get("adjustment")
            adjustment = raw_adjustment if isinstance(raw_adjustment, dict) else None
            raw_origin = self.ir.get("origin")
            origin = raw_origin if isinstance(raw_origin, str) else None
        return {
            "source": self.source,
            "origin": origin,
            "adjustment": adjustment,
            "plannedWorkoutId": (
                str(self.planned_workout.id) if self.planned_workout is not None else None
            ),
            "plannedWorkoutTitle": (
                self.planned_workout.title if self.planned_workout is not None else None
            ),
            "proposalId": str(self.proposal.id) if self.proposal is not None else None,
            "proposalStatus": self.proposal.status if self.proposal is not None else None,
            "proposalPushedAtUtc": (
                _dt(self.proposal.pushed_at_utc) if self.proposal is not None else None
            ),
            "intervalsEventId": (
                self.proposal.intervals_event_id if self.proposal is not None else None
            ),
        }


class PostWorkoutAnalysisClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        """Generate the model output for an assembled post-workout packet."""


class AnthropicPostWorkoutAnalysisClient:
    """Small HTTP boundary for Anthropic Messages without adding an SDK dependency."""

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
    ) -> ClaudeGenerationResult:
        if not self.api_key:
            raise PostWorkoutAnalysisError("ANTHROPIC_API_KEY is not configured.")

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
            raise PostWorkoutAnalysisError("Claude response was not a JSON object.")

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
            raise PostWorkoutAnalysisError("Claude response did not contain text output.")

        model = raw.get("model")
        return ClaudeGenerationResult(
            output_markdown=output,
            raw_response=raw,
            model_name=model if isinstance(model, str) else self.model_name,
        )


class PostWorkoutAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_ride_activities(
        self,
        user_id: uuid.UUID,
        *,
        since: datetime | None = None,
    ) -> list[Activity]:
        lower_bound = since or (_utcnow() - timedelta(days=7))
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == user_id,
                        Activity.start_utc >= lower_bound,
                        Activity.exclude_from_recovery.is_(False),
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )

        pending: list[Activity] = []
        for activity in rows:
            if not _is_ride(activity):
                continue
            latest = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._post_ride_checkin(activity.user_id, activity.id)
            if latest is None or not _analysis_is_current(latest, checkin):
                pending.append(activity)
        return pending

    async def generate_for_pending_rides(
        self,
        player: Profile,
        *,
        since: datetime | None = None,
        client: PostWorkoutAnalysisClient | None = None,
        commit: bool = True,
    ) -> list[PostWorkoutAnalysisResult]:
        results: list[PostWorkoutAnalysisResult] = []
        for activity in await self.pending_ride_activities(player.id, since=since):
            results.append(
                await self.generate_and_store(
                    player,
                    activity,
                    client=client,
                    commit=False,
                )
            )
        if commit:
            await self.session.commit()
            for result in results:
                await self.session.refresh(result.analysis)
        else:
            await self.session.flush()
        return results

    async def assemble_context_packet(self, player: Profile, activity: Activity) -> dict[str, Any]:
        await CoachingStateService(self.session).ensure_seeded(player, commit=False)

        subject_date = _activity_local_date(activity, player.timezone)
        kb_rows = await self._active_knowledge_base(player.id)
        knowledge_base = {row.section: row.content for row in kb_rows}
        planned_workouts = await self._planned_workouts(player.id, subject_date)
        morning_analysis = await self._latest_morning_analysis(player.id, subject_date)
        post_ride_checkin = await self._post_ride_checkin(player.id, activity.id)
        recent_corrections = await FeedbackService(self.session).recent_corrections(player.id)
        timeseries = await self._timeseries(activity.id)
        ftp_watts = _ftp_watts(knowledge_base)
        time_series_summary = _time_series_summary(timeseries, ftp_watts)
        recovery_decision = _recovery_decision_packet(activity)
        grading_target = await self._ride_grading_target(
            player.id,
            subject_date,
            planned_workouts,
            ftp_watts,
        )
        planned_ir = grading_target.ir
        adherence = await self._workout_adherence(
            player.id,
            subject_date,
            grading_target.planned_workout.id if grading_target.planned_workout else None,
        )
        intervals = segment_ride_intervals(timeseries, planned_ir, ftp_watts)
        execution = summarize_execution(
            intervals,
            whole_ride_avg_power_watts=activity.avg_power_watts,
        )
        morning_verdict = _morning_analysis_packet(morning_analysis)
        ride_deviation = detect_ride_deviation(
            grading_target=grading_target,
            execution=execution,
            planned_workouts=planned_workouts,
            workout_adherence=adherence,
            activity=activity,
            morning_verdict=morning_verdict,
        )

        return {
            "packetType": "post_workout_analysis",
            "packetVersion": 1,
            "subjectDate": subject_date.isoformat(),
            "generatedAtUtc": _utcnow().isoformat() + "Z",
            "profile": {
                "userId": str(player.id),
                "displayName": player.display_name,
                "timezone": player.timezone,
                "athleteProfile": knowledge_base.get("profile", {}),
                "ftpWatts": ftp_watts,
            },
            "knowledgeBase": {
                "dataQualityGuardrails": _data_quality_guardrails(knowledge_base),
                "trainingPlan": knowledge_base.get("training_plan", {}),
                "analysisRules": knowledge_base.get("analysis_rules", {}),
            },
            "activity": _activity_packet(activity),
            "timeSeriesSummary": time_series_summary,
            "plannedWorkoutIr": planned_ir,
            "gradingTarget": grading_target.to_packet(),
            "intervals": intervals,
            "execution": execution,
            "rideDeviation": ride_deviation,
            "plannedWorkouts": [_planned_workout_packet(workout) for workout in planned_workouts],
            "morningVerdict": morning_verdict,
            "postRideCheckIn": _manual_entry_packet(post_ride_checkin),
            "workoutAdherence": _manual_entry_packet(adherence),
            "recentCorrections": [c.to_packet() for c in recent_corrections],
            "recoveryDecision": recovery_decision,
            "prompt": {
                "version": PROMPT_VERSION,
                "system": SYSTEM_PROMPT,
                "outputRules": [
                    "include_workout_rating",
                    "incorporate_post_ride_check_in_when_present",
                    "include_power_hr_zones_cadence_performance_condition_stamina_training_effect",
                    "include_specific_timed_recovery_protocol",
                    "include_tomorrow_impact",
                    "grade_execution_on_work_intervals_vs_ftp_targets",
                    "whole_ride_average_power_is_context_not_under_performance",
                    "describe_but_do_not_grade_warmup_recovery_cooldown",
                    "ground_fade_claims_in_interval_fade_and_hr_drift",
                    "fall_back_to_whole_ride_read_when_no_planned_intervals",
                    "grade_against_delivered_proposal_ir_when_present",
                    "name_accepted_substitution_or_manual_override_when_present",
                    "render_deviation_verdict_when_ride_diverged_from_plan",
                    "judge_override_on_readiness_and_objective_grade_never_sycophantic",
                    "no_deviation_verdict_on_plan_or_approved_adjustment",
                    "never_reference_left_right_power_balance",
                    "exclude_wrist_hr_strength_from_recovery_decisions",
                    "acknowledge_recent_user_corrections_when_relevant",
                ],
            },
        }

    async def generate_and_store(
        self,
        player: Profile,
        activity: Activity,
        *,
        client: PostWorkoutAnalysisClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> PostWorkoutAnalysisResult:
        subject_date = _activity_local_date(activity, player.timezone)
        # Flip the planned bike session this ride completed to ``completed`` (Batch
        # 60) — so its Today-card row shows the read instead of the approve/upload
        # controls, and it can no longer be re-slotted. Runs before the current-
        # analysis short-circuit so an already-analysed ride still gets linked.
        matched_workout_id = await complete_matched_planned_workout(
            self.session,
            user_id=player.id,
            subject_date=subject_date,
            category=DAY_CATEGORY_CYCLE,
            activity_id=activity.id,
        )
        if not force:
            existing = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._post_ride_checkin(player.id, activity.id)
            if existing is not None and _analysis_is_current(existing, checkin):
                if (
                    matched_workout_id is not None
                    and existing.planned_workout_id != matched_workout_id
                ):
                    existing.planned_workout_id = matched_workout_id
                if commit:
                    await self.session.commit()
                    await self.session.refresh(existing)
                else:
                    await self.session.flush()
                return PostWorkoutAnalysisResult(analysis=existing, generated=False)

        context_packet = await self.assemble_context_packet(player, activity)
        user_prompt = build_post_workout_user_prompt(context_packet)
        analysis_client = client or AnthropicPostWorkoutAnalysisClient()
        generation = await analysis_client.generate(
            context_packet=context_packet,
            user_prompt=user_prompt,
        )
        verdict = context_packet.get("recoveryDecision", {}).get("status")
        analysis = Analysis(
            user_id=player.id,
            activity_id=activity.id,
            planned_workout_id=matched_workout_id,
            analysis_type=ANALYSIS_TYPE,
            subject_date=subject_date,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION,
            model_name=generation.model_name,
            verdict=verdict if isinstance(verdict, str) else None,
            context_packet=context_packet,
            output_markdown=generation.output_markdown,
            raw_response=generation.raw_response,
        )
        self.session.add(analysis)
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
        else:
            await self.session.flush()
        return PostWorkoutAnalysisResult(analysis=analysis, generated=True)

    async def latest_analysis_for_activity(self, activity_id: uuid.UUID) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.activity_id == activity_id,
                    Analysis.analysis_type == ANALYSIS_TYPE,
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    async def _active_knowledge_base(self, user_id: uuid.UUID) -> list[KnowledgeBase]:
        rows = (
            (
                await self.session.execute(
                    select(KnowledgeBase)
                    .where(KnowledgeBase.user_id == user_id, KnowledgeBase.is_active.is_(True))
                    .order_by(KnowledgeBase.section.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _planned_workouts(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> list[PlannedWorkout]:
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == subject_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                    .order_by(PlannedWorkout.version.desc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _latest_morning_analysis(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == "morning",
                    Analysis.subject_date == subject_date,
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    async def _post_ride_checkin(
        self,
        user_id: uuid.UUID,
        activity_id: uuid.UUID,
    ) -> ManualEntry | None:
        return cast(
            ManualEntry | None,
            await self.session.scalar(
                select(ManualEntry)
                .where(
                    ManualEntry.user_id == user_id,
                    ManualEntry.activity_id == activity_id,
                )
                .order_by(desc(ManualEntry.entry_at_utc), desc(ManualEntry.created_at))
                .limit(1)
            ),
        )

    async def _workout_adherence(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        planned_workout_id: uuid.UUID | None,
    ) -> ManualEntry | None:
        if planned_workout_id is None:
            return None
        return cast(
            ManualEntry | None,
            await self.session.scalar(
                select(ManualEntry)
                .where(
                    ManualEntry.user_id == user_id,
                    ManualEntry.entry_date == subject_date,
                    ManualEntry.planned_workout_id == planned_workout_id,
                )
                .order_by(desc(ManualEntry.entry_at_utc), desc(ManualEntry.created_at))
                .limit(1)
            ),
        )

    async def _timeseries(self, activity_id: uuid.UUID) -> list[ActivityTimeSeries]:
        rows = (
            (
                await self.session.execute(
                    select(ActivityTimeSeries)
                    .where(ActivityTimeSeries.activity_id == activity_id)
                    .order_by(ActivityTimeSeries.sample_index.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _ride_grading_target(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        planned_workouts: Sequence[PlannedWorkout],
        ftp_watts: int | None,
    ) -> RideGradingTarget:
        planned_workout = _planned_ride_workout(planned_workouts)
        proposal = None
        if planned_workout is not None:
            proposal = await self._latest_delivered_proposal_for_workout(
                user_id, planned_workout.id
            )
        if proposal is None:
            proposal = await self._latest_delivered_proposal_for_date(user_id, subject_date)
        if proposal is not None and isinstance(proposal.structured_workout_ir, dict):
            return RideGradingTarget(
                ir=proposal.structured_workout_ir,
                source="delivered_proposal",
                planned_workout=planned_workout,
                proposal=proposal,
            )

        planned_ir = _planned_ride_ir(planned_workouts, ftp_watts)
        return RideGradingTarget(
            ir=planned_ir,
            source="planned_workout" if planned_ir is not None else "none",
            planned_workout=planned_workout if planned_ir is not None else None,
            proposal=None,
        )

    async def _latest_delivered_proposal_for_workout(
        self,
        user_id: uuid.UUID,
        planned_workout_id: uuid.UUID,
    ) -> WorkoutDeliveryProposal | None:
        return cast(
            WorkoutDeliveryProposal | None,
            await self.session.scalar(
                select(WorkoutDeliveryProposal)
                .where(
                    WorkoutDeliveryProposal.user_id == user_id,
                    WorkoutDeliveryProposal.planned_workout_id == planned_workout_id,
                    WorkoutDeliveryProposal.status == STATUS_PUSHED,
                    WorkoutDeliveryProposal.intervals_event_id.is_not(None),
                )
                .order_by(desc(WorkoutDeliveryProposal.created_at))
                .limit(1)
            ),
        )

    async def _latest_delivered_proposal_for_date(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> WorkoutDeliveryProposal | None:
        return cast(
            WorkoutDeliveryProposal | None,
            await self.session.scalar(
                select(WorkoutDeliveryProposal)
                .where(
                    WorkoutDeliveryProposal.user_id == user_id,
                    WorkoutDeliveryProposal.workout_date == subject_date,
                    WorkoutDeliveryProposal.status == STATUS_PUSHED,
                    WorkoutDeliveryProposal.intervals_event_id.is_not(None),
                )
                .order_by(desc(WorkoutDeliveryProposal.created_at))
                .limit(1)
            ),
        )


def build_post_workout_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Generate the post-workout Garmin Coach analysis from this context packet.\n\n"
        "Context packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Garmin logs cycling under several typeKeys — cycling, indoor_cycling,
# road_biking, mountain_biking, gravel_cycling, virtual_ride. "bike" alone misses
# "road_biking" (it contains "biking"), and virtual rides carry neither token, so
# outdoor and virtual rides were silently skipped for post-workout analysis.
_RIDE_TYPE_TOKENS = ("cycling", "bike", "biking")


def _is_ride(activity: Activity) -> bool:
    activity_type = activity.activity_type.lower()
    activity_name = activity.activity_name.lower()
    if activity_type == "virtual_ride" or activity_type.endswith("_ride"):
        return True
    return any(token in activity_type or token in activity_name for token in _RIDE_TYPE_TOKENS)


def _activity_local_date(activity: Activity, timezone_name: str) -> date:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone = ZoneInfo("UTC")
        return activity.start_utc.replace(tzinfo=UTC).astimezone(timezone).date()
    except Exception:
        return activity.start_utc.date()


def _data_quality_guardrails(knowledge_base: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = knowledge_base.get("data_quality_rules", {})
    rules = section.get("rules") if isinstance(section, dict) else None
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _ftp_watts(knowledge_base: Mapping[str, Any]) -> int | None:
    profile = knowledge_base.get("profile", {})
    if not isinstance(profile, dict):
        return None
    ftp = profile.get("ftpWatts")
    if isinstance(ftp, int | float):
        return int(ftp)
    return None


def _activity_packet(row: Activity) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "garminActivityId": row.garmin_activity_id,
        "garminActivityUuid": row.garmin_activity_uuid,
        "activityName": row.activity_name,
        "activityType": row.activity_type,
        "startUtc": _dt(row.start_utc),
        "endUtc": _dt(row.end_utc),
        "durationMin": _minutes(row.duration_sec),
        "elapsedDurationMin": _minutes(row.elapsed_duration_sec),
        "movingDurationMin": _minutes(row.moving_duration_sec),
        "distanceM": row.distance_m,
        "calories": row.calories,
        "avgHeartRateBpm": row.avg_heart_rate_bpm,
        "maxHeartRateBpm": row.max_heart_rate_bpm,
        "avgPowerWatts": row.avg_power_watts,
        "maxPowerWatts": row.max_power_watts,
        "normalizedPowerWatts": row.normalized_power_watts,
        "intensityFactor": row.intensity_factor,
        "trainingLoad": row.training_load,
        "aerobicTrainingEffect": row.aerobic_training_effect,
        "anaerobicTrainingEffect": row.anaerobic_training_effect,
        "avgCadenceRpm": row.avg_cadence_rpm,
        "maxCadenceRpm": row.max_cadence_rpm,
        "avgRespiration": row.avg_respiration,
        "maxRespiration": row.max_respiration,
        "excludeFromRecovery": row.exclude_from_recovery,
    }


def _time_series_summary(
    rows: Sequence[ActivityTimeSeries],
    ftp_watts: int | None,
) -> dict[str, Any]:
    power_values = [row.power_watts for row in rows if row.power_watts is not None]
    hr_values = [row.heart_rate_bpm for row in rows if row.heart_rate_bpm is not None]
    cadence_values = [row.cadence_rpm for row in rows if row.cadence_rpm is not None]
    respiration_values = [row.respiration for row in rows if row.respiration is not None]
    pc_values = [row.performance_condition for row in rows if row.performance_condition is not None]
    available_stamina_values = [
        row.available_stamina for row in rows if row.available_stamina is not None
    ]
    potential_stamina_values = [
        row.potential_stamina for row in rows if row.potential_stamina is not None
    ]

    return {
        "sampleCount": len(rows),
        "power": _series_stats(power_values),
        "heartRate": _series_stats(hr_values),
        "cadence": _series_stats(cadence_values),
        "respiration": _series_stats(respiration_values),
        "performanceCondition": {
            **_series_stats(pc_values),
            "start": pc_values[0] if pc_values else None,
            "end": pc_values[-1] if pc_values else None,
        },
        "stamina": {
            "availableStart": available_stamina_values[0] if available_stamina_values else None,
            "availableEnd": available_stamina_values[-1] if available_stamina_values else None,
            "availableMin": min(available_stamina_values) if available_stamina_values else None,
            "potentialStart": potential_stamina_values[0] if potential_stamina_values else None,
            "potentialEnd": potential_stamina_values[-1] if potential_stamina_values else None,
        },
        "powerZones": _power_zone_distribution(rows, ftp_watts),
    }


def _series_stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "min": None, "max": None}
    return {
        "avg": round(sum(values) / len(values), 2),
        "min": min(values),
        "max": max(values),
    }


def _power_zone_distribution(
    rows: Sequence[ActivityTimeSeries],
    ftp_watts: int | None,
) -> list[dict[str, Any]]:
    if ftp_watts is None:
        return []
    counts: Counter[str] = Counter()
    for row in rows:
        zone = power_zone(row.power_watts, ftp_watts)
        if zone is None:
            continue
        counts[zone] += 1
    total = sum(counts.values())
    if total == 0:
        return []
    return [
        {
            "zone": zone,
            "sampleCount": counts[zone],
            "samplePct": round((counts[zone] / total) * 100, 1),
        }
        for zone in ("Z1", "Z2", "Z3", "Z4", "Z5", "Z6")
        if counts[zone] > 0
    ]


def _planned_ride_ir(
    planned_workouts: Sequence[PlannedWorkout],
    ftp_watts: int | None,
) -> dict[str, Any] | None:
    """Build the planned structured-workout IR (Batch 12.1) for the day's first
    structured bike workout, or ``None`` for a free/outdoor ride with no plan — in
    which case segmentation degrades to the whole-ride read (Batch 44.4)."""
    workout = _planned_ride_workout(planned_workouts)
    if workout is None:
        return None
    try:
        return build_structured_workout_ir(workout, ftp_watts=ftp_watts or DEFAULT_FTP_WATTS)
    except HTTPException:
        return None


def _planned_ride_workout(planned_workouts: Sequence[PlannedWorkout]) -> PlannedWorkout | None:
    for workout in planned_workouts:
        structured = workout.structured_workout
        if not isinstance(structured, dict) or structured.get("format") != "bike":
            continue
        if not structured.get("steps"):
            continue
        return workout
    return None


def _planned_workout_packet(row: PlannedWorkout) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workoutDate": row.workout_date.isoformat(),
        "version": row.version,
        "title": row.title,
        "workoutType": row.workout_type,
        "status": row.status,
        "plannedDurationMin": row.planned_duration_min,
        "intensityTarget": row.intensity_target,
        "structuredWorkout": row.structured_workout,
        "source": row.source,
    }


def _morning_analysis_packet(row: Analysis | None) -> dict[str, Any] | None:
    if row is None:
        return None
    verdict = row.context_packet.get("verdict", {}) if isinstance(row.context_packet, dict) else {}
    return {
        "id": str(row.id),
        "generatedAtUtc": _dt(row.generated_at_utc),
        "verdict": row.verdict,
        "reasons": verdict.get("reasons", []) if isinstance(verdict, dict) else [],
        "planAdjustments": verdict.get("planAdjustments", []) if isinstance(verdict, dict) else [],
        "readinessInterpretation": (
            verdict.get("readinessInterpretation") if isinstance(verdict, dict) else None
        ),
    }


def _manual_entry_packet(row: ManualEntry | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "entryDate": row.entry_date.isoformat(),
        "entryAtUtc": _dt(row.entry_at_utc),
        "activityId": str(row.activity_id) if row.activity_id else None,
        "plannedWorkoutId": str(row.planned_workout_id) if row.planned_workout_id else None,
        "plannedWorkoutVersion": row.planned_workout_version,
        "subjectiveScore": row.subjective_score,
        "rpe": row.rpe,
        "feel": row.feel,
        "adherenceStatus": row.adherence_status,
        "actualWorkoutJson": row.actual_workout_json,
        "notes": row.notes,
    }


def _analysis_is_current(analysis: Analysis, checkin: ManualEntry | None) -> bool:
    """An analysis is current only if it was generated by the live prompt version and
    already reflects the latest post-ride check-in. Bumping ``PROMPT_VERSION`` (Batch
    44) therefore marks older analyses as stale so the hourly poll and the backfill
    regenerate them through the new interval-resolved packet."""
    return analysis.prompt_version == PROMPT_VERSION and _analysis_covers_post_ride_checkin(
        analysis, checkin
    )


def _analysis_covers_post_ride_checkin(
    analysis: Analysis,
    checkin: ManualEntry | None,
) -> bool:
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    packet_checkin = packet.get("postRideCheckIn")
    if checkin is None:
        return packet_checkin is None
    if not isinstance(packet_checkin, dict):
        return False
    return packet_checkin.get("entryAtUtc") == _dt(checkin.entry_at_utc)


def _recovery_decision_packet(activity: Activity) -> dict[str, Any]:
    if activity.exclude_from_recovery:
        return {
            "status": "excluded",
            "excluded": True,
            "reason": "Strength/wrist-HR activity is excluded from recovery decisions.",
        }
    return {
        "status": "ready_for_review",
        "excluded": False,
        "reason": "Cycling activity can inform post-workout recovery guidance.",
    }


def detect_ride_deviation(
    *,
    grading_target: RideGradingTarget,
    execution: Mapping[str, Any],
    planned_workouts: Sequence[PlannedWorkout],
    workout_adherence: ManualEntry | None,
    activity: Activity,
    morning_verdict: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Deterministically decide whether this ride diverged from the day's
    planned/delivered bike session (Batch 80, Mark's Q1a).

    Divergence fires only when a bike session was actually on the plan/delivery and
    Mark did not do it as prescribed — he skipped it and rode his own thing, or rode
    a materially different type/intensity (every gradable work interval off target in
    the same direction). It reuses the Batch 68 delivered-vs-actual grade in
    ``execution`` as the objective anchor and never flags an approved coach-adjustment
    (that is a sanctioned change, not a self-chosen override) or a graded attempt at
    the plan (some work on target). A day with no bike plan is a free ride, not an
    override, so it is not flagged. The good-call/bad-call *judgement* is left to the
    analyst prompt, anchored on the readiness + objective grade this packet carries.
    """
    approved_adjustment = _is_approved_adjustment(grading_target, workout_adherence)
    skipped_workout = _skipped_bike_workout(planned_workouts)
    source = grading_target.source

    has_gradable_plan = (
        bool(execution.get("hasPlan")) and int(execution.get("workIntervalCount") or 0) > 0
    )
    work_count = int(execution.get("workIntervalCount") or 0)
    on_target = int(execution.get("onTargetCount") or 0)
    over = int(execution.get("overCount") or 0)
    under = int(execution.get("underCount") or 0)

    diverged = False
    kind = "on_plan"
    reason = "No divergence from the planned session detected."

    if approved_adjustment:
        kind = "approved_adjustment"
        reason = (
            "Rode the coach-adjusted session he approved — a sanctioned change, not an override."
        )
    elif skipped_workout is not None:
        diverged = True
        kind = "skipped_and_rode"
        reason = (
            f"Skipped the planned {skipped_workout.title} and rode a self-chosen session instead."
        )
    elif source in ("planned_workout", "delivered_proposal") and has_gradable_plan:
        # A real attempt lands at least one work interval on target; every work
        # interval off in the SAME direction is a different session, not a fade.
        if on_target == 0 and over == 0 and under > 0:
            diverged = True
            kind = "easier_than_planned"
            reason = (
                f"Rode easier than the planned session: all {work_count} work "
                "interval(s) came in under target."
            )
        elif on_target == 0 and under == 0 and over > 0:
            diverged = True
            kind = "harder_than_planned"
            reason = (
                f"Rode harder than the planned session: all {work_count} work "
                "interval(s) came in over target."
            )
    elif source == "none":
        kind = "free_ride"
        reason = "No bike session was planned — a free ride, not a plan override."

    return {
        "diverged": diverged,
        "kind": kind,
        "reason": reason,
        "wasApprovedAdjustment": approved_adjustment,
        "plannedSessionSkipped": skipped_workout is not None,
        "gradingSource": source,
        "planned": _deviation_planned_summary(
            grading_target.planned_workout or skipped_workout, grading_target.ir
        ),
        "actual": _deviation_actual_summary(execution, activity),
        "morningReadiness": _deviation_readiness(morning_verdict),
        "signals": {
            "hasGradablePlan": has_gradable_plan,
            "workIntervalCount": work_count,
            "onTargetCount": on_target,
            "overCount": over,
            "underCount": under,
        },
    }


def _is_approved_adjustment(
    grading_target: RideGradingTarget,
    workout_adherence: ManualEntry | None,
) -> bool:
    """True when the delivered IR is a coach-adjustment Mark approved (Batch 68/69),
    so grading it against what he rode is on-plan, not a self-chosen override."""
    if grading_target.source == "delivered_proposal" and isinstance(grading_target.ir, dict):
        adjustment = grading_target.ir.get("adjustment")
        if isinstance(adjustment, dict) and adjustment.get("changed") is True:
            return True
    if workout_adherence is not None:
        actual = workout_adherence.actual_workout_json
        if isinstance(actual, dict) and actual.get("source") == "accepted_adjustment":
            return True
    return False


def _skipped_bike_workout(planned_workouts: Sequence[PlannedWorkout]) -> PlannedWorkout | None:
    for workout in planned_workouts:
        if workout.status != WORKOUT_STATUS_SKIPPED:
            continue
        if category_for_workout_type(workout.workout_type) == DAY_CATEGORY_CYCLE:
            return workout
    return None


def _deviation_planned_summary(
    workout: PlannedWorkout | None,
    ir: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if workout is None and not isinstance(ir, dict):
        return None
    summary: dict[str, Any] = {}
    if workout is not None:
        summary.update(
            {
                "title": workout.title,
                "workoutType": workout.workout_type,
                "intensityTarget": workout.intensity_target,
                "plannedDurationMin": workout.planned_duration_min,
                "status": workout.status,
            }
        )
    if isinstance(ir, dict):
        name = ir.get("name")
        summary["irName"] = name if isinstance(name, str) else None
    return summary or None


def _deviation_actual_summary(
    execution: Mapping[str, Any],
    activity: Activity,
) -> dict[str, Any]:
    return {
        "executionSummary": execution.get("summary"),
        "avgPowerWatts": activity.avg_power_watts,
        "avgHeartRateBpm": activity.avg_heart_rate_bpm,
        "durationMin": _minutes(activity.duration_sec),
    }


def _deviation_readiness(morning_verdict: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(morning_verdict, Mapping):
        return None
    return {
        "verdict": morning_verdict.get("verdict"),
        "readinessInterpretation": morning_verdict.get("readinessInterpretation"),
    }


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _minutes(seconds: float | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None
