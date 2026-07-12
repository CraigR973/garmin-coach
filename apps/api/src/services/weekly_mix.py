"""Weekly-mix maintenance & dynamic rebalancing (Batch 70, #143).

Mark's own plan carries a deliberate weekly bike mix — **VO2×1, Sweet-Spot×1,
Zone-2×3** — and a masters athlete keeps top-end fitness on that small dose of
quality work. When a low-readiness morning eases or drops a hard session, the
week can quietly fall short of that mix without anyone noticing (observation 4).

This module answers "did I keep my mix this week, and if today's hard session is
being dropped, is it made up or not?" as **advisory accounting** over the rows
that already exist — no migration, no auto-scheduling.

  * :func:`summarize_weekly_mix` is a pure, deterministic reducer over the week's
    planned + completed bike sessions. It reports, per bucket, the plan's
    ``target`` (derived from his own week — not a hardcoded number), what's
    ``done``, what's still ``due``, and whether the bucket is ``at_risk`` of
    missing target given what's genuinely still scheduled.
  * The re-patch decision reuses the Batch 66 swap-first engine
    (:func:`weekly_restructure.plan_swap_first`) with Mark's protected days
    (Mon/Fri) applied: a readiness-dropped hard session either moves to a sound
    later slot this week, or the coach says plainly it won't be made up — the
    **soft, readiness-gated quota** (mix protected, readiness vetoes, shortfall
    explained), never a forced session.

:class:`WeeklyMixService` reads the week once and assembles the packet the
morning verdict carries; the pure reducer keeps the rules unit-testable without a
database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import PlannedWorkout
from src.models.profile import Profile
from src.services.weekly_restructure import (
    CATEGORY_ENDURANCE,
    CATEGORY_RECOVERY,
    CATEGORY_SWEET_SPOT,
    CATEGORY_TEMPO,
    CATEGORY_THRESHOLD,
    CATEGORY_VO2,
    PROTECTED_WEEKDAYS,
    SwapSuggestion,
    WeekItem,
    categorize,
    plan_swap_first,
)
from src.services.workout_completion import WORKOUT_STATUS_COMPLETED

# The three tracked mix buckets. Quality (hard) work is VO2 and Sweet-Spot; the
# rest of the week is aerobic Zone-2 volume. Threshold rides — quality, absent
# from Mark's current plan — count with Sweet-Spot; tempo/recovery count as Z2.
MIX_VO2 = "vo2"
MIX_SWEET_SPOT = "sweet_spot"
MIX_Z2 = "z2"
MIX_BUCKETS: tuple[str, ...] = (MIX_VO2, MIX_SWEET_SPOT, MIX_Z2)
HARD_BUCKETS: frozenset[str] = frozenset({MIX_VO2, MIX_SWEET_SPOT})

_BUCKET_LABELS = {
    MIX_VO2: "VO2",
    MIX_SWEET_SPOT: "Sweet Spot",
    MIX_Z2: "Zone 2",
}
_CATEGORY_TO_BUCKET = {
    CATEGORY_VO2: MIX_VO2,
    CATEGORY_SWEET_SPOT: MIX_SWEET_SPOT,
    CATEGORY_THRESHOLD: MIX_SWEET_SPOT,
    CATEGORY_TEMPO: MIX_Z2,
    CATEGORY_ENDURANCE: MIX_Z2,
    CATEGORY_RECOVERY: MIX_Z2,
}


def bucket_label(bucket: str) -> str:
    return _BUCKET_LABELS.get(bucket, bucket)


def mix_bucket(workout_type: str) -> str | None:
    """Map a workout type to its weekly-mix bucket, or ``None`` for a non-bike
    session (strength/mobility never counts toward the bike mix)."""
    if not workout_type.startswith("bike_"):
        return None
    return _CATEGORY_TO_BUCKET.get(categorize(workout_type))


@dataclass(frozen=True)
class MixSession:
    """A single bike session positioned in the week, with its completion state."""

    workout_date: date
    workout_type: str
    completed: bool

    @property
    def bucket(self) -> str | None:
        return mix_bucket(self.workout_type)


@dataclass(frozen=True)
class MixBucketStatus:
    """Per-bucket accounting for one week."""

    bucket: str
    label: str
    target: int
    done: int
    due: int
    remaining_planned: int
    at_risk: bool

    def to_packet(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "label": self.label,
            "target": self.target,
            "done": self.done,
            "due": self.due,
            "remainingPlanned": self.remaining_planned,
            "atRisk": self.at_risk,
        }


@dataclass(frozen=True)
class MixShortfall:
    """The dropped-hard-session outcome the verdict narrates.

    Set only when a low-readiness morning eases today's hard bike session. It
    records whether that session is re-patched to a sound later day this week or
    explicitly not made up — never a silent loss.
    """

    bucket: str
    label: str
    repatched: bool
    move_to_weekday: str | None
    move_to_date: date | None
    message: str

    def to_packet(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "label": self.label,
            "repatched": self.repatched,
            "moveToWeekday": self.move_to_weekday,
            "moveToDate": self.move_to_date.isoformat() if self.move_to_date else None,
            "message": self.message,
        }


@dataclass(frozen=True)
class WeeklyMix:
    week_start: date
    subject_date: date
    buckets: list[MixBucketStatus]
    shortfall: MixShortfall | None = None

    def bucket(self, name: str) -> MixBucketStatus | None:
        return next((b for b in self.buckets if b.bucket == name), None)

    @property
    def at_risk_buckets(self) -> list[MixBucketStatus]:
        return [b for b in self.buckets if b.at_risk]

    def plan_adjustments(self) -> list[str]:
        """The verdict text this mix contributes (the shortfall message, if any)."""
        return [self.shortfall.message] if self.shortfall else []

    def to_packet(self) -> dict[str, Any]:
        return {
            "weekStart": self.week_start.isoformat(),
            "subjectDate": self.subject_date.isoformat(),
            "buckets": [b.to_packet() for b in self.buckets],
            "shortfall": self.shortfall.to_packet() if self.shortfall else None,
        }


def summarize_weekly_mix(
    sessions: Sequence[MixSession],
    *,
    subject_date: date,
    eased_bucket: str | None = None,
) -> WeeklyMix:
    """Deterministic weekly-mix accounting over the week's bike sessions.

    ``target`` for each bucket is the count the week's own plan carries (so a
    recovery week with no VO2 has ``target=0`` and never reads short). ``done``
    counts completed sessions. ``remaining_planned`` counts sessions that will
    still genuinely happen as that bucket — not completed, dated today or later,
    and excluding the single hard session ``eased_bucket`` names as being dropped
    by today's verdict. A bucket is ``at_risk`` when what's still owed
    (``due = target - done``) exceeds what's still scheduled.

    Pure: no database, no clock. ``eased_bucket`` is the only channel through
    which the verdict's easing of today's hard session enters the accounting.
    """
    week_start = subject_date - timedelta(days=subject_date.weekday())
    buckets: list[MixBucketStatus] = []
    for name in MIX_BUCKETS:
        in_bucket = [s for s in sessions if s.bucket == name]
        target = len(in_bucket)
        done = sum(1 for s in in_bucket if s.completed)
        remaining = 0
        for session in in_bucket:
            if session.completed:
                continue
            if session.workout_date < subject_date:
                # A past, uncompleted session is a miss, not a future slot.
                continue
            if name == eased_bucket and session.workout_date == subject_date:
                # Today's hard session is being eased away — it no longer counts
                # as a scheduled hard slot (that's the whole shortfall).
                continue
            remaining += 1
        due = max(target - done, 0)
        buckets.append(
            MixBucketStatus(
                bucket=name,
                label=bucket_label(name),
                target=target,
                done=done,
                due=due,
                remaining_planned=remaining,
                at_risk=due > remaining,
            )
        )
    return WeeklyMix(week_start=week_start, subject_date=subject_date, buckets=buckets)


def build_shortfall(
    *,
    eased_bucket: str,
    swap: SwapSuggestion | None,
) -> MixShortfall:
    """Turn a dropped hard bucket + the re-patch result into the coach's message.

    ``swap`` is the Batch 66 swap-first result (already computed with protected
    days applied): non-``None`` means the dropped session can move to a sound
    later day this week; ``None`` means no sound later slot exists.
    """
    label = bucket_label(eased_bucket)
    if swap is not None:
        weekday = swap.move_to_date.strftime("%A")
        message = (
            f"You'd be a {label} session short this week — moving it to {weekday} "
            "keeps the week's quality work instead of quietly dropping it."
        )
        return MixShortfall(
            bucket=eased_bucket,
            label=label,
            repatched=True,
            move_to_weekday=weekday,
            move_to_date=swap.move_to_date,
            message=message,
        )
    message = (
        f"No {label} session this week — that's the right call on this recovery, "
        "not a gap to force. The mix is protected, but readiness gets the veto, "
        "and the quality work resumes once you've recovered."
    )
    return MixShortfall(
        bucket=eased_bucket,
        label=label,
        repatched=False,
        move_to_weekday=None,
        move_to_date=None,
        message=message,
    )


class WeeklyMixService:
    """Assemble the weekly-mix packet the morning verdict carries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _week_sessions(
        self, player: Profile, week_start: date
    ) -> tuple[list[MixSession], list[WeekItem]]:
        week_end = week_start + timedelta(days=6)
        workouts = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date >= week_start,
                        PlannedWorkout.workout_date <= week_end,
                    )
                    .order_by(PlannedWorkout.workout_date.asc())
                )
            )
            .scalars()
            .all()
        )
        sessions = [
            MixSession(
                workout_date=w.workout_date,
                workout_type=w.workout_type,
                completed=w.status == WORKOUT_STATUS_COMPLETED,
            )
            for w in workouts
            if w.workout_type.startswith("bike_")
        ]
        items = [
            WeekItem(
                workout_id=w.id,
                workout_date=w.workout_date,
                title=w.title,
                workout_type=w.workout_type,
            )
            for w in workouts
        ]
        return sessions, items

    async def summarize_for_verdict(
        self,
        player: Profile,
        subject_date: date,
        *,
        verdict_status: str,
        swap: SwapSuggestion | None,
        protected_weekdays: frozenset[int] = PROTECTED_WEEKDAYS,
        suppress_today_easing: bool = False,
    ) -> WeeklyMix:
        """Compute the week's mix and, on a cautious morning that eases today's
        hard bike session, the re-patch/"not this week" shortfall.

        ``swap`` is the swap-first suggestion the morning packet already computed
        (Batch 66). It *is* the re-patch when present; when it is ``None`` the
        engine is re-run here so a hard drop with no accompanying swap lead still
        resolves to an explicit "not this week" (belt-and-braces, and it lets the
        shortfall stand alone in tests). Nothing is mutated or scheduled.

        ``suppress_today_easing`` is the Batch 98 rest-day guard: the weekly
        accounting remains visible, but a paused holiday session cannot become a
        readiness-driven shortfall or re-patch suggestion.
        """
        week_start = subject_date - timedelta(days=subject_date.weekday())
        sessions, items = await self._week_sessions(player, week_start)

        eased_bucket = None
        if not suppress_today_easing:
            eased_bucket = _eased_bucket(
                sessions, subject_date=subject_date, verdict_status=verdict_status
            )
        mix = summarize_weekly_mix(sessions, subject_date=subject_date, eased_bucket=eased_bucket)
        if eased_bucket is None:
            return mix

        repatch = swap or plan_swap_first(
            items, subject_date=subject_date, protected_weekdays=protected_weekdays
        )
        shortfall = build_shortfall(eased_bucket=eased_bucket, swap=repatch)
        return WeeklyMix(
            week_start=mix.week_start,
            subject_date=mix.subject_date,
            buckets=mix.buckets,
            shortfall=shortfall,
        )


def _eased_bucket(
    sessions: Sequence[MixSession],
    *,
    subject_date: date,
    verdict_status: str,
) -> str | None:
    """The hard bucket whose today session the verdict is easing, if any.

    Only an Amber/Red morning eases a session, and only an as-yet-uncompleted
    hard bike session on ``subject_date`` counts (a session already ridden isn't
    being dropped).
    """
    if verdict_status not in {"Amber", "Red"}:
        return None
    for session in sessions:
        if (
            session.workout_date == subject_date
            and not session.completed
            and session.bucket in HARD_BUCKETS
        ):
            return session.bucket
    return None
