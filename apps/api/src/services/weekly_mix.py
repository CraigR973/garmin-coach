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

# Not imported from a shared module — every service that needs it defines its own
# (executable_coaching.py, daily_loop.py, post_workout_analysis.py); matching that
# convention rather than introducing a new shared-constants import here.
WORKOUT_STATUS_SKIPPED = "skipped"

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
    """A single bike session positioned in the week, with its completion state.

    ``version`` and ``skipped`` exist so the reducer can collapse a version chain
    on its own (Batch 213): the database is expected to hold exactly one active
    row per ``workout_date``, but a supersede bug can leave more than one, and the
    reducer must be robust to that rather than trust it silently.
    """

    workout_date: date
    workout_type: str
    completed: bool
    skipped: bool = False
    version: int = 1

    @property
    def bucket(self) -> str | None:
        return mix_bucket(self.workout_type)


@dataclass(frozen=True)
class MixBucketStatus:
    """Per-bucket accounting for one week.

    ``basis`` is Batch 217: one readable sentence saying how ``target`` and
    ``done`` were reached. On 2026-08-15 Mark challenged this exact figure —
    *"Not sure where you're getting this from 'VO2 has 1 of a 2-session target
    done' - There is only ever 1 vo2 session in my weekly mix"* — and the coach
    could only say the app had recorded a 2 and that the 2 looked wrong. It
    could not say that ``target`` is a count of his own week's sessions rather
    than a standing quota, which is the whole of what he was asking.
    """

    bucket: str
    label: str
    target: int
    done: int
    due: int
    remaining_planned: int
    at_risk: bool
    basis: str

    def to_packet(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "label": self.label,
            "target": self.target,
            "done": self.done,
            "due": self.due,
            "remainingPlanned": self.remaining_planned,
            "atRisk": self.at_risk,
            "basis": self.basis,
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


def _dedupe_by_date(
    sessions: Sequence[MixSession],
) -> tuple[list[MixSession], list[MixSession]]:
    """One session per ``workout_date`` (Batch 213), plus what was dropped.

    A version chain is scoped to a single date (confirmed: every re-slot/edit
    path computes its next version from ``MAX(version) WHERE workout_date =
    ...``), so two rows sharing a date are always the same slot's history, never
    two distinct sessions. The highest version wins — but only among the
    non-``skipped`` rows: a skipped session was never delivered, so it is not a
    plan commitment and must not count toward ``target`` even when it is the
    only row left for that date (a lone, never-superseded skip).

    Batch 217 returns the skipped-only dates as well. Dropping them is correct
    and invisible: Mark sees a skipped session on the Week page and a target
    that does not count it, with nothing joining the two. That silent
    subtraction is the same shape as the 2026-08-11 chain he challenged, so the
    basis sentence names it rather than leaving him to infer it.
    """
    by_date: dict[date, list[MixSession]] = {}
    for session in sessions:
        by_date.setdefault(session.workout_date, []).append(session)
    deduped: list[MixSession] = []
    skipped_only: list[MixSession] = []
    for day_sessions in by_date.values():
        live = [s for s in day_sessions if not s.skipped]
        if not live:
            skipped_only.append(max(day_sessions, key=lambda s: s.version))
            continue
        deduped.append(max(live, key=lambda s: s.version))
    return deduped, skipped_only


def _day_label(value: date) -> str:
    return f"{value:%a} {value.day} {value:%b}"


def _bucket_basis(
    *,
    label: str,
    target: int,
    done: int,
    due: int,
    remaining: int,
    at_risk: bool,
    skipped_dates: Sequence[date],
    week_start: date,
) -> str:
    """One readable sentence for how a bucket's numbers were reached (Batch 217).

    Deliberately a sentence and not a set of fields. The coach is forbidden from
    repeating the app's internal names to Mark, so a basis that cannot be read
    out loud is a basis that does not exist — the lesson from the 2026-08-20
    ``batch_5_seed`` answer.
    """
    window = f"{_day_label(week_start)} to {_day_label(week_start + timedelta(days=6))}"
    if target == 0:
        base = (
            f"Your plan carries no {label} session in the week of {window}, "
            "so there is no target to fall short of."
        )
    else:
        sessions = "session" if target == 1 else "sessions"
        base = (
            f"Counted from your own plan for the week of {window}: {target} {label} "
            f"{sessions} scheduled, {done} completed. The target is your own week's "
            "count, not a standing weekly quota."
        )
    if skipped_dates:
        days = ", ".join(_day_label(day) for day in sorted(skipped_dates))
        base += (
            f" A {label} session you skipped ({days}) is not counted, "
            "because a skipped session was never a commitment."
        )
    if at_risk:
        base += f" {due} still owed with {remaining} left scheduled, so the bucket reads short."
    return base


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

    Sessions are deduped to one per date before counting (:func:`_dedupe_by_date`)
    so a stray duplicate/superseded row — the data-integrity bug this accounting
    must not depend on being already fixed — cannot inflate ``target``.

    Each bucket also carries a ``basis`` (Batch 217): the same counting, said in
    a sentence, so the number can be defended when Mark asks where it came from
    instead of being conceded as probably wrong.

    Pure: no database, no clock. ``eased_bucket`` is the only channel through
    which the verdict's easing of today's hard session enters the accounting.
    """
    sessions, skipped_only = _dedupe_by_date(sessions)
    week_start = subject_date - timedelta(days=subject_date.weekday())
    buckets: list[MixBucketStatus] = []
    for name in MIX_BUCKETS:
        in_bucket = [s for s in sessions if s.bucket == name]
        skipped_dates = [s.workout_date for s in skipped_only if s.bucket == name]
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
        at_risk = due > remaining
        label = bucket_label(name)
        buckets.append(
            MixBucketStatus(
                bucket=name,
                label=label,
                target=target,
                done=done,
                due=due,
                remaining_planned=remaining,
                at_risk=at_risk,
                basis=_bucket_basis(
                    label=label,
                    target=target,
                    done=done,
                    due=due,
                    remaining=remaining,
                    at_risk=at_risk,
                    skipped_dates=skipped_dates,
                    week_start=week_start,
                ),
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
                skipped=w.status == WORKOUT_STATUS_SKIPPED,
                version=w.version,
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
