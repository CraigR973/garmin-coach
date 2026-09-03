"""Executable coaching — close the loop from morning verdict to Zwift delivery.

Batch 13 turns the daily verdict into an *acted-on* workout (Decision #30):

  * On an **Amber or Red** morning verdict, ``regenerate_for_verdict`` rebuilds
    today's bike workout — Amber as an adjusted proposal (cut duration ~25% and
    ease hard intervals a zone via ``verdict_scaling``, holding an already-Zone-2
    ride's intensity — Batch 173.2), Red as an easy recovery substitution — and
    stores it through the Batch 12 rail.
  * ``adjust_ir_for_verdict`` (now shared from ``verdict_scaling``) is a
    deterministic transform on the normalized ``%FTP`` IR, so the verdict framework
    — and the hard guarantee that **Red never emits VO2** — is testable rule code,
    not an LLM call.
  * ``auto_push_due`` delivers already-**approved** proposals due today; Batch 25
    supersedes the old couple-days-ahead lead window from Decision #31. It never
    pushes anything unapproved (Decision #29). Batch 243 also puts Red-never-VO2
    inside every Zwift create/update rail, so baseline reconcile and direct API
    callers cannot bypass it.
  * Every proposal and push is written to the ``analyses`` audit log (Batch 9
    pattern) so each delivery has inspectable evidence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, ManualEntry, PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile
from src.services.chronic_patterns import CHRONIC_DELOAD_WINDOW_DAYS
from src.services.daily_loop import ANALYSIS_TYPE_MORNING
from src.services.garmin_workout_delivery import (
    GarminWorkoutClient,
    GarminWorkoutDeliveryService,
)
from src.services.interval_workout_editor import (
    EditableIntervalBlock,
    apply_interval_block,
    block_workout_type,
)
from src.services.structured_workout_builder import (
    is_indoor_bike_workout,
    is_outdoor_bike_workout,
)
from src.services.verdict_scaling import (
    MIN_POWER_PCT,
    _normalize_verdict,
    adjust_ir_for_chronic_deload,
    adjust_ir_for_verdict,
    blocks_red_vo2,
    companion_session_present,
)
from src.services.workout_categories import category_for_workout_type
from src.services.workout_completion import WORKOUT_STATUS_COMPLETED
from src.services.workout_delivery import (
    STATUS_APPROVED,
    STATUS_DELETED,
    STATUS_FAILED,
    STATUS_PROPOSED,
    STATUS_PUSHED,
    IntervalsEventClient,
    WorkoutDeliveryService,
    build_intervals_payload,
    build_structured_workout_ir,
    build_zwo_xml,
    expand_structured_steps,
)

if TYPE_CHECKING:
    pass

PROMPT_VERSION = "executable-coaching:v1"
AUDIT_TYPE_PROPOSED = "workout_proposed"
AUDIT_TYPE_PUSHED = "workout_pushed"
AUDIT_TYPE_PUSH_BLOCKED = "workout_push_blocked"
AUDIT_TYPE_PROPOSAL_EXPIRED = "workout_proposal_expired"
# Batch 29 push-on-plan-set + Today-card action audit types (analyses rows).
AUDIT_TYPE_DELIVERED = "workout_delivered"
AUDIT_TYPE_REPLACED = "workout_replaced"
AUDIT_TYPE_MOVED = "workout_moved"
AUDIT_TYPE_SKIPPED = "workout_skipped"
AUDIT_TYPE_REMOVED = "workout_removed"
WORKOUT_STATUS_SKIPPED = "skipped"
DEFAULT_LEAD_DAYS = 0
DONE_ADHERENCE_STATUSES = {"completed", "modified", "done", "did_something_else"}

# The verdict-scaling knobs (AMBER/RED duration, zone drop, caps, MIN_POWER_PCT)
# and the deterministic transform now live in ``verdict_scaling`` so the delivery
# transform, the interval-editor preset, and the narrative share one rule
# (Batch 173.2). Only the manual-override ceiling is specific to this module.
MAX_MANUAL_POWER_PCT = 150

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _local_today(timezone_name: str, now_utc: datetime | None = None) -> date:
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return now.astimezone(timezone).date()


def _proposal_content_matches_workout(
    proposal: WorkoutDeliveryProposal,
    workout: PlannedWorkout,
    expected_ir: dict[str, Any],
) -> bool:
    """Require both the local pointer and intended delivered IR to match.

    The IR is the persisted snapshot of what intervals.icu last accepted. Using
    its workout id/version alongside the mutable relationship columns prevents a
    stale or legacy false pointer from suppressing reconciliation. Verdict-driven
    baseline delivery is re-synced when the day's light changes, while a manual
    edit remains deliberate and is never silently overwritten.
    """
    ir = proposal.structured_workout_ir
    if not isinstance(ir, dict):
        return False
    pointers_match = (
        proposal.planned_workout_id == workout.id
        and proposal.planned_workout_version == workout.version
        and ir.get("plannedWorkoutId") == str(workout.id)
        and ir.get("plannedWorkoutVersion") == workout.version
    )
    if not pointers_match:
        return False
    automatic_origins = {
        "as_planned",
        "amber_regeneration",
        "red_substitution",
        "red_endurance_hold",
    }
    if str(ir.get("origin") or "") not in automatic_origins:
        return True
    return ir == expected_ir


def apply_manual_override_to_ir(
    base_ir: dict[str, Any],
    *,
    duration_scale_pct: int | None = None,
    intensity_scale_pct: int | None = None,
) -> dict[str, Any]:
    """Return a copy of ``base_ir`` with Mark's manual duration/intensity dial applied."""
    if duration_scale_pct is None and intensity_scale_pct is None:
        return dict(base_ir)

    duration_scale = (duration_scale_pct or 100) / 100
    intensity_scale = (intensity_scale_pct or 100) / 100
    raw_steps = base_ir.get("steps")
    steps = [s for s in raw_steps if isinstance(s, dict)] if isinstance(raw_steps, list) else []
    adjusted_steps: list[dict[str, Any]] = []
    for step in steps:
        next_step = dict(step)
        next_step["durationSec"] = max(1, round(int(step.get("durationSec", 0)) * duration_scale))
        for key in ("powerStartPct", "powerEndPct"):
            next_step[key] = max(
                MIN_POWER_PCT,
                min(MAX_MANUAL_POWER_PCT, round(int(step.get(key, 0)) * intensity_scale)),
            )
        next_step["kind"] = (
            "ramp" if next_step["powerStartPct"] != next_step["powerEndPct"] else "steady"
        )
        adjusted_steps.append(next_step)

    adjusted = dict(base_ir)
    adjusted["steps"] = adjusted_steps
    adjusted["totalDurationSec"] = sum(int(step["durationSec"]) for step in adjusted_steps)
    adjusted["name"] = f"Manual override: {base_ir.get('name', 'Workout')}"
    raw_adjustment = base_ir.get("adjustment")
    adjustment = dict(raw_adjustment) if isinstance(raw_adjustment, dict) else {}
    adjustment["manualOverride"] = {
        "durationScalePct": duration_scale_pct or 100,
        "intensityScalePct": intensity_scale_pct or 100,
        "basisTotalDurationSec": base_ir.get("totalDurationSec"),
    }
    adjustment["changed"] = True
    adjusted["adjustment"] = adjustment
    adjusted["origin"] = "manual_override"
    return adjusted


class ExecutableCoachingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        intervals_client: IntervalsEventClient | None = None,
        garmin_client: GarminWorkoutClient | None = None,
    ) -> None:
        self.session = session
        self.rail = WorkoutDeliveryService(session, intervals_client=intervals_client)
        # Outdoor rides deliver to Garmin, not Zwift (Batch 78). The client is lazy —
        # built only when the window actually contains an outdoor workout — so the
        # indoor-only path never logs into Garmin.
        self.garmin_delivery = GarminWorkoutDeliveryService(session, garmin_client=garmin_client)

    async def regenerate_for_verdict(
        self,
        player: Profile,
        subject_date: date,
        *,
        analysis: Analysis,
        commit: bool = True,
    ) -> list[WorkoutDeliveryProposal]:
        """Propose an adjusted workout when the morning verdict is Amber or Red.

        Idempotent per planned workout (id + version) and per verdict — a second
        run is a no-op because the audit row guards against a duplicate proposal.
        Amber regenerates an adjusted session; Red substitutes an easy recovery
        spin (the ``red_substitution`` transform). Both are only *proposed* — never
        auto-approved — so a human still approves before anything is pushed, and
        the Red-never-VO2 guarantee is additionally enforced at the push gate
        (``auto_push_due``).

        Batch 173.1: a ride is skipped only when Mark has *deliberately acted on it
        today* (``_deliberately_acted``). A ride the plan pre-delivered to Zwift by
        push-on-plan-set (Decision #99) is **not** "acted on", so it still receives a
        proposed morning adjustment — the fix for the adjustment that used to appear
        only at the 11:00 backstop. This guard lives here so the check-in and the
        backstop apply the same rule.
        """
        verdict = self._verdict_status(analysis)
        if verdict not in {"Amber", "Red"}:
            return []

        created: list[WorkoutDeliveryProposal] = []
        for workout in await self._deliverable_bike_workouts(player.id, subject_date):
            tag = _regen_tag(workout, verdict)
            if await self._already_recorded(player.id, AUDIT_TYPE_PROPOSED, tag, subject_date):
                continue
            if await self._deliberately_acted(player.id, workout):
                continue
            try:
                ftp_watts = await self.rail._ftp_watts(player.id)
                base_ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
            except HTTPException:
                continue  # malformed/non-deliverable workout — skip safely
            adjusted = adjust_ir_for_verdict(
                base_ir,
                verdict,
                companion_session=await self._companion_session(player.id, workout),
            )
            proposal = await self.rail.propose_from_ir(
                player=player, workout=workout, ir=adjusted, commit=False
            )
            self._record_delivery_audit(
                player,
                proposal,
                analysis_type=AUDIT_TYPE_PROPOSED,
                tag=tag,
                subject_date=subject_date,
                verdict=verdict,
                summary=f"{verdict} regeneration proposed for {workout.title}.",
            )
            created.append(proposal)

        if commit:
            await self.session.commit()
        return created

    async def propose_chronic_deload(
        self,
        player: Profile,
        subject_date: date,
        *,
        analysis: Analysis,
        commit: bool = True,
    ) -> list[WorkoutDeliveryProposal]:
        """Queue persistent lighter proposals across the next seven days.

        The trigger is already frozen in the deterministic morning packet. This
        method only translates it into delivery proposals; it never changes the
        analysis verdict. Existing pending or acted-on coach adjustments win, so
        an acute Amber/Red regeneration is never overwritten. Audit tags make the
        pass idempotent while an ignored proposal remains visible on its workout.
        When the current packet withdraws or replaces the deload signal, pending
        chronic-origin offers expire with an audit row. Approved/failed/pushed
        sessions are decisions already made and are never retracted here.
        """

        packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
        verdict_packet = packet.get("verdict")
        action = verdict_packet.get("chronicAction") if isinstance(verdict_packet, dict) else None
        if not isinstance(action, dict):
            return []

        active_deload = action.get("triggered") is True and action.get("kind") == "deload_proposal"
        if not active_deload:
            reason = (
                "chronic_action_cleared"
                if action.get("triggered") is not True
                else "chronic_action_changed"
            )
            await self._expire_pending_chronic_deloads(
                player,
                subject_date=subject_date,
                reason=reason,
            )
            if commit:
                await self.session.commit()
            return []

        end_date = subject_date + timedelta(days=CHRONIC_DELOAD_WINDOW_DAYS - 1)
        created: list[WorkoutDeliveryProposal] = []
        workouts = await self._active_bike_workouts_in_range(player.id, subject_date, end_date)
        for workout in workouts:
            if workout.status == WORKOUT_STATUS_COMPLETED:
                continue
            tag = _chronic_deload_tag(workout)
            if await self._already_recorded(
                player.id, AUDIT_TYPE_PROPOSED, tag, workout.workout_date
            ):
                continue
            if await self._pending_adjustment(player.id, workout) is not None:
                continue
            latest = await self._latest_proposal_for_workout(player.id, workout.id)
            latest_ir = (
                latest.structured_workout_ir
                if latest is not None and isinstance(latest.structured_workout_ir, dict)
                else {}
            )
            latest_adjustment = latest_ir.get("adjustment")
            if (
                latest is not None
                and latest.status != STATUS_PROPOSED
                and isinstance(latest_adjustment, dict)
                and latest_adjustment.get("changed") is True
            ):
                continue
            try:
                ftp_watts = await self.rail._ftp_watts(player.id)
                base_ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
            except HTTPException:
                continue
            adjusted = adjust_ir_for_chronic_deload(base_ir, action)
            proposal = await self.rail.propose_from_ir(
                player=player, workout=workout, ir=adjusted, commit=False
            )
            self._record_delivery_audit(
                player,
                proposal,
                analysis_type=AUDIT_TYPE_PROPOSED,
                tag=tag,
                subject_date=workout.workout_date,
                verdict=None,
                summary=(
                    f"Seven-day chronic deload proposed for {workout.title}; "
                    "the daily verdict is unchanged."
                ),
            )
            created.append(proposal)

        if commit:
            await self.session.commit()
        return created

    async def _expire_pending_chronic_deloads(
        self,
        player: Profile,
        *,
        subject_date: date,
        reason: str,
    ) -> list[WorkoutDeliveryProposal]:
        """Expire future undecided offers whose chronic evidence no longer holds.

        ``status='proposed'`` and no event id is the durable definition of an
        undecided offer. Any approved, failed, or pushed proposal stays untouched,
        as does an inconsistent row that already points at a cloud event.
        """

        pending = (
            (
                await self.session.execute(
                    select(WorkoutDeliveryProposal)
                    .where(
                        WorkoutDeliveryProposal.user_id == player.id,
                        WorkoutDeliveryProposal.status == STATUS_PROPOSED,
                        WorkoutDeliveryProposal.workout_date >= subject_date,
                    )
                    .order_by(WorkoutDeliveryProposal.workout_date.asc())
                )
            )
            .scalars()
            .all()
        )
        expired: list[WorkoutDeliveryProposal] = []
        for proposal in pending:
            ir = (
                proposal.structured_workout_ir
                if isinstance(proposal.structured_workout_ir, dict)
                else {}
            )
            if ir.get("origin") != "chronic_deload" or proposal.intervals_event_id is not None:
                continue
            tag = _chronic_deload_expired_tag(proposal)
            if await self._already_recorded(
                player.id,
                AUDIT_TYPE_PROPOSAL_EXPIRED,
                tag,
                proposal.workout_date,
            ):
                continue
            proposal.status = STATUS_DELETED
            proposal.last_error = None
            self._record_delivery_audit(
                player,
                proposal,
                analysis_type=AUDIT_TYPE_PROPOSAL_EXPIRED,
                tag=tag,
                subject_date=proposal.workout_date,
                verdict=None,
                reason=reason,
                summary=(
                    f"Expired undecided chronic-deload proposal for "
                    f"{proposal.workout_date.isoformat()}: the current morning packet "
                    "no longer supports that deload."
                ),
            )
            expired.append(proposal)

        if expired:
            await self.session.flush()
            log.info(
                "expired chronic deload proposals",
                profile_id=str(player.id),
                subject_date=subject_date.isoformat(),
                reason=reason,
                proposal_count=len(expired),
            )
        return expired

    async def auto_push_due(
        self,
        player: Profile,
        *,
        now_utc: datetime | None = None,
        lead_days: int = DEFAULT_LEAD_DAYS,
        commit: bool = True,
    ) -> list[WorkoutDeliveryProposal]:
        """Push approved-but-unpushed proposals due within ``lead_days``.

        Honours propose → approve → push (Decision #29): only proposals a human
        already approved are eligible. Each push is isolated so one delivery
        failure (e.g. a missing intervals.icu key → 503) cannot block the rest.

        Safety gate (Decision #61): a proposal carrying VO2 intensity is never
        pushed on a day whose morning verdict is Red — even if it was approved
        earlier — so the Red-never-VO2 guarantee holds at the delivery boundary,
        not only inside the regeneration transform. A blocked push is audited.
        """
        window_end = _local_today(player.timezone, now_utc) + timedelta(days=max(0, lead_days))
        pushed: list[WorkoutDeliveryProposal] = []
        for proposal in await self._approved_unpushed(player.id, window_end):
            verdict = await self._morning_verdict_for(player.id, proposal.workout_date)
            if blocks_red_vo2(verdict, proposal.structured_workout_ir):
                await self._record_block_if_new(player, proposal)
                log.info(
                    "auto-push blocked by red verdict",
                    profile_id=str(player.id),
                    proposal_id=str(proposal.id),
                    workout_date=proposal.workout_date.isoformat(),
                )
                continue
            try:
                result = await self.rail.push(player=player, proposal_id=proposal.id)
            except HTTPException:
                continue
            tag = _push_tag(result)
            if not await self._already_recorded(
                player.id, AUDIT_TYPE_PUSHED, tag, result.workout_date
            ):
                self._record_delivery_audit(
                    player,
                    result,
                    analysis_type=AUDIT_TYPE_PUSHED,
                    tag=tag,
                    subject_date=result.workout_date,
                    verdict=_proposal_verdict(result),
                    summary=f"Auto-pushed approved workout for {result.workout_date.isoformat()}.",
                )
            pushed.append(result)

        if commit:
            await self.session.commit()
        return pushed

    async def send_today(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
        duration_scale_pct: int | None = None,
        intensity_scale_pct: int | None = None,
        now_utc: datetime | None = None,
    ) -> WorkoutDeliveryProposal:
        """Approve and immediately push today's bike workout.

        This is the Batch 25 same-day path. It keeps the existing proposal model
        and approval gate, but collapses approve -> push into one explicit user
        action from Home. Manual overrides create a fresh proposal so the exact IR
        sent to intervals.icu remains inspectable.
        """
        workout = await self.rail._planned_workout(player.id, planned_workout_id)
        today = _local_today(player.timezone, now_utc)
        if workout.workout_date != today:
            raise HTTPException(
                status_code=409,
                detail="Only today's workout can be sent same-day from Home",
            )

        override_requested = duration_scale_pct is not None or intensity_scale_pct is not None
        proposal = await self._latest_proposal_for_workout(player.id, planned_workout_id)
        if proposal and proposal.status == STATUS_PUSHED and not override_requested:
            return proposal
        if proposal and proposal.status == STATUS_PUSHED and override_requested:
            raise HTTPException(
                status_code=409,
                detail="This workout has already been sent to Zwift",
            )

        verdict = await self._morning_verdict_for(player.id, workout.workout_date)
        if override_requested or proposal is None:
            ftp_watts = await self.rail._ftp_watts(player.id)
            base_ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
            ir = adjust_ir_for_verdict(
                base_ir,
                verdict,
                companion_session=await self._companion_session(player.id, workout),
            )
            if override_requested:
                ir = apply_manual_override_to_ir(
                    ir,
                    duration_scale_pct=duration_scale_pct,
                    intensity_scale_pct=intensity_scale_pct,
                )
            proposal = await self.rail.propose_from_ir(
                player=player, workout=workout, ir=ir, commit=False
            )
            self._record_delivery_audit(
                player,
                proposal,
                analysis_type=AUDIT_TYPE_PROPOSED,
                tag=_same_day_propose_tag(proposal, override=override_requested),
                subject_date=workout.workout_date,
                verdict=verdict,
                summary=(
                    "Manual override prepared for same-day Zwift delivery."
                    if override_requested
                    else "Workout prepared for same-day Zwift delivery."
                ),
            )

        if override_requested:
            proposal.intervals_payload = build_intervals_payload(proposal.structured_workout_ir)
            proposal.zwo_xml = build_zwo_xml(proposal.structured_workout_ir)

        if proposal.status == STATUS_PROPOSED:
            proposal.status = STATUS_APPROVED
            proposal.approved_at_utc = _utcnow()
            proposal.approved_by_profile_id = player.id
            proposal.last_error = None
            await self.session.flush()
        elif proposal.status not in {STATUS_APPROVED, STATUS_FAILED}:
            raise HTTPException(
                status_code=409,
                detail=f"Proposal cannot be sent from status {proposal.status}",
            )

        if blocks_red_vo2(verdict, proposal.structured_workout_ir):
            await self._record_block_if_new(player, proposal)
            await self.session.commit()
            raise HTTPException(
                status_code=409,
                detail="Red verdict blocks VO2 delivery to Zwift",
            )

        await self.session.commit()
        pushed = await self.rail.push(player=player, proposal_id=proposal.id)
        tag = _same_day_push_tag(pushed)
        if not await self._already_recorded(player.id, AUDIT_TYPE_PUSHED, tag, pushed.workout_date):
            self._record_delivery_audit(
                player,
                pushed,
                analysis_type=AUDIT_TYPE_PUSHED,
                tag=tag,
                subject_date=pushed.workout_date,
                verdict=verdict or _proposal_verdict(pushed),
                summary=f"Same-day approved workout pushed for {pushed.workout_date.isoformat()}.",
            )
            await self.session.commit()
            await self.session.refresh(pushed)
        return pushed

    async def reconcile_deliveries(
        self,
        player: Profile,
        *,
        start_date: date,
        end_date: date,
    ) -> list[WorkoutDeliveryProposal]:
        """Push-on-plan-set: ensure every active bike workout in the window has a
        live delivery matching its current content (Decision #99).

        **Indoor** rides deliver to Zwift via the intervals.icu rail; **outdoor**
        rides deliver to Garmin Connect (Batch 78, Decision #151). The baseline is
        delivered **without a per-workout approval** — as planned on Green/no read,
        or through the canonical ease on Amber/Red (Batch 243). Explicit morning
        offers remain human-approved; this default merely prevents a later plan
        reconcile from putting the harder source back on the trainer. Each workout
        is isolated so one delivery failure (e.g. a missing intervals.icu key → 503,
        or a Garmin 429) never blocks the rest, and the pass is idempotent only when
        both plan version and verdict-adjusted content match. The Zwift proposals
        are returned; outdoor Garmin delivery is a side effect recorded on its own row.
        """
        delivered: list[WorkoutDeliveryProposal] = []
        for workout in await self._active_bike_workouts_in_range(player.id, start_date, end_date):
            try:
                result = await self._deliver_one(player, workout)
            except HTTPException as exc:
                # The rail was called with commit=False: this service owns the
                # unit of work and deliberately persists only the honest failure
                # state after the cloud operation has failed.
                await self.session.commit()
                log.warning(
                    "workout_delivery_failed",
                    user_id=str(player.id),
                    planned_workout_id=str(workout.id),
                    planned_workout_version=workout.version,
                    status_code=exc.status_code,
                )
                continue
            if result is not None:
                delivered.append(result)

        outdoor = await self._active_outdoor_bike_workouts_in_range(player.id, start_date, end_date)
        if outdoor:
            ftp_watts = await self.rail._ftp_watts(player.id)
            for workout in outdoor:
                try:
                    await self.garmin_delivery.reconcile_workout(
                        player, workout, ftp_watts=ftp_watts
                    )
                except Exception:  # noqa: BLE001 - isolated; the row carries last_error (#97)
                    continue
        return delivered

    async def _deliver_one(
        self, player: Profile, workout: PlannedWorkout
    ) -> WorkoutDeliveryProposal | None:
        try:
            ftp_watts = await self.rail._ftp_watts(player.id)
        except HTTPException as exc:
            failure = await self.rail.record_failure(
                player=player,
                workout=workout,
                code="missing_ftp",
                stage="load_ftp",
                retryable=exc.status_code >= 500,
                detail=exc.detail,
            )
            log.warning(
                "workout_not_deliverable",
                user_id=str(player.id),
                planned_workout_id=str(workout.id),
                planned_workout_version=workout.version,
                failure_code="missing_ftp",
                retryable=exc.status_code >= 500,
                proposal_id=str(failure.id),
            )
            return None
        try:
            base_ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
        except HTTPException as exc:
            failure = await self.rail.record_failure(
                player=player,
                workout=workout,
                code="malformed_workout",
                stage="build_ir",
                retryable=False,
                detail=exc.detail,
            )
            log.warning(
                "workout_not_deliverable",
                user_id=str(player.id),
                planned_workout_id=str(workout.id),
                planned_workout_version=workout.version,
                failure_code="malformed_workout",
                retryable=False,
                proposal_id=str(failure.id),
            )
            return None
        verdict = await self._morning_verdict_for(player.id, workout.workout_date)
        companion = await self._companion_session(player.id, workout)
        if verdict in {"Amber", "Red"}:
            delivery_ir = adjust_ir_for_verdict(
                base_ir,
                verdict,
                companion_session=companion,
            )
        else:
            delivery_ir = dict(base_ir)
            delivery_ir["origin"] = "as_planned"
            delivery_ir["adjustment"] = {"verdict": verdict, "changed": False}

        live = await self.rail.latest_delivered_for_workout(player.id, workout.id)
        if live is None:
            live = await self.rail.latest_delivered_for_date(player.id, workout.workout_date)
        if live is not None and _proposal_content_matches_workout(live, workout, delivery_ir):
            return None  # this exact version is already on Zwift — idempotent

        if live is not None:
            # A restructure re-versioned the slot — re-sync the existing event in
            # place so Zwift never carries a stale or duplicate session.
            delivered = await self.rail.replace_event(proposal=live, ir=delivery_ir, commit=False)
            live.planned_workout_id = workout.id
            live.planned_workout_version = workout.version
            retried = await self.rail.mark_retry_delivered(
                workout=workout,
                delivered=live,
                commit=False,
            )
            if retried is not None:
                delivered = retried
            audit_type = AUDIT_TYPE_REPLACED
            summary = (
                f"Re-synced Zwift event for {workout.title} ({workout.workout_date.isoformat()})."
            )
        else:
            proposal = await self.rail.propose_from_ir(
                player=player, workout=workout, ir=delivery_ir, commit=False
            )
            delivered = await self.rail.create_event(
                proposal=proposal,
                ir=delivery_ir,
                commit=False,
            )
            audit_type = AUDIT_TYPE_DELIVERED
            summary = f"Delivered {workout.title} to Zwift for {workout.workout_date.isoformat()}."

        tag = _delivery_action_tag(delivered, audit_type)
        if not await self._already_recorded(player.id, audit_type, tag, workout.workout_date):
            self._record_delivery_audit(
                player,
                delivered,
                analysis_type=audit_type,
                tag=tag,
                subject_date=workout.workout_date,
                verdict=verdict,
                summary=summary,
            )
        await self.session.commit()
        await self.session.refresh(delivered)
        return delivered

    async def _active_bike_workouts_raw(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[PlannedWorkout]:
        return list(
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status != WORKOUT_STATUS_SKIPPED,
                        PlannedWorkout.workout_date >= start_date,
                        PlannedWorkout.workout_date <= end_date,
                    )
                    .order_by(
                        PlannedWorkout.workout_date.asc(),
                        PlannedWorkout.version.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _active_bike_workouts_in_range(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[PlannedWorkout]:
        """Active **indoor** bike workouts — including malformed bike rows.

        A known indoor shape follows ``is_indoor_bike_workout``. A row whose
        workout type says bike but whose structure is malformed must also reach
        ``_deliver_one`` so it records a durable failure instead of disappearing
        at this filter. Explicit outdoor rows remain on the Garmin rail.
        """
        workouts = await self._active_bike_workouts_raw(user_id, start_date, end_date)
        return [
            workout
            for workout in workouts
            if is_indoor_bike_workout(workout.structured_workout)
            or (
                workout.workout_type.startswith("bike_")
                and not is_outdoor_bike_workout(workout.structured_workout)
            )
        ]

    async def _active_outdoor_bike_workouts_in_range(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[PlannedWorkout]:
        """Active **outdoor** bike workouts — the Garmin delivery rail (Batch 78)."""
        workouts = await self._active_bike_workouts_raw(user_id, start_date, end_date)
        return [w for w in workouts if is_outdoor_bike_workout(w.structured_workout)]

    # ------------------------------------------------------------------
    # Today-card actions (Batch 29.3): Edit / Approve / Swap / Skip
    # ------------------------------------------------------------------

    async def edit_today(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
        duration_scale_pct: int | None = None,
        intensity_scale_pct: int | None = None,
    ) -> WorkoutDeliveryProposal:
        """Manual Edit — re-sync the live Zwift event with a manually scaled IR.

        Available in both card states. Bike-only: ``build_structured_workout_ir``
        rejects a non-bike session (422), which is correct — non-bike days carry no
        Zwift upload.
        """
        workout = await self.rail._planned_workout(player.id, planned_workout_id)
        ftp_watts = await self.rail._ftp_watts(player.id)
        base_ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
        ir = apply_manual_override_to_ir(
            base_ir,
            duration_scale_pct=duration_scale_pct,
            intensity_scale_pct=intensity_scale_pct,
        )
        delivered = await self._resync_event(player, workout, ir)
        self._record_action_audit(
            player,
            analysis_type=AUDIT_TYPE_REPLACED,
            tag=f"edit:{workout.id}:v{workout.version}",
            subject_date=workout.workout_date,
            summary=f"Manually edited {workout.title} and re-synced to Zwift.",
            planned_workout_id=workout.id,
            planned_workout_version=workout.version,
            event_id=delivered.intervals_event_id,
            status=delivered.status,
        )
        await self.session.commit()
        await self.session.refresh(delivered)
        return delivered

    async def approve_interval_edit(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
        block: EditableIntervalBlock,
    ) -> WorkoutDeliveryProposal:
        """Version the source interval block, approve it, and update Zwift.

        The source mapper preserves warm-up/cool-down/primer JSON. The resulting
        workout is a fresh ``planned_workouts`` version and the exact re-expanded
        IR is retained on a normal delivery proposal before the existing live
        intervals.icu event is replaced. Red-never-VO2 remains a hard gate.
        """
        current = await self.rail._planned_workout(player.id, planned_workout_id)
        if current.status == WORKOUT_STATUS_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail="This session is already done, so its intervals can't be edited.",
            )
        if not is_indoor_bike_workout(current.structured_workout):
            raise HTTPException(
                status_code=422,
                detail="The interval editor uploads indoor bike sessions to Zwift",
            )

        structured = apply_interval_block(
            dict(current.structured_workout or {}),
            current.intensity_target,
            block,
        )
        expanded_steps = expand_structured_steps(structured, current.intensity_target)
        verdict = await self._morning_verdict_for(player.id, current.workout_date)
        if blocks_red_vo2(verdict, {"steps": expanded_steps}):
            raise HTTPException(status_code=409, detail="Red verdict blocks VO2 delivery to Zwift")

        live = await self.rail.latest_delivered_for_workout(player.id, current.id)
        if live is None:
            live = await self.rail.latest_delivered_for_date(player.id, current.workout_date)
        current.is_active = False
        current_version = await self.session.scalar(
            select(func.max(PlannedWorkout.version)).where(
                PlannedWorkout.user_id == player.id,
                PlannedWorkout.workout_date == current.workout_date,
            )
        )
        workout = PlannedWorkout(
            user_id=player.id,
            plan_block_id=current.plan_block_id,
            workout_date=current.workout_date,
            version=(current_version or 0) + 1,
            title=current.title,
            workout_type=block_workout_type(block),
            status="planned",
            is_active=True,
            planned_duration_min=ceil(
                sum(int(step["durationSec"]) for step in expanded_steps) / 60
            ),
            intensity_target=f"{block.work.power_pct}% FTP intervals",
            structured_workout=structured,
            source="interval_editor",
        )
        self.session.add(workout)
        await self.session.flush()

        ftp_watts = await self.rail._ftp_watts(player.id)
        ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
        ir["origin"] = "interval_editor"
        ir["adjustment"] = {
            "changed": True,
            "kind": "interval_editor",
            "basisPlannedWorkoutId": str(current.id),
            "basisPlannedWorkoutVersion": current.version,
        }
        proposal = await self.rail.propose_from_ir(
            player=player,
            workout=workout,
            ir=ir,
            commit=False,
        )
        proposal = await self.rail.approve(
            player=player,
            proposal_id=proposal.id,
            commit=False,
        )

        if live is None:
            delivered = await self.rail.push(player=player, proposal_id=proposal.id)
        else:
            try:
                await self.rail.replace_event(proposal=live, ir=ir, commit=False)
            except HTTPException:
                proposal.status = STATUS_FAILED
                proposal.last_error = live.last_error
                await self.session.commit()
                await self.session.refresh(proposal)
                raise
            live.planned_workout_id = workout.id
            live.planned_workout_version = workout.version
            proposal.status = STATUS_PUSHED
            proposal.pushed_at_utc = _utcnow()
            proposal.intervals_event_id = live.intervals_event_id
            proposal.last_error = None
            await self.session.commit()
            await self.session.refresh(proposal)
            delivered = proposal

        self._record_action_audit(
            player,
            analysis_type=AUDIT_TYPE_REPLACED,
            tag=f"interval-edit:{workout.id}:v{workout.version}",
            subject_date=workout.workout_date,
            summary=f"Approved the interval edit for {workout.title} and uploaded it.",
            planned_workout_id=workout.id,
            planned_workout_version=workout.version,
            event_id=delivered.intervals_event_id,
            status=delivered.status,
            verdict=verdict,
        )
        await self.session.commit()
        await self.session.refresh(delivered)
        return delivered

    async def approve_adjustment(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
    ) -> WorkoutDeliveryProposal:
        """Approve & upload (changes state) — replace the live Zwift event with the
        pending coach-adjusted IR. Red-never-VO2 still gates this (Decision #30/#61):
        Ignore can keep the planned session, but Approve can never push a VO2 set on
        a Red day.
        """
        workout = await self.rail._planned_workout(player.id, planned_workout_id)
        pending = await self._pending_adjustment(player.id, workout)
        if pending is None:
            raise HTTPException(status_code=409, detail="No pending coach adjustment to approve")
        verdict = await self._morning_verdict_for(player.id, workout.workout_date)
        ir = pending.structured_workout_ir
        if blocks_red_vo2(verdict, ir):
            await self._record_block_if_new(player, pending)
            await self.session.commit()
            raise HTTPException(status_code=409, detail="Red verdict blocks VO2 delivery to Zwift")
        delivered = await self._resync_event(player, workout, ir)
        await self._seed_adjustment_adherence(
            player_id=player.id,
            workout=workout,
            ir=ir,
        )
        # Consume the pending proposal so the card returns to the no-changes state.
        pending.approved_at_utc = _utcnow()
        pending.approved_by_profile_id = player.id
        if pending.id != delivered.id:
            pending.status = STATUS_PUSHED
            pending.pushed_at_utc = _utcnow()
        self._record_action_audit(
            player,
            analysis_type=AUDIT_TYPE_PUSHED,
            tag=f"approve:{workout.id}:v{workout.version}",
            subject_date=workout.workout_date,
            summary=f"Approved the coach adjustment for {workout.title} and uploaded it.",
            planned_workout_id=workout.id,
            planned_workout_version=workout.version,
            event_id=delivered.intervals_event_id,
            status=delivered.status,
            verdict=verdict,
        )
        await self.session.commit()
        await self.session.refresh(delivered)
        return delivered

    async def _seed_adjustment_adherence(
        self,
        *,
        player_id: uuid.UUID,
        workout: PlannedWorkout,
        ir: dict[str, Any],
    ) -> None:
        """Batch 69: approving an adjusted ride pre-fills adherence once."""
        entry = await self.session.scalar(
            select(ManualEntry).where(
                ManualEntry.user_id == player_id,
                ManualEntry.entry_date == workout.workout_date,
                ManualEntry.planned_workout_id == workout.id,
            )
        )
        if entry is None:
            entry = ManualEntry(
                user_id=player_id,
                planned_workout_id=workout.id,
                entry_date=workout.workout_date,
                entry_at_utc=_utcnow(),
            )
            self.session.add(entry)

        actual = dict(entry.actual_workout_json or {})
        actual.setdefault("type", _accepted_adjustment_type(ir))
        actual.setdefault("intensity", _accepted_adjustment_target(ir))
        actual.setdefault("changeSummary", _accepted_adjustment_summary(ir))
        actual.setdefault("source", "accepted_adjustment")

        entry.entry_at_utc = _utcnow()
        entry.planned_workout_version = workout.version
        if entry.adherence_status in {None, "modified"}:
            entry.adherence_status = "modified"
        entry.actual_workout_json = actual
        await self.session.flush()

    async def skip_workout(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
    ) -> PlannedWorkout:
        """Skip — a ``planned → skipped`` status transition (no migration; the
        column is already free text) plus a Zwift delete. No reshuffle — that stays
        the separate restructure tool (Decision #99). Honest on failure (#97): the
        status only flips once the Zwift delete succeeds.
        """
        workout = await self.rail._planned_workout(player.id, planned_workout_id)
        if workout.status == WORKOUT_STATUS_COMPLETED or await self._has_done_adherence(
            player.id, workout
        ):
            raise HTTPException(
                status_code=409,
                detail="This session is already done, so it can't be skipped.",
            )
        live = await self.rail.latest_delivered_for_workout(player.id, workout.id)
        if live is None:
            live = await self.rail.latest_delivered_for_date(player.id, workout.workout_date)
        event_id = live.intervals_event_id if live is not None else None
        if live is not None:
            await self.rail.delete_event(proposal=live, commit=False)
        workout.status = WORKOUT_STATUS_SKIPPED
        self._record_action_audit(
            player,
            analysis_type=AUDIT_TYPE_SKIPPED,
            tag=f"skip:{workout.id}:v{workout.version}",
            subject_date=workout.workout_date,
            summary=f"Skipped {workout.title} ({workout.workout_date.isoformat()}).",
            planned_workout_id=workout.id,
            planned_workout_version=workout.version,
            event_id=event_id,
            status=WORKOUT_STATUS_SKIPPED,
        )
        await self.session.commit()
        await self.session.refresh(workout)
        return workout

    async def remove_workout(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
    ) -> PlannedWorkout:
        """Remove a user-added workout outright: deactivate the row so it leaves
        Home/Week immediately, and delete any live Zwift event without creating
        skipped-adherence noise on a coach-planned session."""
        workout = await self.rail._planned_workout(player.id, planned_workout_id)
        if workout.source != "plan_action_add":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only user-added workouts can be removed. Planned sessions should be skipped."
                ),
            )

        live = await self.rail.latest_delivered_for_workout(player.id, workout.id)
        if live is None:
            live = await self.rail.latest_delivered_for_date(player.id, workout.workout_date)
        event_id = live.intervals_event_id if live is not None else None
        if live is not None:
            await self.rail.delete_event(proposal=live, commit=False)

        workout.is_active = False
        self._record_action_audit(
            player,
            analysis_type=AUDIT_TYPE_REMOVED,
            tag=f"remove:{workout.id}:v{workout.version}",
            subject_date=workout.workout_date,
            summary=f"Removed added workout {workout.title} ({workout.workout_date.isoformat()}).",
            planned_workout_id=workout.id,
            planned_workout_version=workout.version,
            event_id=event_id,
            status="removed",
        )
        await self.session.commit()
        await self.session.refresh(workout)
        return workout

    async def swap_day(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
        target_date: date,
    ) -> PlannedWorkout:
        """Swap day = unified move-or-swap (Decision #99): an empty target day
        **moves** the session there; an occupied one **swaps** the two. Re-slots the
        plan by versioning (sidesteps the (date, version) unique constraint and
        keeps history) and moves the affected Zwift events in place.
        """
        workout = await self.rail._planned_workout(player.id, planned_workout_id)
        source_date = workout.workout_date
        if target_date == source_date:
            raise HTTPException(status_code=400, detail="Pick a different day to swap to")

        # Scope swap-target detection to the source's category (Batch 65): moving a
        # ride swaps only with the target day's ride, so a same-day strength/flexibility
        # session is never dragged along, and swapping two ride days leaves both days'
        # strength in place.
        source_category = category_for_workout_type(workout.workout_type)
        target_workout = await self._active_workout_on(
            player.id, target_date, category=source_category
        )
        # A completed session can't be re-slotted in either direction (Batch 60):
        # it already happened, so moving the source — or swapping it onto a day
        # that already holds a completed session — would rewrite history.
        if workout.status == WORKOUT_STATUS_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail="This session is already done, so it can't be moved.",
            )
        if target_workout is not None and target_workout.status == WORKOUT_STATUS_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail="That day already has a completed session, so pick another day.",
            )
        source_live = await self.rail.latest_delivered_for_workout(player.id, workout.id)
        if source_live is None:
            source_live = await self.rail.latest_delivered_for_date(player.id, source_date)
        target_live = (
            await self.rail.latest_delivered_for_workout(player.id, target_workout.id)
            if target_workout is not None
            else None
        )
        if target_workout is not None and target_live is None:
            target_live = await self.rail.latest_delivered_for_date(player.id, target_date)

        # Move the Zwift events first so a failed cloud move aborts before any local
        # re-slot (#97 honesty): the plan never diverges from the calendar silently.
        if source_live is not None:
            await self.rail.move_event(proposal=source_live, new_date=target_date, commit=False)
        if target_workout is not None and target_live is not None:
            await self.rail.move_event(proposal=target_live, new_date=source_date, commit=False)

        source_content = self._content_snapshot(workout)
        target_content = self._content_snapshot(target_workout) if target_workout else None
        # Batch 213: `_active_workout_on` deliberately excludes a skipped row when
        # picking a swap partner (there's nothing to swap with), but that must not
        # leave the skipped row as a second active row once its date gets a
        # reslotted replacement. Deactivate every same-category active occupant on
        # both dates — not just the ones chosen as swap partners — so a stale
        # skipped row can never survive a swap through this date again.
        for stale in await self._active_occupants_on(
            player.id, source_date, category=source_category
        ):
            stale.is_active = False
        for stale in await self._active_occupants_on(
            player.id, target_date, category=source_category
        ):
            stale.is_active = False
        await self.session.flush()

        new_source = await self._reslot(player, source_content, target_date)
        # Re-point the moved events at the freshly versioned rows so a later
        # reconcile sees them as already-matching (idempotent) rather than
        # dangling at the now-inactive source/target rows.
        if source_live is not None:
            source_live.planned_workout_id = new_source.id
            source_live.planned_workout_version = new_source.version
            source_ir = dict(source_live.structured_workout_ir or {})
            source_ir["plannedWorkoutId"] = str(new_source.id)
            source_ir["plannedWorkoutVersion"] = new_source.version
            source_live.structured_workout_ir = source_ir
        if target_content is not None:
            new_target = await self._reslot(player, target_content, source_date)
            if target_live is not None:
                target_live.planned_workout_id = new_target.id
                target_live.planned_workout_version = new_target.version
                target_ir = dict(target_live.structured_workout_ir or {})
                target_ir["plannedWorkoutId"] = str(new_target.id)
                target_ir["plannedWorkoutVersion"] = new_target.version
                target_live.structured_workout_ir = target_ir

        summary = (
            f"Moved {workout.title} from {source_date.isoformat()} to {target_date.isoformat()}."
            if target_content is None
            else f"Swapped {source_date.isoformat()} and {target_date.isoformat()}."
        )
        self._record_action_audit(
            player,
            analysis_type=AUDIT_TYPE_MOVED,
            tag=f"swap:{planned_workout_id}:{target_date.isoformat()}",
            subject_date=source_date,
            summary=summary,
            planned_workout_id=new_source.id,
            planned_workout_version=new_source.version,
            event_id=source_live.intervals_event_id if source_live is not None else None,
            status="moved",
        )
        await self.session.commit()
        await self.session.refresh(new_source)
        return new_source

    async def _resync_event(
        self, player: Profile, workout: PlannedWorkout, ir: dict[str, Any]
    ) -> WorkoutDeliveryProposal:
        """Replace this date's live Zwift event with ``ir`` (or create one if the
        slot has none yet), re-pointing the carrying proposal at ``workout``."""
        live = await self.rail.latest_delivered_for_workout(player.id, workout.id)
        if live is None:
            live = await self.rail.latest_delivered_for_date(player.id, workout.workout_date)
        if live is None:
            proposal = await self.rail.propose_from_ir(
                player=player, workout=workout, ir=ir, commit=False
            )
            try:
                return await self.rail.create_event(proposal=proposal, ir=ir, commit=False)
            except HTTPException:
                await self.session.commit()
                raise
        try:
            delivered = await self.rail.replace_event(proposal=live, ir=ir, commit=False)
        except HTTPException:
            await self.session.commit()
            raise
        live.planned_workout_id = workout.id
        live.planned_workout_version = workout.version
        return delivered

    async def _pending_adjustment(
        self, user_id: uuid.UUID, workout: PlannedWorkout
    ) -> WorkoutDeliveryProposal | None:
        """The un-acted coach adjustment for today's workout: the latest proposed
        proposal whose IR is flagged ``adjustment.changed`` (Amber/Red regen)."""
        proposals = (
            (
                await self.session.execute(
                    select(WorkoutDeliveryProposal)
                    .where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.planned_workout_id == workout.id,
                        WorkoutDeliveryProposal.status == STATUS_PROPOSED,
                    )
                    .order_by(WorkoutDeliveryProposal.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for proposal in proposals:
            ir = (
                proposal.structured_workout_ir
                if isinstance(proposal.structured_workout_ir, dict)
                else {}
            )
            adjustment = ir.get("adjustment")
            if isinstance(adjustment, dict) and adjustment.get("changed"):
                return proposal
        return None

    async def _active_occupants_on(
        self, user_id: uuid.UUID, workout_date: date, *, category: str | None = None
    ) -> list[PlannedWorkout]:
        """Every ``is_active`` row on a date, highest version first — including a
        ``skipped`` one (Batch 213).

        This is the superset :meth:`_active_workout_on` filters down when picking
        a swap partner. Use this one when the question is "what must be
        deactivated here", not "what can I swap with" — those are different
        questions, and conflating them is what let a skipped row survive a swap
        onto its date as a second active row.
        """
        candidates = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == workout_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                    .order_by(PlannedWorkout.version.desc())
                )
            )
            .scalars()
            .all()
        )
        if category is None:
            return list(candidates)
        return [w for w in candidates if category_for_workout_type(w.workout_type) == category]

    async def _active_workout_on(
        self, user_id: uuid.UUID, workout_date: date, *, category: str | None = None
    ) -> PlannedWorkout | None:
        """The active (non-skipped) workout on a date, highest version first.

        When ``category`` is given only a workout of that day-category matches
        (Batch 65) — so a multi-workout day (e.g. a split Saturday's ride +
        Bodyweight) resolves to the same-category session rather than an arbitrary
        ``.limit(1)`` pick. With no category it keeps the prior behaviour.
        """
        for workout in await self._active_occupants_on(user_id, workout_date, category=category):
            if workout.status != WORKOUT_STATUS_SKIPPED:
                return workout
        return None

    async def _has_done_adherence(self, user_id: uuid.UUID, workout: PlannedWorkout) -> bool:
        entry = await self.session.scalar(
            select(ManualEntry)
            .where(
                ManualEntry.user_id == user_id,
                ManualEntry.entry_date == workout.workout_date,
                ManualEntry.planned_workout_id == workout.id,
                ManualEntry.activity_id.is_(None),
            )
            .order_by(ManualEntry.entry_at_utc.desc(), ManualEntry.created_at.desc())
            .limit(1)
        )
        if entry is None:
            return False
        return (entry.adherence_status or "").strip().lower() in DONE_ADHERENCE_STATUSES

    def _content_snapshot(self, workout: PlannedWorkout) -> dict[str, Any]:
        return {
            "plan_block_id": workout.plan_block_id,
            "title": workout.title,
            "workout_type": workout.workout_type,
            "status": workout.status,
            "planned_duration_min": workout.planned_duration_min,
            "intensity_target": workout.intensity_target,
            "structured_workout": dict(workout.structured_workout or {}),
        }

    async def _reslot(
        self, player: Profile, content: dict[str, Any], target_date: date
    ) -> PlannedWorkout:
        current_version = await self.session.scalar(
            select(func.max(PlannedWorkout.version)).where(
                PlannedWorkout.user_id == player.id,
                PlannedWorkout.workout_date == target_date,
            )
        )
        next_version = (current_version or 0) + 1
        workout = PlannedWorkout(
            user_id=player.id,
            plan_block_id=content["plan_block_id"],
            workout_date=target_date,
            version=next_version,
            title=content["title"],
            workout_type=content["workout_type"],
            status=content["status"],
            is_active=True,
            planned_duration_min=content["planned_duration_min"],
            intensity_target=content["intensity_target"],
            structured_workout=content["structured_workout"],
            source="today_card_swap",
        )
        self.session.add(workout)
        await self.session.flush()
        return workout

    def _record_action_audit(
        self,
        player: Profile,
        *,
        analysis_type: str,
        tag: str,
        subject_date: date,
        summary: str,
        planned_workout_id: uuid.UUID | None,
        planned_workout_version: int | None,
        event_id: str | None,
        status: str,
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
                context_packet={
                    "tag": tag,
                    "plannedWorkoutId": (str(planned_workout_id) if planned_workout_id else None),
                    "plannedWorkoutVersion": planned_workout_version,
                    "intervalsEventId": event_id,
                    "status": status,
                },
                output_markdown=summary,
                raw_response={},
            )
        )

    def _record_delivery_audit(
        self,
        player: Profile,
        proposal: WorkoutDeliveryProposal,
        *,
        analysis_type: str,
        tag: str,
        subject_date: date,
        verdict: str | None,
        summary: str,
        reason: str | None = None,
    ) -> None:
        ir = (
            proposal.structured_workout_ir
            if isinstance(proposal.structured_workout_ir, dict)
            else {}
        )
        context_packet = {
            "tag": tag,
            "proposalId": str(proposal.id),
            "plannedWorkoutId": (
                str(proposal.planned_workout_id) if proposal.planned_workout_id else None
            ),
            "plannedWorkoutVersion": proposal.planned_workout_version,
            "workoutDate": proposal.workout_date.isoformat(),
            "status": proposal.status,
            "provider": proposal.provider,
            "origin": ir.get("origin"),
            "adjustment": ir.get("adjustment"),
            "intervalsEventId": proposal.intervals_event_id,
        }
        if reason is not None:
            context_packet["reason"] = reason
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
                output_markdown=summary,
                raw_response={},
            )
        )

    def _verdict_status(self, analysis: Analysis) -> str | None:
        status = _normalize_verdict(analysis.verdict)
        if status is not None:
            return status
        packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
        verdict = packet.get("verdict")
        if isinstance(verdict, dict):
            return _normalize_verdict(verdict.get("status"))
        return None

    async def _active_workouts_on(
        self, user_id: uuid.UUID, subject_date: date
    ) -> list[PlannedWorkout]:
        return list(
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

    async def _deliverable_bike_workouts(
        self, user_id: uuid.UUID, subject_date: date
    ) -> list[PlannedWorkout]:
        return [
            workout
            for workout in await self._active_workouts_on(user_id, subject_date)
            if isinstance(workout.structured_workout, dict)
            and workout.structured_workout.get("format") == "bike"
        ]

    async def _companion_session(self, user_id: uuid.UUID, workout: PlannedWorkout) -> bool:
        """Does the day already hold another session whose load counts (Batch 215.5)?

        The coach's own caveat to Mark: with a bodyweight session alongside a
        45-minute Zone 2, the *total* is what matters. When one is scheduled, Red
        withdraws its endurance allowance and reverts to the recovery substitution.
        """
        others = await self._active_workouts_on(user_id, workout.workout_date)
        return companion_session_present(other.status for other in others if other.id != workout.id)

    async def _approved_unpushed(
        self, user_id: uuid.UUID, window_end: date
    ) -> list[WorkoutDeliveryProposal]:
        rows = (
            (
                await self.session.execute(
                    select(WorkoutDeliveryProposal)
                    .where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.status == STATUS_APPROVED,
                        WorkoutDeliveryProposal.pushed_at_utc.is_(None),
                        WorkoutDeliveryProposal.workout_date <= window_end,
                    )
                    .order_by(WorkoutDeliveryProposal.workout_date.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _latest_proposal_for_workout(
        self, user_id: uuid.UUID, planned_workout_id: uuid.UUID
    ) -> WorkoutDeliveryProposal | None:
        proposal: WorkoutDeliveryProposal | None = await self.session.scalar(
            select(WorkoutDeliveryProposal)
            .where(
                WorkoutDeliveryProposal.user_id == user_id,
                WorkoutDeliveryProposal.planned_workout_id == planned_workout_id,
            )
            .order_by(WorkoutDeliveryProposal.created_at.desc())
            .limit(1)
        )
        return proposal

    async def _deliberately_acted(self, user_id: uuid.UUID, workout: PlannedWorkout) -> bool:
        """True when Mark has *deliberately* acted on today's ride (Batch 173.1).

        "Acted on" means he approved the coach adjustment, sent it same-day, or
        hand-edited the session — signals that carry either an explicit approver
        (``approved_by_profile_id``, set only by ``approve``/``send_today``/the
        interval-edit approve, never by push-on-plan-set) or a delivered change
        (``status == pushed`` with an ``adjustment.changed`` IR, e.g. a manual
        ``edit_today``). The push-on-plan-set baseline (``origin=as_planned``,
        ``changed=False``, no approver) is deliberately *not* "acted on", so a
        pre-delivered ride still receives a proposed morning adjustment; a ride Mark
        acted on is never silently re-adjusted (Decision #29).
        """
        proposals = (
            (
                await self.session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.planned_workout_id == workout.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for proposal in proposals:
            if proposal.approved_by_profile_id is not None:
                return True
            ir = (
                proposal.structured_workout_ir
                if isinstance(proposal.structured_workout_ir, dict)
                else {}
            )
            adjustment = ir.get("adjustment")
            if (
                proposal.status == STATUS_PUSHED
                and isinstance(adjustment, dict)
                and adjustment.get("changed") is True
            ):
                return True
        return False

    async def _already_recorded(
        self,
        user_id: uuid.UUID,
        analysis_type: str,
        tag: str,
        subject_date: date,
    ) -> bool:
        rows = (
            (
                await self.session.execute(
                    select(Analysis).where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == analysis_type,
                        Analysis.subject_date == subject_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        return any(
            isinstance(row.context_packet, dict) and row.context_packet.get("tag") == tag
            for row in rows
        )

    async def _morning_verdict_for(self, user_id: uuid.UUID, subject_date: date) -> str | None:
        """The latest stored morning verdict for a date, normalised (or None)."""
        analysis = await self.session.scalar(
            select(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.analysis_type == ANALYSIS_TYPE_MORNING,
                Analysis.subject_date == subject_date,
            )
            .order_by(Analysis.generated_at_utc.desc(), Analysis.created_at.desc())
            .limit(1)
        )
        return _normalize_verdict(analysis.verdict) if analysis else None

    async def _record_block_if_new(
        self, player: Profile, proposal: WorkoutDeliveryProposal
    ) -> None:
        """Audit a blocked push once per proposal (idempotent across the day's sweeps)."""
        tag = _block_tag(proposal)
        if await self._already_recorded(
            player.id, AUDIT_TYPE_PUSH_BLOCKED, tag, proposal.workout_date
        ):
            return
        self._record_delivery_audit(
            player,
            proposal,
            analysis_type=AUDIT_TYPE_PUSH_BLOCKED,
            tag=tag,
            subject_date=proposal.workout_date,
            verdict="Red",
            summary=(
                f"Auto-push blocked: Red verdict on {proposal.workout_date.isoformat()} "
                "— VO2 session not delivered."
            ),
        )


def _delivery_action_tag(proposal: WorkoutDeliveryProposal, action: str) -> str:
    """Idempotency tag for a push-on-plan-set delivery/action, keyed to the
    planned workout id + version so each version is delivered (or mutated) once."""
    return f"{action}:{proposal.planned_workout_id}:v{proposal.planned_workout_version}"


def _regen_tag(workout: PlannedWorkout, verdict: str) -> str:
    return f"{verdict.lower()}-regen:{workout.id}:v{workout.version}"


def _chronic_deload_tag(workout: PlannedWorkout) -> str:
    return f"chronic-deload:{workout.id}:v{workout.version}"


def _chronic_deload_expired_tag(proposal: WorkoutDeliveryProposal) -> str:
    return f"chronic-deload-expired:{proposal.id}"


def _push_tag(proposal: WorkoutDeliveryProposal) -> str:
    return f"auto-push:{proposal.id}"


def _same_day_propose_tag(proposal: WorkoutDeliveryProposal, *, override: bool) -> str:
    prefix = "same-day-override" if override else "same-day-propose"
    return f"{prefix}:{proposal.id}"


def _same_day_push_tag(proposal: WorkoutDeliveryProposal) -> str:
    return f"same-day-push:{proposal.id}"


def _block_tag(proposal: WorkoutDeliveryProposal) -> str:
    return f"push-blocked:{proposal.id}"


def _proposal_verdict(proposal: WorkoutDeliveryProposal) -> str | None:
    ir = proposal.structured_workout_ir if isinstance(proposal.structured_workout_ir, dict) else {}
    adjustment = ir.get("adjustment")
    if isinstance(adjustment, dict):
        return _normalize_verdict(adjustment.get("verdict"))
    return None


def _accepted_adjustment_type(ir: dict[str, Any]) -> str:
    origin = str(ir.get("origin") or "").strip().lower()
    if origin == "red_substitution":
        return "Recovery substitution"
    if origin == "red_endurance_hold":
        return "Shortened Zone 2"
    if origin == "amber_regeneration":
        return "Eased ride"
    if origin == "manual_override":
        return "Manual override"
    return "Changed session"


def _accepted_adjustment_target(ir: dict[str, Any]) -> str:
    adjustment = ir.get("adjustment")
    if isinstance(adjustment, dict):
        manual = adjustment.get("manualOverride")
        if isinstance(manual, dict):
            intensity = manual.get("intensityScalePct")
            if isinstance(intensity, int):
                return f"{intensity}% of planned intensity"
        zone_drop = adjustment.get("zoneDropPct")
        duration = adjustment.get("durationScalePct")
        if isinstance(zone_drop, int) and zone_drop > 0 and isinstance(duration, int):
            return f"{duration}% duration, {zone_drop} points easier"
        power_cap = adjustment.get("powerCapPct")
        if isinstance(power_cap, int):
            return f"Capped at {power_cap}% FTP"
    return str(ir.get("name") or "Adjusted session")


def _accepted_adjustment_summary(ir: dict[str, Any]) -> str:
    adjustment = ir.get("adjustment")
    if isinstance(adjustment, dict):
        verdict = _normalize_verdict(adjustment.get("verdict"))
        if verdict == "Red":
            return "Accepted the coach's recovery substitution."
        if verdict == "Amber":
            return "Accepted the coach's eased ride."
        manual = adjustment.get("manualOverride")
        if isinstance(manual, dict):
            duration = manual.get("durationScalePct")
            intensity = manual.get("intensityScalePct")
            if isinstance(duration, int) and isinstance(intensity, int):
                return (
                    f"Accepted the manual override ({duration}% duration, {intensity}% intensity)."
                )
    name = str(ir.get("name") or "adjusted session").strip()
    return f"Accepted the adjusted session: {name}."
