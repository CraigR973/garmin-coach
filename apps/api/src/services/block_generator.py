"""App-generated 13-week 2121 training blocks — Batch 16.

The generator emits a structured, versioned 13-week 2121 block (2 build / 1
recovery, repeated, then wk12 consolidation / wk13 taper) from the athlete's
profile + FTP, then supports a **refine-then-lock** workflow (Decision #16):
mould individual days, fix errors, then lock. Locking writes the draft into the
owned plan (``plan_blocks`` + ``planned_workouts``, active) so the block feeds
the daily loop and the Zwift delivery rail under the existing approve → push gate.

The draft is **deterministic**, not an LLM call, so the 2121 shape, the VO2
progression and the Red-never-VO2 guarantee are inspectable, unit-tested invariants
that hold without ``ANTHROPIC_API_KEY`` (Decision #69). Since Batch 323 it is built by
``services.next_plan`` from his last plan: his week, read from its authored sessions,
an FTP ramp test in week 1, build weeks that progress (VO2 by ``select_vo2_protocol``,
30/30 before week 7 and Rønnestad 30/15 from it, written for ERG), two loaded
dumbbell sessions a week, and no week longer than his last plan's longest. The fixed
``coaching_state`` templates it used before stay the seed of a profile with no plan.

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
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.coaching_state import _block_name, _current_cycle_start
from src.services.holiday_pause import is_build1
from src.services.next_plan import (
    DEFAULT_LONGEST_WEEK_MIN,
    PLAN_NO_2_RHYTHM,
    PastSession,
    default_start,
    longest_week_minutes,
    next_plan_draft,
    rhythm_from,
)
from src.services.profile_clock import profile_today
from src.services.workout_categories import normalise_workout_type
from src.services.workout_delivery import IntervalsEventClient

log = structlog.get_logger(__name__)

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


#: A plan's block names carry its number: Plan No. 2 is "PN2 W01 BUILD".
_PLAN_BLOCK_NAME = re.compile(r"^PN(\d+) W\d+")


@dataclass(frozen=True)
class PreviousPlan:
    """His last plan, as the next one is built from it (Batch 323)."""

    number: int | None
    end_date: date
    sessions: list[PastSession]
    longest_week_min: int | None


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
        """Build the next plan's draft from his last plan (Batch 323). No model call.

        It starts the day after his last plan ends when that Monday is still to come,
        otherwise next Monday; it uses his FTP as it stands, because the week-1 ramp test
        sets the next one (the drift-based proposal Batch 16 used is no longer applied).
        """
        existing, content = await self._load_kb(user.id)
        if content is not None and content.get("status") == STATUS_DRAFT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An unlocked draft already exists; lock or discard it before generating",
            )

        previous = await self.previous_plan(user.id)
        if start_date is None:
            start_date = default_start(
                profile_today(user), previous.end_date if previous is not None else None
            )
        if start_date.weekday() != 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A plan starts on a Monday",
            )
        if ftp_watts is None:
            ftp_watts = await self._ftp_watts(user.id)
        athlete_name = await self._athlete_name(user)
        number = previous.number if previous is not None else None
        plan = next_plan_draft(
            start_date=start_date,
            ftp_watts=ftp_watts,
            athlete_name=athlete_name,
            generated_at_utc=_utcnow(),
            rhythm=rhythm_from(previous.sessions) if previous is not None else PLAN_NO_2_RHYTHM,
            longest_week_min=(
                previous.longest_week_min
                if previous is not None and previous.longest_week_min
                else DEFAULT_LONGEST_WEEK_MIN
            ),
            plan_number=number + 1 if number is not None else None,
            previous_name=f"Plan No. {number}" if number is not None else None,
        )
        await self._save_draft(user, plan, existing)
        await self.session.commit()
        log.info(
            "next_plan_generated",
            profile_id=str(user.id),
            plan_name=plan["planName"],
            start_date=plan["startDate"],
        )
        return plan

    async def previous_plan(self, user_id: uuid.UUID) -> PreviousPlan | None:
        """His last plan: the 13 weeks ending at his latest plan block, and its sessions.

        The authored sessions are those with the source of the plan's first row (Plan No.
        2's import, or a lock), so a swap or an edit he made later does not move his week.
        Only the columns read are loaded.
        """
        last = await self.session.scalar(
            select(PlanBlock)
            .where(PlanBlock.user_id == user_id)
            .order_by(PlanBlock.end_date.desc(), PlanBlock.version.desc())
            .limit(1)
        )
        if last is None:
            return None
        window_start = last.end_date - timedelta(days=13 * 7 - 1)
        blocks = list(
            (
                await self.session.execute(
                    select(PlanBlock).where(
                        PlanBlock.user_id == user_id,
                        PlanBlock.start_date >= window_start,
                        PlanBlock.end_date <= last.end_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {block.id: block for block in blocks}
        rows = (
            await self.session.execute(
                select(
                    PlannedWorkout.workout_date,
                    PlannedWorkout.workout_type,
                    PlannedWorkout.title,
                    PlannedWorkout.planned_duration_min,
                    PlannedWorkout.source,
                    PlannedWorkout.created_at,
                    PlannedWorkout.plan_block_id,
                )
                .where(
                    PlannedWorkout.user_id == user_id,
                    PlannedWorkout.plan_block_id.in_(list(by_id)),
                )
                .order_by(PlannedWorkout.created_at.asc())
            )
        ).all()
        match = _PLAN_BLOCK_NAME.match(last.name or "")
        number = int(match.group(1)) if match else None
        if not rows:
            return PreviousPlan(
                number=number, end_date=last.end_date, sessions=[], longest_week_min=None
            )
        authored = rows[0].source
        sessions = [
            PastSession(
                workout_date=row.workout_date,
                workout_type=str(row.workout_type or ""),
                title=str(row.title or ""),
                minutes=int(row.planned_duration_min or 0),
                block_type=str(by_id[row.plan_block_id].block_type or ""),
                week_number=int(by_id[row.plan_block_id].sequence_index or 0),
            )
            for row in rows
            if row.source == authored and row.plan_block_id in by_id
        ]
        return PreviousPlan(
            number=number,
            end_date=last.end_date,
            sessions=sessions,
            longest_week_min=longest_week_minutes(sessions),
        )

    # ------------------------------------------------------------------
    # Refine
    # ------------------------------------------------------------------

    async def refine(
        self,
        user: Profile,
        *,
        week_number: int,
        day_offset: int,
        slot: int = 0,
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
        # Batch 323: a day can carry two sessions (his Saturday ride and strength), told
        # apart by slot; a draft written before slots existed has one session a day.
        workout = next(
            (
                w
                for w in week["workouts"]
                if w.get("dayOffset") == day_offset and int(w.get("slot") or 0) == slot
            ),
            None,
        )
        if workout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Day offset {day_offset} slot {slot} is not in week {week_number}",
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
        # Batch 323: a declined plan writes nothing; its row stays, inactive, as the record.
        log.info(
            "next_plan_declined",
            profile_id=str(user.id),
            plan_name=content.get("planName"),
            start_date=content.get("startDate"),
        )

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
        log.info(
            "next_plan_accepted",
            profile_id=str(user.id),
            plan_name=content.get("planName"),
            start_date=content.get("startDate"),
            workouts=result.workouts_written,
        )

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

        A numbered plan's blocks are named as Plan No. 2's were ("PN3 W01 TEST + BUILD");
        an older draft keeps the 2121 ``_block_name`` scheme. Either name is versioned
        (max + 1) so it never collides with an existing slate. Each workout date is
        versioned once: its active rows are deactivated, then every session the draft has
        on that date is inserted, in slot order, each with the next version. Batch 323:
        deactivating before each session instead kept only the last of a two-session day.
        """
        blocks_created = 0
        workouts_written = 0
        plan_number = content.get("planNumber")

        for week in content["weeks"]:
            block_type = str(week["blockType"])
            seq = int(week["weekNumber"])
            block_start = date.fromisoformat(week["startDate"])
            block_end = date.fromisoformat(week["endDate"])
            name = (
                f"PN{int(plan_number)} W{seq:02d} {week.get('label') or block_type.upper()}"
                if isinstance(plan_number, int)
                else _block_name(seq, block_type)
            )

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
                    "planName": content.get("planName"),
                },
            )
            self.session.add(plan_block)
            await self.session.flush()
            blocks_created += 1

            by_date: dict[date, list[dict[str, Any]]] = {}
            for workout in week["workouts"]:
                by_date.setdefault(date.fromisoformat(workout["workoutDate"]), []).append(workout)
            for workout_date, sessions in sorted(by_date.items()):
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
                ordered: Sequence[dict[str, Any]] = sorted(
                    sessions, key=lambda item: int(item.get("slot") or 0)
                )
                for offset, workout in enumerate(ordered, start=1):
                    self.session.add(
                        PlannedWorkout(
                            user_id=user_id,
                            plan_block_id=plan_block.id,
                            workout_date=workout_date,
                            version=(current_version or 0) + offset,
                            title=str(workout["title"]),
                            # Batch 253 (CR236-05): the model writes this column, so
                            # it is normalised into the shared vocabulary before it
                            # lands rather than classified differently by each
                            # language afterwards.
                            workout_type=normalise_workout_type(str(workout["workoutType"])),
                            status="planned",
                            is_active=True,
                            planned_duration_min=workout.get("plannedDurationMin"),
                            intensity_target=workout.get("intensityTarget"),
                            structured_workout=workout.get("structuredWorkout") or {},
                            source=BLOCK_LOCK_SOURCE,
                        )
                    )
                    workouts_written += 1
                await self.session.flush()

        return LockResult(
            blocks_created=blocks_created,
            workouts_written=workouts_written,
            start_date=date.fromisoformat(content["startDate"]),
            end_date=date.fromisoformat(content["endDate"]),
        )
