from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import KnowledgeBase, PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile

DEFAULT_FTP_WATTS = 280
PROVIDER_INTERVALS_ICU = "intervals_icu"
STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_PUSHED = "pushed"
STATUS_FAILED = "failed"
STATUS_DELETED = "deleted"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class IntervalsCreateResult:
    event_id: str
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class WeekAheadEntry:
    workout: PlannedWorkout
    proposal: WorkoutDeliveryProposal | None


class IntervalsEventClient(Protocol):
    async def create_workout_event(self, payload: dict[str, Any]) -> IntervalsCreateResult: ...
    async def update_workout_event(
        self, event_id: str, payload: dict[str, Any]
    ) -> IntervalsCreateResult: ...
    async def delete_workout_event(self, event_id: str) -> None: ...


class IntervalsIcuClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        athlete_id: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.intervals_api_key
        self.athlete_id = athlete_id if athlete_id is not None else settings.intervals_athlete_id
        self.base_url = (base_url if base_url is not None else settings.intervals_base_url).rstrip(
            "/"
        )

    def _auth(self) -> tuple[str, str]:
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="intervals.icu API key is not configured",
            )
        if not self.athlete_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="intervals.icu athlete id is not configured",
            )
        return ("API_KEY", self.api_key)

    def _events_url(self, event_id: str | None = None) -> str:
        base = f"{self.base_url}/athlete/{self.athlete_id}/events"
        return f"{base}/{event_id}" if event_id else base

    async def create_workout_event(self, payload: dict[str, Any]) -> IntervalsCreateResult:
        auth = self._auth()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self._events_url(), auth=auth, json=payload)
        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"intervals.icu event create failed with HTTP {response.status_code}",
            )
        return self._result(response.json())

    async def update_workout_event(
        self, event_id: str, payload: dict[str, Any]
    ) -> IntervalsCreateResult:
        """Update an existing calendar event in place (replace/move).

        Batch 29 re-syncs an already-delivered workout — a manual edit, an
        approved sleep adjustment, or a day swap — by PUTting the new payload to
        ``/events/{event_id}`` rather than creating a duplicate, so the live Zwift
        event keeps its identity (Decision #99, true update-in-place mechanism).
        """
        auth = self._auth()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.put(self._events_url(event_id), auth=auth, json=payload)
        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"intervals.icu event update failed with HTTP {response.status_code}",
            )
        return self._result(response.json(), fallback_event_id=event_id)

    async def delete_workout_event(self, event_id: str) -> None:
        """Delete a calendar event (Skip). A 404 is treated as already-gone so the
        delete is idempotent across retries."""
        auth = self._auth()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.delete(self._events_url(event_id), auth=auth)
        if response.status_code not in (200, 204, 404):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"intervals.icu event delete failed with HTTP {response.status_code}",
            )

    @staticmethod
    def _result(
        body: dict[str, Any], *, fallback_event_id: str | None = None
    ) -> IntervalsCreateResult:
        event_id = str(body.get("id") or fallback_event_id or "")
        if not event_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="intervals.icu response did not include an event id",
            )
        return IntervalsCreateResult(event_id=event_id, raw_response=body)


def expand_structured_steps(
    structured: dict[str, Any] | None,
    intensity_target: str | None,
) -> list[dict[str, Any]]:
    """Expand a ``structured_workout`` dict into concrete IR steps (pure, DB-free).

    Shared by ``build_structured_workout_ir`` (the delivery path) and
    ``validate_deliverable_bike_workout`` (the import gate). Raises 422 when the
    workout is not a bike, has no steps, or a step can't resolve — no step is ever
    silently dropped or defaulted to a plausible-looking easy ride.
    """
    structured = structured or {}
    if structured.get("format") != "bike":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only bike workouts can be delivered to Zwift",
        )

    raw_steps = structured.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Structured bike workout has no steps to deliver",
        )

    steps: list[dict[str, Any]] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue
        steps.extend(_expand_step(raw_step, intensity_target))

    if not steps:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Structured bike workout did not produce deliverable steps",
        )
    return steps


