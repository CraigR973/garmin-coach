"""One loop for the scheduler's per-profile jobs (Batch 341, CR327-04).

Nine scheduled jobs run the same shape: for each profile, do the job's step, and if
it fails, roll back, raise the job's own alert and carry on with the next profile.
Each hand-wrote the same rules, and two broke one of them (CR327-02): a failure
handler read an attribute of the profile *after* the rollback had expired it, so
the handler raised ``MissingGreenlet`` and the failure it existed to report became
an outage of the whole job (``scheduler.run_trend_narratives``, 20 Sep).

The rules, kept here once:

1. A previous profile's rollback expired every loaded instance, so each profile is
   made usable again before its step (``restore_after_rollback``).
2. What a failure handler may log is read before the step runs, into a
   :class:`ProfileRef` that a rollback cannot expire.
3. A failure rolls the session back before anything else touches it, and the
   profile is reloaded before the handler runs, so a handler that passes the
   profile on (the weekly review records its failure on it) gets a usable one.
4. The job's own handler then runs, with its own alert route.
5. The next profile runs regardless. An exception from the handler itself still
   escapes, as it did before: a failure path that fails is the job's failure.

Steps take the session as an argument rather than closing over one, so moving to a
session per profile (Batch 209's trigger, a second user) changes this module alone.

Not every loop in ``scheduler.py`` belongs here. The batch loops (Hive poll, evening
nudge, evening alerts, activity poll) are deliberately all-or-nothing in one
transaction; the morning jobs leave isolation to ``MorningBriefPipeline``; the wake
check isolates each Garmin fetch; fan control serves one profile.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.profile import Profile
from src.services.session_recovery import restore_after_rollback

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ProfileRef:
    """A profile's identity, read before its step runs, so a rollback cannot expire it."""

    id: uuid.UUID
    timezone: str | None
    #: The job's subject day for this profile, when the job passes ``today``.
    today: date | None = None


@dataclass
class ProfileLoopResult:
    """How many profiles ran, and which of them failed."""

    profiles: int = 0
    failed: list[uuid.UUID] = field(default_factory=list)

    @property
    def failures(self) -> int:
        return len(self.failed)


ProfileStep = Callable[[AsyncSession, Profile, ProfileRef], Awaitable[None]]
FailureHandler = Callable[[AsyncSession, Profile, ProfileRef, Exception], Awaitable[None]]


async def for_each_active_profile(
    job: str,
    step: ProfileStep,
    *,
    session: AsyncSession,
    profiles: Iterable[Profile],
    on_failure: FailureHandler,
    today: Callable[[Profile], date] | None = None,
) -> ProfileLoopResult:
    """Run ``step`` once per profile, a failure isolated to its profile.

    ``today`` computes the job's subject day once per profile, before the step, so the
    step and the failure handler agree on it. ``on_failure`` runs inside the exception
    handler, so ``log.exception`` and ``exc_info=True`` see the failure.
    """

    result = ProfileLoopResult()
    for profile in profiles:
        await restore_after_rollback(session, profile)
        ref = ProfileRef(
            id=profile.id,
            timezone=profile.timezone,
            today=today(profile) if today is not None else None,
        )
        result.profiles += 1
        try:
            await step(session, profile, ref)
        except Exception as exc:
            await session.rollback()
            result.failed.append(ref.id)
            log.warning("profile step failed", job=job, profile_id=str(ref.id))
            await restore_after_rollback(session, profile)
            await on_failure(session, profile, ref, exc)
    return result
