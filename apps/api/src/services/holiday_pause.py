"""Holiday pause/resume — Batch 15, reworked by Batch 290.

A holiday window is treated as a recovery-week equivalent: planned workouts
inside it are versioned as ``status='skipped'`` with ``source='holiday_pause'``.

**A holiday ends by itself (Batch 290).** A window is running on a day only if
it has not been closed by hand *and* that day is on or before its end date — see
:meth:`HolidayWindow.is_active_on`. Before this, a window stayed "active" until
someone pressed Resume, so Mark's 12-16 Jul 2026 holiday was still active in
September and the app refused to let him enter a new one.

**Resume means "I'm back early", and it never rewrites the plan.** It closes the
window at the day Mark returns (or removes it if the holiday had not started) and
restores the sessions the pause skipped from that day on. Batch 15 also
regenerated the first build week after the holiday from the app's generic 2121
templates; every active planned session is now Mark's own imported plan or his
edits of it, so that step could only overwrite what he wrote — and because it
keyed on the window's original dates, resuming a stale window would have rewritten
a week he had already ridden. It is removed (Decision #351).

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

from src.models.coaching import KnowledgeBase, PlannedWorkout
from src.models.profile import Profile
from src.services.profile_clock import profile_today

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

    def is_active_on(self, day: date) -> bool:
        """True while the holiday is running on ``day``.

        It has not been closed by hand, and ``day`` is on or before its end date.
        There is deliberately no date-free "is active": that property is what let
        a July holiday stay active into September.
        """
        return self.resumed_at_utc is None and day <= self.end_date


def holiday_windows_covering_date(
    windows: Sequence[HolidayWindow], subject_date: date
) -> list[HolidayWindow]:
    """Return the stored holiday windows that cover ``subject_date``.

    Historical/resumed windows intentionally remain eligible: analysis packets
    use this helper when reconstructing the truth for a past date.
    """
    return [window for window in windows if window.start_date <= subject_date <= window.end_date]


def holiday_windows_away_overnight(
    windows: Sequence[HolidayWindow], subject_date: date
) -> list[HolidayWindow]:
    """Return the stored holiday windows where Mark is still away *that night*.

    Overnight away is end-exclusive: on ``end_date`` Mark is home that evening,
    so the climate/bedroom subsystem should resume for that night even though the
    day's plan and morning "last-night" reads still treat the holiday as active.
    """
    return [window for window in windows if window.start_date <= subject_date < window.end_date]


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
            if window.is_active_on(subject_date)
        ),
        None,
    )


def overnight_away_window_for_date(
    windows: Sequence[HolidayWindow], subject_date: date
) -> HolidayWindow | None:
    """Return the active holiday window when Mark is still away that night."""
    return next(
        (
            window
            for window in reversed(holiday_windows_away_overnight(windows, subject_date))
            if window.is_active_on(subject_date)
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
    #: Sessions the pause had skipped, from the return day on, that are back.
    restored_count: int
    #: The holiday had not started, so it was removed rather than shortened.
    cancelled: bool = False


def is_build1(sequence_index: int) -> bool:
    """True if this build block is the first in its 2121 build pair.

    In the seeded 13-week 2121 slate the pairs are at sequence indexes
    (1,2), (4,5), (7,8), (10,11).  (S-1) % 3 == 0 → Build1; == 1 → Build2.
    """
    return (sequence_index - 1) % 3 == 0


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

    async def get_active_window(
        self, user: Profile, *, today: date | None = None
    ) -> HolidayWindow | None:
        """The holiday running today, in Mark's own timezone, if there is one."""
        windows = await self.get_windows(user)
        day = today or profile_today(user)
        return next((w for w in reversed(windows) if w.is_active_on(day)), None)

    async def get_active_window_for_date(
        self, user: Profile, subject_date: date
    ) -> HolidayWindow | None:
        windows = await self.get_windows(user)
        return active_holiday_window_for_date(windows, subject_date)

    async def get_overnight_away_window_for_date(
        self, user: Profile, subject_date: date
    ) -> HolidayWindow | None:
        windows = await self.get_windows(user)
        return overnight_away_window_for_date(windows, subject_date)

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

    async def pause(
        self,
        user: Profile,
        start_date: date,
        end_date: date,
        *,
        today: date | None = None,
    ) -> PauseResult:
        if start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="start_date must be on or before end_date",
            )

        existing, windows = await self._load_kb(user.id)
        day = today or profile_today(user)
        if any(w.is_active_on(day) for w in windows):
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

    async def resume(
        self,
        user: Profile,
        *,
        today: date | None = None,
        now_utc: datetime | None = None,
    ) -> ResumeResult:
        """Mark is back early: close the window at his return and restore his plan.

        The window is shortened to end the day before he returns, so a later read
        of those days does not think he was away; if he returns on or before its
        first day it is removed, because the holiday never happened. The sessions
        the pause skipped from his return day to the original end come back as they
        were planned. Nothing outside the holiday is touched.
        """
        existing, windows = await self._load_kb(user.id)
        day = today or profile_today(user)
        try:
            active_idx, window = next((i, w) for i, w in enumerate(windows) if w.is_active_on(day))
        except StopIteration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active holiday window to resume from",
            )

        original_end = window.end_date
        window.resumed_at_utc = now_utc or _utcnow()
        cancelled = day <= window.start_date
        if cancelled:
            windows.pop(active_idx)
        else:
            window.end_date = min(window.end_date, day - timedelta(days=1))
            windows[active_idx] = window
        await self._save_kb(user, windows, existing)

        restored = await self._restore_skipped(user.id, day, original_end)
        await self.session.commit()
        return ResumeResult(window=window, restored_count=len(restored), cancelled=cancelled)

    async def _restore_skipped(
        self, user_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[PlannedWorkout]:
        """Bring back the sessions the pause skipped between two dates, inclusive.

        Only rows the pause itself wrote (``source='holiday_pause'``, still skipped)
        are touched; each is versioned back to a planned session with the same
        content, the version-as-slot convention the pause used.
        """
        skipped = (
            (
                await self.session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= from_date,
                        PlannedWorkout.workout_date <= to_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.source == HOLIDAY_PAUSE_SOURCE,
                        PlannedWorkout.status == "skipped",
                    )
                )
            )
            .scalars()
            .all()
        )

        restored: list[PlannedWorkout] = []
        for w in skipped:
            w.is_active = False
            back = PlannedWorkout(
                user_id=user_id,
                plan_block_id=w.plan_block_id,
                workout_date=w.workout_date,
                version=w.version + 1,
                title=w.title,
                workout_type=w.workout_type,
                status="planned",
                is_active=True,
                planned_duration_min=w.planned_duration_min,
                intensity_target=w.intensity_target,
                structured_workout=w.structured_workout,
                source=HOLIDAY_RESUME_SOURCE,
            )
            self.session.add(back)
            restored.append(back)
        return restored