def validate_deliverable_bike_workout(
    structured: dict[str, Any] | None,
    intensity_target: str | None,
    *,
    context: str = "",
) -> list[dict[str, Any]]:
    """Assert a plan's bike workout is a real, deliverable structured session.

    Import-time gate (Batch 67): every target must resolve (no silent 55% ride),
    the workout must be multi-step, and it must carry a warm-up, a cool-down, and
    at least one authored ramp. Raises ``ValueError`` (with ``context``) so a
    malformed plan fails at import — before anything reaches Zwift. Returns the
    expanded steps so the caller can also check ``duration_min`` traces the sum.
    """
    where = f" ({context})" if context else ""
    try:
        steps = expand_structured_steps(structured, intensity_target)
    except HTTPException as exc:
        raise ValueError(f"bike workout is not deliverable{where}: {exc.detail}") from exc
    if len(steps) < 2:
        raise ValueError(f"bike workout collapsed to a single block{where}")
    phases = {str(step["phase"]) for step in steps}
    if "warmup" not in phases:
        raise ValueError(f"bike workout has no warm-up step{where}")
    if "cooldown" not in phases:
        raise ValueError(f"bike workout has no cool-down step{where}")
    if not any(step["kind"] == "ramp" for step in steps):
        raise ValueError(f"bike workout has no ramp (warm-up/cool-down authored flat){where}")
    return steps


def build_structured_workout_ir(
    workout: PlannedWorkout,
    *,
    ftp_watts: int = DEFAULT_FTP_WATTS,
) -> dict[str, Any]:
    steps = expand_structured_steps(workout.structured_workout, workout.intensity_target)
    total_seconds = sum(int(step["durationSec"]) for step in steps)
    return {
        "version": 1,
        "source": "planned_workouts",
        "plannedWorkoutId": str(workout.id),
        "plannedWorkoutVersion": workout.version,
        "workoutDate": workout.workout_date.isoformat(),
        "name": workout.title,
        "workoutType": workout.workout_type,
        "ftpWatts": ftp_watts,
        "totalDurationSec": total_seconds,
        "cadenceCriticalExpanded": True,
        "steps": steps,
    }


def build_intervals_payload(ir: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": "WORKOUT",
        "start_date_local": f"{ir['workoutDate']}T00:00:00",
        "type": "Ride",
        "name": ir["name"],
        "description": _intervals_description(ir),
    }


def build_zwo_xml(ir: dict[str, Any]) -> str:
    lines = [
        "<workout_file>",
        "  <author>Garmin Coach</author>",
        f"  <name>{html.escape(str(ir['name']))}</name>",
        "  <sportType>bike</sportType>",
        "  <workout>",
    ]
    for step in ir["steps"]:
        duration = int(step["durationSec"])
        cadence = step.get("cadenceRpm")
        cadence_attr = f' Cadence="{int(cadence)}"' if cadence else ""
        low = float(step["powerStartPct"]) / 100
        high = float(step["powerEndPct"]) / 100
        if step["kind"] == "ramp":
            tag = "Warmup" if step["phase"] == "warmup" else "Cooldown"
            lines.append(
                f'    <{tag} Duration="{duration}" PowerLow="{_zwo_power(low)}" '
                f'PowerHigh="{_zwo_power(high)}"{cadence_attr}/>'
            )
        else:
            lines.append(
                f'    <SteadyState Duration="{duration}" Power="{_zwo_power(high)}"{cadence_attr}/>'
            )
    lines.extend(["  </workout>", "</workout_file>"])
    return "\n".join(lines) + "\n"


class WorkoutDeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        intervals_client: IntervalsEventClient | None = None,
    ) -> None:
        self.session = session
        self.intervals_client = intervals_client or IntervalsIcuClient()

    async def list_proposals(self, player: Profile) -> list[WorkoutDeliveryProposal]:
        result = await self.session.execute(
            select(WorkoutDeliveryProposal)
            .where(WorkoutDeliveryProposal.user_id == player.id)
            .order_by(WorkoutDeliveryProposal.created_at.desc())
            .limit(50)
        )
        return list(result.scalars().all())

    async def propose(
        self,
        *,
        player: Profile,
        planned_workout_id: uuid.UUID,
    ) -> WorkoutDeliveryProposal:
        workout = await self._planned_workout(player.id, planned_workout_id)
        ftp_watts = await self._ftp_watts(player.id)
        ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
        return await self.propose_from_ir(player=player, workout=workout, ir=ir)

    async def propose_from_ir(
        self,
        *,
        player: Profile,
        workout: PlannedWorkout,
        ir: dict[str, Any],
        commit: bool = True,
    ) -> WorkoutDeliveryProposal:
        """Persist a delivery proposal from an already-built IR.

        Shared by the manual propose path (base IR) and Batch 13's executable
        coaching path (an Amber-adjusted or Red-substituted IR). The IR snapshot
        is the source of truth for the intervals.icu payload + ``.ZWO`` fallback.
        """
        proposal = WorkoutDeliveryProposal(
            user_id=player.id,
            planned_workout_id=workout.id,
            planned_workout_version=workout.version,
            workout_date=workout.workout_date,
            provider=PROVIDER_INTERVALS_ICU,
            status=STATUS_PROPOSED,
            proposed_at_utc=_utcnow(),
            structured_workout_ir=ir,
            intervals_payload=build_intervals_payload(ir),
            zwo_xml=build_zwo_xml(ir),
        )
        self.session.add(proposal)
        if commit:
            await self.session.commit()
            await self.session.refresh(proposal)
        else:
            await self.session.flush()
        return proposal

    async def list_week_ahead(
        self,
        player: Profile,
        *,
        start_date: date,
        days: int = 7,
    ) -> list[WeekAheadEntry]:
        """Upcoming deliverable (bike) workouts with their latest proposal.

        Powers the PWA week-ahead surface (Decision #31): the human sees the
        week, then propose → approve drives delivery. Strength/mobility days are
        omitted because only bike workouts can be delivered to Zwift.
        """
        end_date = start_date + timedelta(days=max(1, days) - 1)
        workouts = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.is_active.is_(True),
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
        latest_by_workout = await self._latest_proposals_by_workout(player.id, start_date, end_date)

        entries: list[WeekAheadEntry] = []
        for workout in workouts:
            structured = workout.structured_workout or {}
            if structured.get("format") != "bike":
                continue
            entries.append(
                WeekAheadEntry(
                    workout=workout,
                    proposal=latest_by_workout.get(workout.id),
                )
            )
        return entries

    async def _latest_proposals_by_workout(
        self,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> dict[uuid.UUID, WorkoutDeliveryProposal]:
        proposals = (
            (
                await self.session.execute(
                    select(WorkoutDeliveryProposal)
                    .where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.workout_date >= start_date,
                        WorkoutDeliveryProposal.workout_date <= end_date,
                    )
                    .order_by(WorkoutDeliveryProposal.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        latest: dict[uuid.UUID, WorkoutDeliveryProposal] = {}
        for proposal in proposals:
            if proposal.planned_workout_id is None:
                continue
            latest.setdefault(proposal.planned_workout_id, proposal)
        return latest

    async def approve(
        self,
        *,
        player: Profile,
        proposal_id: uuid.UUID,
    ) -> WorkoutDeliveryProposal:
        proposal = await self._proposal(player.id, proposal_id)
        if proposal.status == STATUS_PUSHED:
            return proposal
        if proposal.status != STATUS_PROPOSED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Proposal cannot be approved from status {proposal.status}",
            )
        proposal.status = STATUS_APPROVED
        proposal.approved_at_utc = _utcnow()
        proposal.approved_by_profile_id = player.id
        proposal.last_error = None
        await self.session.commit()
        await self.session.refresh(proposal)
        return proposal

    async def push(
        self,
        *,
        player: Profile,
        proposal_id: uuid.UUID,
    ) -> WorkoutDeliveryProposal:
        proposal = await self._proposal(player.id, proposal_id)
        if proposal.status == STATUS_PUSHED:
            return proposal
        if proposal.status not in {STATUS_APPROVED, STATUS_FAILED} or not proposal.approved_at_utc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Proposal must be approved before it can be pushed",
            )
        try:
            result = await self.intervals_client.create_workout_event(proposal.intervals_payload)
        except HTTPException as exc:
            proposal.status = STATUS_FAILED
            proposal.last_error = str(exc.detail)
            await self.session.commit()
            raise

        proposal.status = STATUS_PUSHED
        proposal.pushed_at_utc = _utcnow()
        proposal.intervals_event_id = result.event_id
        proposal.last_error = None
        await self.session.commit()
        await self.session.refresh(proposal)
        return proposal

    async def latest_delivered_for_date(
        self, user_id: uuid.UUID, workout_date: date
    ) -> WorkoutDeliveryProposal | None:
        """The live Zwift event for a calendar slot: the most recent proposal on
        ``workout_date`` that was pushed and still carries an intervals event id.

        Resolving by *date* (not planned-workout id) keeps re-syncs robust when a
        restructure re-versions the slot into a fresh ``planned_workouts`` row —
        the event already sitting on that day is the one to replace or move.
        """
        proposal: WorkoutDeliveryProposal | None = await self.session.scalar(
            select(WorkoutDeliveryProposal)
            .where(
                WorkoutDeliveryProposal.user_id == user_id,
                WorkoutDeliveryProposal.workout_date == workout_date,
                WorkoutDeliveryProposal.status == STATUS_PUSHED,
                WorkoutDeliveryProposal.intervals_event_id.is_not(None),
            )
            .order_by(WorkoutDeliveryProposal.created_at.desc())
            .limit(1)
        )
        return proposal

    async def latest_delivered_for_workout(
        self, user_id: uuid.UUID, planned_workout_id: uuid.UUID
    ) -> WorkoutDeliveryProposal | None:
        """The live Zwift event for a specific planned workout.

        Batch 30 allows mixed days and append-to-occupied-day actions, so a date
        can legitimately carry more than one workout. Prefer the workout id for
        action routes; date lookup remains as the compatibility fallback for
        older delivery rows that were keyed to the slot before mixed days.
        """
        proposal: WorkoutDeliveryProposal | None = await self.session.scalar(
            select(WorkoutDeliveryProposal)
            .where(
                WorkoutDeliveryProposal.user_id == user_id,
                WorkoutDeliveryProposal.planned_workout_id == planned_workout_id,
                WorkoutDeliveryProposal.status == STATUS_PUSHED,
                WorkoutDeliveryProposal.intervals_event_id.is_not(None),
            )
            .order_by(WorkoutDeliveryProposal.created_at.desc())
            .limit(1)
        )
        return proposal

    async def create_event(
        self,
        *,
        proposal: WorkoutDeliveryProposal,
        ir: dict[str, Any],
        commit: bool = True,
    ) -> WorkoutDeliveryProposal:
        """Create a brand-new Zwift event for a proposal from ``ir``.

        Backs push-on-plan-set (the as-planned baseline, delivered without a
        per-workout approval — Decision #99) and the replace/move fallback when a
        slot has no live event yet. On a cloud failure the proposal is marked
        ``failed`` with the error and re-raised; it is never recorded as delivered.
        """
        payload = build_intervals_payload(ir)
        try:
            result = await self.intervals_client.create_workout_event(payload)
        except HTTPException as exc:
            proposal.status = STATUS_FAILED
            proposal.last_error = str(exc.detail)
            await self.session.commit()
            raise
        return await self._persist_event(proposal, ir, payload, result.event_id, commit=commit)

    async def replace_event(
        self,
        *,
        proposal: WorkoutDeliveryProposal,
        ir: dict[str, Any],
        commit: bool = True,
    ) -> WorkoutDeliveryProposal:
        """Re-sync a delivered workout's content in place (Edit / Approve-adjusted).

        The intervals.icu event is updated first; only once the cloud write
        succeeds is the new IR persisted, so a failed re-sync leaves local state
        honest (Decision #97) — the proposal keeps its previously-delivered IR plus
        a ``last_error`` note rather than claiming a change that never landed.
        """
        if not proposal.intervals_event_id:
            return await self.create_event(proposal=proposal, ir=ir, commit=commit)
        payload = build_intervals_payload(ir)
        try:
            result = await self.intervals_client.update_workout_event(
                proposal.intervals_event_id, payload
            )
        except HTTPException as exc:
            proposal.last_error = str(exc.detail)
            await self.session.commit()
            raise
        return await self._persist_event(proposal, ir, payload, result.event_id, commit=commit)

    async def move_event(
        self,
        *,
        proposal: WorkoutDeliveryProposal,
        new_date: date,
        commit: bool = True,
    ) -> WorkoutDeliveryProposal:
        """Move a delivered event to ``new_date`` (Swap day) by updating
        ``start_date_local`` in place. Honest on failure (Decision #97): the local
        ``workout_date`` only changes once the cloud move succeeds."""
        ir = dict(proposal.structured_workout_ir or {})
        ir["workoutDate"] = new_date.isoformat()
        if not proposal.intervals_event_id:
            proposal.workout_date = new_date
            return await self.create_event(proposal=proposal, ir=ir, commit=commit)
        payload = build_intervals_payload(ir)
        try:
            result = await self.intervals_client.update_workout_event(
                proposal.intervals_event_id, payload
            )
        except HTTPException as exc:
            proposal.last_error = str(exc.detail)
            await self.session.commit()
            raise
        proposal.workout_date = new_date
        return await self._persist_event(proposal, ir, payload, result.event_id, commit=commit)

    async def delete_event(
        self,
        *,
        proposal: WorkoutDeliveryProposal,
        commit: bool = True,
    ) -> WorkoutDeliveryProposal:
        """Delete a delivered event (Skip). Idempotent — a missing event is
        treated as already-gone by the client. Honest on failure (Decision #97):
        the proposal is only marked deleted once the cloud delete succeeds."""
        if proposal.intervals_event_id:
            try:
                await self.intervals_client.delete_workout_event(proposal.intervals_event_id)
            except HTTPException as exc:
                proposal.last_error = str(exc.detail)
                await self.session.commit()
                raise
        proposal.status = STATUS_DELETED
        proposal.last_error = None
        if commit:
            await self.session.commit()
            await self.session.refresh(proposal)
        else:
            await self.session.flush()
        return proposal

    async def _persist_event(
        self,
        proposal: WorkoutDeliveryProposal,
        ir: dict[str, Any],
        payload: dict[str, Any],
        event_id: str,
        *,
        commit: bool,
    ) -> WorkoutDeliveryProposal:
        proposal.structured_workout_ir = ir
        proposal.intervals_payload = payload
        proposal.zwo_xml = build_zwo_xml(ir)
        proposal.intervals_event_id = event_id
        proposal.status = STATUS_PUSHED
        proposal.pushed_at_utc = _utcnow()
        proposal.last_error = None
        if commit:
            await self.session.commit()
            await self.session.refresh(proposal)
        else:
            await self.session.flush()
        return proposal

    async def _planned_workout(
        self,
        user_id: uuid.UUID,
        planned_workout_id: uuid.UUID,
    ) -> PlannedWorkout:
        workout = await self.session.scalar(
            select(PlannedWorkout).where(
                PlannedWorkout.id == planned_workout_id,
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.is_active.is_(True),
            )
        )
        if workout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Planned workout not found",
            )
        return workout

    async def _proposal(
        self,
        user_id: uuid.UUID,
        proposal_id: uuid.UUID,
    ) -> WorkoutDeliveryProposal:
        proposal = await self.session.scalar(
            select(WorkoutDeliveryProposal).where(
                WorkoutDeliveryProposal.id == proposal_id,
                WorkoutDeliveryProposal.user_id == user_id,
            )
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workout delivery proposal not found",
            )
        return proposal

    async def _ftp_watts(self, user_id: uuid.UUID) -> int:
        profile_section = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == "profile",
                KnowledgeBase.is_active.is_(True),
            )
        )
        if profile_section and isinstance(profile_section.content, dict):
            ftp = profile_section.content.get("ftpWatts")
            if isinstance(ftp, int) and ftp > 0:
                return ftp
        return DEFAULT_FTP_WATTS


