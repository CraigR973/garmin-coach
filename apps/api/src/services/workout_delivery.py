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

    async def create_workout_event(self, payload: dict[str, Any]) -> IntervalsCreateResult:
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

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/athlete/{self.athlete_id}/events",
                auth=("API_KEY", self.api_key),
                json=payload,
            )
        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"intervals.icu event create failed with HTTP {response.status_code}",
            )
        body = response.json()
        event_id = str(body.get("id") or "")
        if not event_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="intervals.icu response did not include an event id",
            )
        return IntervalsCreateResult(event_id=event_id, raw_response=body)


def build_structured_workout_ir(
    workout: PlannedWorkout,
    *,
    ftp_watts: int = DEFAULT_FTP_WATTS,
) -> dict[str, Any]:
    structured = workout.structured_workout or {}
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
        steps.extend(_expand_step(raw_step, workout.intensity_target))

    if not steps:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Structured bike workout did not produce deliverable steps",
        )

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


def _power_pct(text: str, *, fallback: int | None = None) -> int:
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*%", text)
    if range_match:
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
    return 55


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
