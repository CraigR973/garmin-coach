"""App-generated 13-week 2121 training blocks — Batch 16.

The generator emits a structured, versioned 13-week 2121 block (2 build / 1
recovery, repeated, then wk12 taper / wk13 consolidation) from the athlete's
profile + FTP, then supports a **refine-then-lock** workflow (Decision #16):
mould individual days, fix errors, then lock. Locking writes the draft into the
owned plan (``plan_blocks`` + ``planned_workouts``, active) so the block feeds
the daily loop and the Zwift delivery rail under the existing approve → push gate.

The draft is **deterministic** — it reuses the shared ``coaching_state`` block
templates and the Batch 14 ``vo2_progression`` toolkit, not an LLM call — so the
2121 shape, the VO2 30/15 progression, and the Red-never-VO2 guarantee are
inspectable, unit-tested invariants that hold without ``ANTHROPIC_API_KEY``
(Decision #69). Generated VO2 days draw from ``select_vo2_protocol`` automatically
(30/30 early build, Rønnestad 30/15 from ~Week 7).

Storage: a ``knowledge_base`` row at ``section='generated_block'`` holds the
working draft as JSONB. Each generate/refine/lock versions the row (existing
deactivated, new active), mirroring the Batch 15 no-migration pattern. Lifecycle:

    generate (status='draft')  →  refine* (edit days)  →  lock (status='locked')

``generate`` refuses to clobber an unlocked draft (409) so refinements are never
silently discarded; ``discard`` drops an unlocked draft; ``lock`` writes the plan
and is the only path that mutates ``planned_workouts``.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.coaching_state import (
    BLOCK_SEQUENCE,
    _block_name,
    _block_templates,
    _current_cycle_start,
)
from src.services.holiday_pause import is_build1
from src.services.workout_delivery import IntervalsEventClient

GENERATED_BLOCK_SECTION = "generated_block"
BLOCK_LOCK_SOURCE = "block_generator_lock"
DEFAULT_FTP_WATTS = 280

STATUS_DRAFT = "draft"
STATUS_LOCKED = "locked"

_BLOCK_FOCUS = {
    "build": "Progress aerobic capacity and quality bike work.",
    "recovery": "Absorb load and protect sleep quality.",
    "taper": "Sharpen without carrying fatigue.",
    "consolidation": "Stabilize gains and set up the next cycle.",
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def next_cycle_start(today: date) -> date:
    """Default start for a freshly generated block: the Monday of next week.

    Generating a *future* block should not clobber the current part-week, so the
    default start is the next cycle boundary rather than this week's Monday.
    """
    return _current_cycle_start(today) + timedelta(days=7)


def block_label(sequence_index: int, block_type: str) -> str:
    """Human-readable label for a week in the 2121 slate.

    Build weeks alternate Build1/Build2 within each pair (reusing the Batch 15
    ``is_build1`` parity); other weeks carry their block type.
    """
    if block_type == "build":
        return "Build1" if is_build1(sequence_index) else "Build2"
    return {
        "recovery": "Recovery",
        "taper": "Taper",
        "consolidation": "Consolidation",
    }.get(block_type, block_type.title())


def generate_block_plan(
    *,
    start_date: date,
    ftp_watts: int,
    athlete_name: str,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    """Build the draft content for a 13-week 2121 block (pure, deterministic)."""
    weeks: list[dict[str, Any]] = []
    for index, block_type in enumerate(BLOCK_SEQUENCE, start=1):
        week_start = start_date + timedelta(days=(index - 1) * 7)
        week_end = week_start + timedelta(days=6)
        workouts: list[dict[str, Any]] = []
        for template in _block_templates(block_type, index):
            workouts.append(
                {
                    "dayOffset": template.day_offset,
                    "workoutDate": (week_start + timedelta(days=template.day_offset)).isoformat(),
                    "title": template.title,
                    "workoutType": template.workout_type,
                    "plannedDurationMin": template.planned_duration_min,
                    "intensityTarget": template.intensity_target,
                    "structuredWorkout": copy.deepcopy(template.structured_workout),
                }
            )
        weeks.append(
            {
                "weekNumber": index,
                "blockType": block_type,
                "label": block_label(index, block_type),
                "focus": _BLOCK_FOCUS.get(block_type, ""),
                "startDate": week_start.isoformat(),
                "endDate": week_end.isoformat(),
                "workouts": workouts,
            }
        )

    return {
        "status": STATUS_DRAFT,
        "framework": "13-week 2121",
        "startDate": start_date.isoformat(),
        "endDate": (start_date + timedelta(days=len(BLOCK_SEQUENCE) * 7 - 1)).isoformat(),
        "ftpWatts": ftp_watts,
        "athleteName": athlete_name,
        "generatedAtUtc": generated_at_utc.isoformat(),
        "lockedAtUtc": None,
        "weeks": weeks,
    }


@dataclass
class LockResult:
    blocks_created: int
    workouts_written: int
    start_date: date
    end_date: date


class BlockGeneratorService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        intervals_client: IntervalsEventClient | None = None,
    ) -> None:
        self.session = session
        self.intervals_client = intervals_client

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def _load_kb(
        self, user_id: uuid.UUID
    ) -> tuple[KnowledgeBase | None, dict[str, Any] | None]:
        row = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        if row is None:
            return None, None
        # Deep-copy so refinements never mutate the row we are about to archive.
        return row, copy.deepcopy(dict(row.content))

    async def get_draft(self, user: Profile) -> dict[str, Any] | None:
        _, content = await self._load_kb(user.id)
        return content

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

    async def _athlete_name(self, user: Profile) -> str:
        profile_section = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user.id,
                KnowledgeBase.section == "profile",
                KnowledgeBase.is_active.is_(True),
            )
        )
        if profile_section and isinstance(profile_section.content, dict):
            name = profile_section.content.get("athleteName")
            if isinstance(name, str) and name:
                return name
        return user.display_name

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    async def _save_draft(
        self,
        user: Profile,
        content: dict[str, Any],
        existing: KnowledgeBase | None,
    ) -> None:
        # Version from the max across all rows (active or archived) so a
        # discard-then-regenerate does not collide on a reused version number.
        current_version = await self.session.scalar(
            select(func.max(KnowledgeBase.version)).where(
                KnowledgeBase.user_id == user.id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
            )
        )
        if existing is not None:
            await self.session.execute(
                update(KnowledgeBase)
                .where(
                    KnowledgeBase.user_id == user.id,
                    KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                )
                .values(is_active=False)
            )
        next_version = (current_version or 0) + 1

        self.session.add(
            KnowledgeBase(
                user_id=user.id,
                section=GENERATED_BLOCK_SECTION,
                version=next_version,
                is_active=True,
                source="block_generator",
                content=content,
                updated_by_profile_id=user.id,
            )
        )

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    async def generate(
        self,
        user: Profile,
        *,
        start_date: date | None = None,
        ftp_watts: int | None = None,
    ) -> dict[str, Any]:
        existing, content = await self._load_kb(user.id)
        if content is not None and content.get("status") == STATUS_DRAFT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An unlocked draft already exists; lock or discard it before generating",
            )

        if start_date is None:
            start_date = next_cycle_start(date.today())
        if ftp_watts is None:
            ftp_watts = await self._ftp_watts(user.id)
        athlete_name = await self._athlete_name(user)

        plan = generate_block_plan(
            start_date=start_date,
            ftp_watts=ftp_watts,
            athlete_name=athlete_name,
            generated_at_utc=_utcnow(),
        )
        await self._save_draft(user, plan, existing)
        await self.session.commit()
        return plan

    # ------------------------------------------------------------------
    # Refine
    # ------------------------------------------------------------------

    async def refine(
        self,
        user: Profile,
        *,
        week_number: int,
        day_offset: int,
        title: str | None = None,
        workout_type: str | None = None,
        planned_duration_min: int | None = None,
        intensity_target: str | None = None,
        structured_workout: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing, content = await self._load_kb(user.id)
        if existing is None or content is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No generated block draft to refine",
            )
        if content.get("status") != STATUS_DRAFT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot refine a locked block; generate a new draft instead",
            )

        week = next((w for w in content["weeks"] if w.get("weekNumber") == week_number), None)
        if week is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Week {week_number} is not in the draft",
            )
        workout = next((w for w in week["workouts"] if w.get("dayOffset") == day_offset), None)
        if workout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Day offset {day_offset} is not in week {week_number}",
            )

        if title is not None:
            workout["title"] = title
        if workout_type is not None:
            workout["workoutType"] = workout_type
        if planned_duration_min is not None:
            workout["plannedDurationMin"] = planned_duration_min
        if intensity_target is not None:
            workout["intensityTarget"] = intensity_target
        if structured_workout is not None:
            workout["structuredWorkout"] = structured_workout

        await self._save_draft(user, content, existing)
        await self.session.commit()
        return content

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    async def discard(self, user: Profile) -> None:
        existing, content = await self._load_kb(user.id)
        if existing is None or content is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No generated block draft to discard",
            )
        if content.get("status") == STATUS_LOCKED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Locked blocks are part of the plan and cannot be discarded",
            )
        await self.session.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.user_id == user.id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
            )
            .values(is_active=False)
        )
        await self.session.commit()

    # ------------------------------------------------------------------
    # Lock
    # ------------------------------------------------------------------

    async def lock(self, user: Profile) -> LockResult:
        existing, content = await self._load_kb(user.id)
        if existing is None or content is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No generated block draft to lock",
            )
        if content.get("status") == STATUS_LOCKED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This block is already locked",
            )

        result = await self._write_plan(user.id, content)

        content["status"] = STATUS_LOCKED
        content["lockedAtUtc"] = _utcnow().isoformat()
        await self._save_draft(user, content, existing)
        await self.session.commit()

        # Push-on-plan-set (Decision #99): the locked block's bike sessions are
        # delivered to Zwift now, days ahead, with no per-workout approval — so by
        # the morning each session is already on the calendar and the morning is
        # review-only. Delivery is isolated/idempotent and degrades gracefully when
        # intervals.icu is unconfigured, so locking the plan never fails on it.
        from src.services.executable_coaching import ExecutableCoachingService

        delivery = ExecutableCoachingService(self.session, intervals_client=self.intervals_client)
        await delivery.reconcile_deliveries(
            user, start_date=result.start_date, end_date=result.end_date
        )
        return result

    async def _write_plan(self, user_id: uuid.UUID, content: dict[str, Any]) -> LockResult:
        """Write the draft into ``plan_blocks`` + active ``planned_workouts``.

        Plan-block names reuse the 2121 ``_block_name`` scheme, so the block name
        is versioned (max + 1) to avoid colliding with an existing seed slate.
        Each workout date is versioned: any active row on that date is deactivated
        and a new active version inserted — the same pattern as the holiday
        regenerator — so locking integrates with, rather than duplicates, history.
        """
        blocks_created = 0
        workouts_written = 0

        for week in content["weeks"]:
            block_type = str(week["blockType"])
            seq = int(week["weekNumber"])
            block_start = date.fromisoformat(week["startDate"])
            block_end = date.fromisoformat(week["endDate"])
            name = _block_name(seq, block_type)

            current_block_version = await self.session.scalar(
                select(func.max(PlanBlock.version)).where(
                    PlanBlock.user_id == user_id,
                    PlanBlock.name == name,
                )
            )
            plan_block = PlanBlock(
                user_id=user_id,
                name=name,
                version=(current_block_version or 0) + 1,
                sequence_index=seq,
                block_type=block_type,
                start_date=block_start,
                end_date=block_end,
                goals_json={
                    "focus": _BLOCK_FOCUS.get(block_type, ""),
                    "weekNumber": seq,
                    "label": week.get("label"),
                },
                raw_plan={
                    "cycle": "2121",
                    "weekNumber": seq,
                    "blockType": block_type,
                    "source": "block_generator",
                },
            )
            self.session.add(plan_block)
            await self.session.flush()
            blocks_created += 1

            for workout in week["workouts"]:
                workout_date = date.fromisoformat(workout["workoutDate"])
                current_version = await self.session.scalar(
                    select(func.max(PlannedWorkout.version)).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == workout_date,
                    )
                )
                await self.session.execute(
                    update(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == workout_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                    .values(is_active=False)
                )
                self.session.add(
                    PlannedWorkout(
                        user_id=user_id,
                        plan_block_id=plan_block.id,
                        workout_date=workout_date,
                        version=(current_version or 0) + 1,
                        title=str(workout["title"]),
                        workout_type=str(workout["workoutType"]),
                        status="planned",
                        is_active=True,
                        planned_duration_min=workout.get("plannedDurationMin"),
                        intensity_target=workout.get("intensityTarget"),
                        structured_workout=workout.get("structuredWorkout") or {},
                        source=BLOCK_LOCK_SOURCE,
                    )
                )
                workouts_written += 1

        return LockResult(
            blocks_created=blocks_created,
            workouts_written=workouts_written,
            start_date=date.fromisoformat(content["startDate"]),
            end_date=date.fromisoformat(content["endDate"]),
        )