def _expand_step(raw_step: dict[str, Any], workout_target: str | None) -> list[dict[str, Any]]:
    label = str(raw_step.get("label") or "Step")
    phase = _phase(label)
    target_text = str(raw_step.get("target") or workout_target or label)
    cadence = _cadence(raw_step)

    ramp = raw_step.get("ramp")
    if ramp is not None:
        # Ramp raw-step form (Batch 67): ``{"label", "minutes", "ramp": [startPct, endPct]}``
        # authors a genuine ramp (powerStartPct != powerEndPct) — the warm-up/cool-down
        # shape the plan needs. Without this, _expand_step could only emit steady steps,
        # so every "warm-up" landed flat.
        if "minutes" not in raw_step:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Ramp step {label!r} needs a 'minutes' duration",
            )
        if not isinstance(ramp, (list, tuple)) or len(ramp) != 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Ramp step {label!r} 'ramp' must be [startPct, endPct]",
            )
        duration = int(float(raw_step["minutes"]) * 60)
        start_pct = _ramp_pct(ramp[0], label)
        end_pct = _ramp_pct(ramp[1], label)
        return [_step(label, phase, duration, start_pct, end_pct, cadence)]

    if "minutes" in raw_step:
        duration = int(float(raw_step["minutes"]) * 60)
        pct = _power_pct(target_text)
        return [_step(label, phase, duration, pct, pct, cadence)]

    pattern = str(raw_step.get("pattern") or "")
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workout step {label!r} has no duration or pattern",
        )
    return _expand_pattern(
        label, phase, pattern, target_text, cadence, int(raw_step.get("repeats") or 1)
    )


