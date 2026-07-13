"""Holiday pause/resume — Batch 15.

A holiday window is treated as a recovery-week equivalent:
  * Planned workouts during the window are versioned as ``status='skipped'``
    with ``source='holiday_pause'``.
  * On return, block continuation follows the 2121 rule:
      - pre-holiday Build1 → first week back continues as Build2
      - pre-holiday Build2 → first week back repeats Build1

Build1/Build2 is determined from the plan block's ``sequence_index`` in the
seeded 2121 slate: (S-1) % 3 == 0 → Build1; (S-1) % 3 == 1 → Build2.

Storage: a ``knowledge_base`` row with ``section='holiday_windows'`` holds the
window history as ``{"windows": [{startDate, endDate, pausedAtUtc, resumedAtUtc}]}``.
No migration required (mirrors the Batch 14 no-migration pattern).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.coaching_state import _block_templates

KB_SECTION = "holiday_windows"
HOLIDAY_PAUSE_SOURCE = "holiday_pause"
HOLIDAY_RESUME_SOURCE = "holiday_resume"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class HolidayWindow:
    start_date: date
    end_date: date
    paused_at_utc: datetime
    resumed_at_utc: datetime | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HolidayWindow:
        return cls(
            start_date=date.fromisoformat(d["startDate"]),
            end_date=date.fromisoformat(d["endDate"]),
            paused_at_utc=datetime.fromisoformat(d["pausedAtUtc"]),
            resumed_at_utc=datetime.fromisoformat(d["resumedAtUtc"])
            if d.get("resumedAtUtc")
            else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
            "pausedAtUtc": self.paused_at_utc.isoformat(),
            "resumedAtUtc": self.resumed_at_utc.isoformat() if self.resumed_at_utc else None,
        }

    @property
    def is_active(self) -> bool:
        return self.resumed_at_utc is None


def holiday_windows_covering_date(
    windows: Sequence[HolidayWindow], subject_date: date
) -> list[HolidayWindow]:
    """Return the stored holiday windows that cover ``subject_date``.

    Historical/resumed windows intentionally remain eligible: analysis packets
    use this helper when reconstructing the truth for a past date.
    """
    return [window for window in windows if window.start_date <= subject_date <= window.end_date]


def active_holiday_window_for_date(
    windows: Sequence[HolidayWindow], subject_date: date
) -> HolidayWindow | None:
    """Return the current away window when it covers ``subject_date``.

    Scheduled environment jobs use the active-only form so an early resume
    immediately re-enables the bedroom subsystem even if the original window's
    planned end date is still in the future.
    """
    return next(
        (
            window
            for window in reversed(holiday_windows_covering_date(windows, subject_date))
            if window.is_active
        ),
        None,
    )


@dataclass
class PauseResult:
    window: HolidayWindow
    skipped_count: int


@dataclass
class ResumeResult:
    window: HolidayWindow
    continuation_label: str
    regenerated_count: int


def is_build1(sequence_index: int) -> bool:
    """True if this build block is the first in its 2121 build pair.

    In the seeded 13-week 2121 slate the pairs are at sequence indexes
    (1,2), (4,5), (7,8), (10,11).  (S-1) % 3 == 0 → Build1; == 1 → Build2.
    """
    return (sequence_index - 1) % 3 == 0


def continuation_label(sequence_index: int, block_type: str) -> str:
    """Human-readable label for the first post-holiday training block."""
    if block_type != "build":
        return "Build1"
    return "Build2" if is_build1(sequence_index) else "Build1"


def continuation_week_number(sequence_index: int, block_type: str) -> int:
    """Template week number to use when regenerating the first post-holiday week.

    Build1 pre-holiday → continue to Build2 (week S+1).
    Build2 pre-holiday → repeat Build1 (week S-1).
    Non-build → fall back to week 1 template.
    """
    if block_type != "build":
        return 1
    if is_build1(sequence_index):
        return sequence_index + 1
    return max(sequence_index - 1, 1)


class HolidayPauseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def _load_kb(
        self, user_id: uuid.UUID
    ) -> tuple[KnowledgeBase | None, list[HolidayWindow]]:
        row = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == KB_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        if row is None:
            return None, []
        return row, [HolidayWindow.from_dict(w) for w in row.content.get("windows", [])]

    async def get_windows(self, user: Profile) -> list[HolidayWindow]:
        _, windows = await self._load_kb(user.id)
        return windows

    async def get_active_window(self, user: Profile) -> HolidayWindow | None:
        windows = await self.get_windows(user)
        return next((w for w in reversed(windows) if w.is_active), None)

    async def get_active_window_for_date(
        self, user: Profile, subject_date: date
    ) -> HolidayWindow | None:
        windows = await self.get_windows(user)
        return active_holiday_window_for_date(windows, subject_date)

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    async def _save_kb(
        self,
        user: Profile,
        windows: list[HolidayWindow],
        existing: KnowledgeBase | None,
    ) -> None:
        content: dict[str, Any] = {"windows": [w.to_dict() for w in windows]}
        if existing is not None:
            await self.session.execute(
                update(KnowledgeBase)
                .where(
                    KnowledgeBase.user_id == user.id,
                    KnowledgeBase.section == KB_SECTION,
                )
                .values(is_active=False)
            )
            next_version = existing.version + 1
        else:
            next_version = 1

        self.session.add(
            KnowledgeBase(
                user_id=user.id,
                section=KB_SECTION,
                version=next_version,
                is_active=True,
                source="holiday_manager",
                content=content,
                updated_by_profile_id=user.id,
            )
        )

    # ------------------------------------------------------------------
    # Pause
    # ------------------------------------------------------------------

    async def pause(self, user: Profile, start_date: date, end_date: date) -> PauseResult:
        if start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="start_date must be on or before end_date",
            )

        existing, windows = await self._load_kb(user.id)
        if any(w.is_active for w in windows):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A holiday is already active; resume it before pausing again",
            )

        window = HolidayWindow(
            start_date=start_date,
            end_date=end_date,
            paused_at_utc=_utcnow(),
        )
        windows.append(window)
        await self._save_kb(user, windows, existing)

        skipped = await self._skip_workouts(user.id, start_date, end_date)
        await self.session.commit()
        return PauseResult(window=window, skipped_count=len(skipped))

    async def _skip_workouts(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[PlannedWorkout]:
        active = (
            (
                await self.session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= start_date,
                        PlannedWorkout.workout_date <= end_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

        new_versions: list[PlannedWorkout] = []
        for w in active:
            w.is_active = False
            skipped = PlannedWorkout(
                user_id=user_id,
                plan_block_id=w.plan_block_id,
                workout_date=w.workout_date,
                version=w.version + 1,
                title=w.title,
                workout_type=w.workout_type,
                status="skipped",
                is_active=True,
                planned_duration_min=w.planned_duration_min,
                intensity_target=w.intensity_target,
                structured_workout=w.structured_workout,
                source=HOLIDAY_PAUSE_SOURCE,
            )
            self.session.add(skipped)
            new_versions.append(skipped)

        return new_versions

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    async def resume(self, user: Profile) -> ResumeResult:
        existing, windows = await self._load_kb(user.id)
        try:
            active_idx, window = next((i, w) for i, w in enumerate(windows) if w.is_active)
        except StopIteration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active holiday window to resume from",
            )

        window.resumed_at_utc = _utcnow()
        windows[active_idx] = window
        await self._save_kb(user, windows, existing)

        label = "Build1"
        regenerated: list[PlannedWorkout] = []

        pre_block = await self.session.scalar(
            select(PlanBlock)
            .where(
                PlanBlock.user_id == user.id,
                PlanBlock.end_date < window.start_date,
                PlanBlock.block_type == "build",
            )
            .order_by(PlanBlock.end_date.desc())
        )

        if pre_block is not None and pre_block.sequence_index is not None:
            seq = pre_block.sequence_index
            label = continuation_label(seq, "build")
            week_num = continuation_week_number(seq, "build")

            post_block = await self.session.scalar(
                select(PlanBlock)
                .where(
                    PlanBlock.user_id == user.id,
                    PlanBlock.start_date >= window.end_date,
                    PlanBlock.block_type == "build",
                )
                .order_by(PlanBlock.start_date.asc())
            )

            if post_block is not None:
                regenerated = await self._regenerate_block(user.id, post_block, week_num)

        await self.session.commit()
        return ResumeResult(
            window=window,
            continuation_label=label,
            regenerated_count=len(regenerated),
        )

    async def _regenerate_block(
        self,
        user_id: uuid.UUID,
        block: PlanBlock,
        week_number: int,
    ) -> list[PlannedWorkout]:
        """Regenerate a build block's planned workouts using the continuation template."""
        templates = _block_templates("build", week_number)

        existing = (
            (
                await self.session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= block.start_date,
                        PlannedWorkout.workout_date <= block.end_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

        max_versions: dict[date, int] = {w.workout_date: w.version for w in existing}
        for w in existing:
            w.is_active = False

        new_workouts: list[PlannedWorkout] = []
        for template in templates:
            workout_date = block.start_date + timedelta(days=template.day_offset)
            current_v = max_versions.get(workout_date, 0)
            new_w = PlannedWorkout(
                user_id=user_id,
                plan_block_id=block.id,
                workout_date=workout_date,
                version=current_v + 1,
                title=template.title,
                workout_type=template.workout_type,
                status="planned",
                is_active=True,
                planned_duration_min=template.planned_duration_min,
                intensity_target=template.intensity_target,
                structured_workout=template.structured_workout,
                source=HOLIDAY_RESUME_SOURCE,
            )
            self.session.add(new_w)
            new_workouts.append(new_w)

        return new_workouts