def _expand_pattern(
    label: str,
    phase: str,
    pattern: str,
    target_text: str,
    cadence: int | None,
    repeats: int,
) -> list[dict[str, Any]]:
    local_repeats = 1
    rest = pattern.strip()
    match = re.match(r"(?P<count>\d+)\s*x\s+(?P<rest>.+)", rest, flags=re.IGNORECASE)
    if match:
        local_repeats = int(match.group("count"))
        rest = match.group("rest")

    parts = [part.strip() for part in rest.split("/") if part.strip()]
    if len(parts) == 1:
        duration = _duration_sec(parts[0])
        pct = _power_pct(target_text)
        return [_step(label, phase, duration, pct, pct, cadence)]
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workout pattern {pattern!r} is not deliverable",
        )

    on_duration = _duration_sec(parts[0])
    off_duration = _duration_sec(parts[1])
    on_pct = _power_pct(target_text)
    off_pct = _power_pct(parts[1], fallback=50)
    total_repeats = max(1, repeats) * max(1, local_repeats)
    steps: list[dict[str, Any]] = []
    for idx in range(total_repeats):
        suffix = f"{idx + 1}/{total_repeats}"
        steps.append(_step(f"{label} work {suffix}", phase, on_duration, on_pct, on_pct, cadence))
        steps.append(
            _step(f"{label} recovery {suffix}", phase, off_duration, off_pct, off_pct, None)
        )
    return steps


def _step(
    label: str,
    phase: str,
    duration_sec: int,
    power_start_pct: int,
    power_end_pct: int,
    cadence_rpm: int | None,
) -> dict[str, Any]:
    kind = "ramp" if power_start_pct != power_end_pct else "steady"
    step: dict[str, Any] = {
        "label": label,
        "phase": phase,
        "kind": kind,
        "durationSec": duration_sec,
        "powerStartPct": power_start_pct,
        "powerEndPct": power_end_pct,
    }
    if cadence_rpm:
        step["cadenceRpm"] = cadence_rpm
    return step


def _phase(label: str) -> str:
    lower = label.lower()
    if "warm" in lower or "settle" in lower:
        return "warmup"
    if "cool" in lower:
        return "cooldown"
    return "interval"


def _duration_sec(text: str) -> int:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b", text, re.I)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse workout duration from {text!r}",
        )
    value = float(match.group(1))
    unit = match.group(2).lower()
    return int(value if unit.startswith("s") else value * 60)


def _cadence(raw_step: dict[str, Any]) -> int | None:
    explicit = raw_step.get("cadenceRpm")
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    haystack = f"{raw_step.get('target', '')} {raw_step.get('pattern', '')}"
    match = re.search(r"(\d+)\s*rpm\b", haystack, re.I)
    if match:
        return int(match.group(1))
    return None


def _ramp_pct(value: Any, label: str) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ramp step {label!r} has a non-numeric power {value!r}",
        ) from None


# Range separators seen in the plan text: ASCII hyphen plus the unicode dash family
# (hyphen U+2010, non-breaking hyphen U+2011, figure dash U+2012, en dash U+2013,
# em dash U+2014, horizontal bar U+2015) and the minus sign U+2212. The plan uses an
# en dash ("65–72%"), which the old ASCII-only regex missed — so it fell through to the
# single-% branch and grabbed the *top* of the band (72), grading a fine Z2 "under".
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-‐-―−]\s*(\d+(?:\.\d+)?)\s*%")


def _power_pct(text: str, *, fallback: int | None = None) -> int:
    range_match = _RANGE_RE.search(text)
    if range_match:
        # Collapse a band to its midpoint so "65-72%" delivers ~68% (and grades a
        # 64.9% ride "on" within ±5, not "under" against 72).
        return round((float(range_match.group(1)) + float(range_match.group(2))) / 2)
    single_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if single_match:
        return round(float(single_match.group(1)))

    lower = text.lower()
    zone_map = [
        ("threshold", 98),
        ("sweet spot", 91),
        ("tempo", 80),
        ("upper zone 1", 55),
        ("low zone 2", 60),
        ("zone 2", 65),
        ("endurance", 65),
        ("easy", 50),
        ("recovery", 50),
        ("spin-up", 85),
    ]
    for needle, pct in zone_map:
        if needle in lower:
            return pct
    if fallback is not None:
        return fallback
    # No silent 55% fallback (Batch 67): an unresolvable target must fail loudly at
    # propose/import rather than deliver a plausible-looking flat easy ride to Zwift.
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Could not resolve a power target from {text!r}",
    )


def _intervals_description(ir: dict[str, Any]) -> str:
    lines = ["Garmin Coach approved workout", ""]
    for step in ir["steps"]:
        duration = _intervals_duration(int(step["durationSec"]))
        cadence = f" {step['cadenceRpm']}rpm" if step.get("cadenceRpm") else ""
        start_pct = int(step["powerStartPct"])
        end_pct = int(step["powerEndPct"])
        if step["kind"] == "ramp":
            target = f"ramp {start_pct}-{end_pct}%"
        else:
            target = f"{end_pct}%"
        lines.append(f"- {duration} {target}{cadence}")
    return "\n".join(lines)


def _intervals_duration(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _zwo_power(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")
