"""One morning-brief pipeline behind all three triggers (Batch 251, CR236-02).

The most valuable path in the product used to be implemented three times in two
modules, with different transaction semantics, different failure recording and
different names for the same thing:

* ``scheduler.run_morning_sync`` — the wake job: sync inputs + "good morning"
  nudge, no generation.
* ``routers/daily_loop._generate_brief_after_checkin`` — the check-in: every step
  ``commit=False`` under one transaction with a single terminal commit, plus a
  ``BriefGenerationStatus`` write and an admin alert in the handler.
* ``scheduler.run_morning_weather_sync`` — the 11:00 backstop: every step commits
  independently and rolls back on error, with **no** ``BriefGenerationStatus``
  write of any kind.

Every morning-path defect in the ledger is drift between those three, each fixed
in whichever copy it was noticed in — Batch 141 added the failure card to the
router path only, Batch 144 derived a stale ``generating`` at read time because
no writer owned the transition, Batch 222 taught the router to sync inputs by
importing a *private scheduler helper*, and Batch 232.1 had to add the same
``GenerationRequestInProgress`` handler in two places with two different bodies.

So the differences that are real become a **policy**, declared at the call site
and readable as a table, and everything else becomes one implementation:

============================  ===============  ===============
                              check-in         11:00 backstop
============================  ===============  ===============
transaction contract          terminal         per step
a failed step                 aborts the run   is isolated
regenerates an existing read  yes (``force``)  no
missing sleep tolerated       after 11:00      always
pushes an unchanged brief     yes              no
writes generation status      yes              yes (Batch 251)
precomputes drivers           no               yes
============================  ===============  ===============

``CommitPolicy`` names both halves of the transaction contract on purpose: who
commits and what a failure costs are one decision, not two. Terminal means the
brief and its consequences are one artifact — if the proposals fail, the brief is
not half-written, and Mark gets a retryable failure card. Per step means the
backstop is a multi-profile loop in which one profile's bad step must not roll
back another's good inputs.

The one asymmetry that was not deliberate is now closed: a backstop generation
failure wrote no status row, so it produced no failure card and no Retry
affordance — it was survivable only because Mark could still check in and take
the router path. Both generating triggers now record the same outcome through the
same owner.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DAILY_METRIC_PHASE_SETTLED,
    Analysis,
)
from src.models.profile import Profile
from src.services.anthropic_text import AnthropicApiError
from src.services.brief_generation_status import BriefGenerationStatusService
from src.services.environment_sync import (
    EnvironmentSyncService,
    OpenMeteoClient,
    WeatherRequest,
)
from src.services.executable_coaching import ExecutableCoachingService
from src.services.garmin_sync import (
    GarminConnectClient,
    GarminDailyPayloads,
    GarminSyncService,
)
from src.services.generation_requests import GenerationRequestInProgress
from src.services.insights import InsightsService
from src.services.morning_analysis import MorningAnalysisClient, MorningAnalysisService
from src.services.morning_inputs import morning_input_presence
from src.services.nudge_alerts import NudgeAlertService
from src.services.profile_clock import profile_now, profile_today
from src.services.retry import retry_async, retry_sync
from src.services.session_recovery import restore_after_rollback
from src.services.tts_pregenerate import pregenerate_brief_audio
from src.services.wake_detection import BACKSTOP

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class MorningInputsNotReady(RuntimeError):
    """A successful model read cannot start from an unsynced wake date."""


class MorningTrigger(StrEnum):
    """Which of the three doors this run came through."""

    WAKE = "wake"
    CHECKIN = "checkin"
    BACKSTOP = "backstop"


class CommitPolicy(StrEnum):
    """Who owns the transaction boundary, and what a failed step costs.

    ``TERMINAL`` — nothing commits until the whole run does, so a failure aborts
    the run and leaves no half-written brief. ``PER_STEP`` — each step commits on
    success, so a failure is isolated and the ladder continues.
    """

    TERMINAL = "terminal"
    PER_STEP = "per_step"


@dataclass(frozen=True, slots=True)
class MorningBriefPolicy:
    """The differences between the two generating triggers, named."""

    trigger: MorningTrigger
    commit: CommitPolicy
    #: Regenerate a read that already exists (the check-in folds in his notes).
    force_regenerate: bool
    #: ``None`` means "tolerate a missing sleep session only after the backstop
    #: hour", which is the check-in's clock-dependent rule.
    allow_missing_sleep: bool | None
    #: Push "your brief is ready" even when this run generated nothing new.
    push_when_unchanged: bool
    #: Precompute the 120-day driver correlations (Batch 62.2).
    precompute_drivers: bool


CHECKIN_POLICY = MorningBriefPolicy(
    trigger=MorningTrigger.CHECKIN,
    commit=CommitPolicy.TERMINAL,
    force_regenerate=True,
    allow_missing_sleep=None,
    push_when_unchanged=True,
    precompute_drivers=False,
)

BACKSTOP_POLICY = MorningBriefPolicy(
    trigger=MorningTrigger.BACKSTOP,
    commit=CommitPolicy.PER_STEP,
    force_regenerate=False,
    allow_missing_sleep=True,
    push_when_unchanged=False,
    precompute_drivers=True,
)


@dataclass(frozen=True, slots=True)
class MorningInputResult:
    weather_days: int = 0
    daily_metrics: int = 0
    sleep: int = 0
    failures: int = 0


@dataclass(frozen=True, slots=True)
class WakeNudgeResult:
    sent: bool = False
    #: Today's read already exists (he checked in, or the backstop generated it).
    skipped: bool = False
    failures: int = 0


@dataclass
class MorningBriefOutcome:
    """What one profile's generate attempt did, in the counters both jobs report."""

    generated: bool = False
    existing: bool = False
    #: Another worker holds this artifact scope — not a failure (Batch 232.1).
    deferred: bool = False
    inputs_not_ready: bool = False
    brief_ready_pushes: int = 0
    proposals_regenerated: int = 0
    chronic_deload_proposals: int = 0
    drivers_cached: int = 0
    failures: int = 0
    analysis: Analysis | None = None


async def commit_step(
    session: AsyncSession,
    *,
    step: str,
    profile_id: uuid.UUID | None = None,
    subject_date: date | None = None,
) -> bool:
    """Commit one morning input boundary, restoring the Session on failure."""

    try:
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        log.exception(
            "morning input commit failed",
            step=step,
            profile_id=str(profile_id) if profile_id is not None else None,
            subject_date=subject_date.isoformat() if subject_date is not None else None,
        )
        return False


async def sync_garmin_daily(
    session: AsyncSession,
    profiles: list[Profile],
    *,
    client: GarminConnectClient | None = None,
) -> tuple[int, int, int]:
    """Sync today plus the last three closed Garmin days (429-safe).

    Returns ``(daily_metrics_synced, sleep_synced, failures)``. The fetch is wrapped in an
    exponential-backoff retry so a transient Garmin 429 is survived. Each date
    is isolated, so one failed historical fetch cannot block today's inputs or
    another date's self-heal. Each successful date commits independently.

    This loop is where CI191-02 came from: Garmin returns a closed day's *final*
    training readiness, so the D-1..D-3 pass used to overwrite the wake snapshot
    the verdict had already been computed from. Batch 205 keeps both — today
    writes the ``morning`` row, the closed days write ``settled`` — so the
    re-sync still self-heals a missed morning without rewriting history.
    """
    if not profiles:
        return (0, 0, 0)

    client = client or GarminConnectClient()
    sync_service = GarminSyncService(session)
    daily_synced = 0
    sleep_synced = 0
    failures = 0
    for profile in profiles:
        await restore_after_rollback(session, profile)
        # Batch 242 (CR236-01): hoisted before the *date* loop, not just before
        # the try. Each date is its own recovery boundary, so date N's rollback
        # would otherwise expire the instance that date N+1 reads inside its
        # own try — and the resulting MissingGreenlet escapes the handler.
        profile_id = profile.id
        today = profile_today(profile)
        for offset in range(4):
            subject_date = today - timedelta(days=offset)
            phase = DAILY_METRIC_PHASE_MORNING if offset == 0 else DAILY_METRIC_PHASE_SETTLED
            try:
                payloads: GarminDailyPayloads = await retry_sync(
                    lambda: client.fetch_daily_payloads(subject_date),
                    backoff=2.0,
                )
                result = await sync_service.sync_daily(
                    profile_id,
                    subject_date,
                    payloads,
                    phase=phase,
                    commit=False,
                )
                # One date is one recovery boundary. Committing here means a
                # later bad historical row cannot roll today's good inputs back.
                if await commit_step(
                    session,
                    step="garmin_daily",
                    profile_id=profile_id,
                    subject_date=subject_date,
                ):
                    daily_synced += result.daily_metrics_synced
                    sleep_synced += result.sleep_synced
                else:
                    failures += 1
            except Exception:
                failures += 1
                await session.rollback()
                log.exception(
                    "garmin daily sync failed",
                    profile_id=str(profile_id),
                    subject_date=subject_date.isoformat(),
                )
    return (daily_synced, sleep_synced, failures)


class MorningBriefPipeline:
    """The single owner of the morning path.

    ``policy`` is required for :meth:`generate_brief` and irrelevant to
    :meth:`sync_inputs` / :meth:`send_wake_nudge`, which the wake trigger uses on
    their own.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: MorningBriefPolicy | None = None,
        morning_service: MorningAnalysisService | None = None,
    ) -> None:
        self.session = session
        self._policy = policy
        # Built once and held, so a test can substitute the morning service the
        # way ``regenerate_after_morning_checkin`` used to allow, and so every
        # step reads the same instances.
        self.morning = morning_service or MorningAnalysisService(session)
        self.coaching = ExecutableCoachingService(session)
        self.nudges = NudgeAlertService(session)
        self.insights = InsightsService(session)
        self.status = BriefGenerationStatusService(session)

    @property
    def policy(self) -> MorningBriefPolicy:
        if self._policy is None:  # pragma: no cover - guarded by construction
            raise RuntimeError("this pipeline was built without a generate policy")
        return self._policy

    # -- input sync (all three triggers) -------------------------------------

    async def sync_inputs(
        self,
        profiles: list[Profile],
        *,
        garmin_client: GarminConnectClient | None = None,
        weather_client: OpenMeteoClient | None = None,
    ) -> MorningInputResult:
        """Pull weather + current/finalized Garmin daily data for the given profiles.

        Returns committed counts plus isolated failure count. Weather syncs first, then the
        Garmin daily sync, so the morning verdict reads today's real readiness + sleep
        instead of empty inputs (Batch 18). This helper commits each recoverable step
        and returns the number that degraded without raising past verdict generation.
        """
        session = self.session
        service = EnvironmentSyncService(session)
        weather_days = 0
        failures = 0
        client = weather_client or OpenMeteoClient()
        for profile in profiles:
            await restore_after_rollback(session, profile)
            profile_id = profile.id
            subject_date = profile_today(profile)
            try:
                request = WeatherRequest(
                    latitude=profile.latitude or settings.weather_latitude,
                    longitude=profile.longitude or settings.weather_longitude,
                    timezone=profile.timezone or settings.weather_timezone,
                )
                payload = await retry_async(lambda: client.fetch_daily_payload(request))
                result = await service.sync_weather_daily(
                    profile_id,
                    payload,
                    timezone=request.timezone,
                    commit=False,
                )
                if await commit_step(
                    session,
                    step="weather",
                    profile_id=profile_id,
                    subject_date=subject_date,
                ):
                    weather_days += result.weather_days_synced
                else:
                    failures += 1
            except Exception:
                failures += 1
                await session.rollback()
                log.exception(
                    "morning weather input failed",
                    profile_id=str(profile_id),
                )

        daily_metrics_synced, sleep_synced, garmin_failures = await sync_garmin_daily(
            session, profiles, client=garmin_client
        )
        failures += garmin_failures
        # Keep a guarded phase boundary even though successful dates commit
        # independently; this catches a driver-level failure before analysis begins.
        if not await commit_step(session, step="garmin_phase"):
            failures += 1
        return MorningInputResult(
            weather_days=weather_days,
            daily_metrics=daily_metrics_synced,
            sleep=sleep_synced,
            failures=failures,
        )

    # -- wake trigger ---------------------------------------------------------

    async def send_wake_nudge(self, profile: Profile) -> WakeNudgeResult:
        """Invite a check-in, unless today's read already exists.

        No point inviting a check-in once today's read is already done (he checked
        in, or the backstop generated it) — a cheap DB read guards the push.
        """
        session = self.session
        # ``sync_inputs`` rolls back on a failed weather or Garmin step, so this
        # method's first read is already at risk.
        await restore_after_rollback(session, profile)
        profile_id = profile.id
        subject_date = profile_today(profile)
        if await self.morning.latest_analysis(profile_id, subject_date):
            return WakeNudgeResult(skipped=True)
        try:
            sent = await self.nudges.push_good_morning(
                profile, subject_date=subject_date, commit=False
            )
            if not await commit_step(
                session,
                step="good_morning_nudge",
                profile_id=profile_id,
                subject_date=subject_date,
            ):
                return WakeNudgeResult(sent=sent, failures=1)
            return WakeNudgeResult(sent=sent)
        except Exception:
            await session.rollback()
            log.exception(
                "good morning nudge failed",
                profile_id=str(profile_id),
                subject_date=subject_date.isoformat(),
            )
            return WakeNudgeResult(failures=1)

    # -- the two generating triggers -----------------------------------------

    async def generate_brief(
        self,
        profile: Profile,
        subject_date: date | None = None,
        *,
        client: MorningAnalysisClient | None = None,
    ) -> MorningBriefOutcome:
        """Generate today's brief and everything that follows from it.

        One ladder, one ``GenerationRequestInProgress`` handler, one place that
        records the outcome. What differs between the check-in and the backstop is
        declared by ``self.policy`` and nowhere else.

        ``subject_date`` defaults to the profile's own local date, derived *after*
        the rollback reload — a caller that derived it first would read
        ``profile.timezone`` off an instance ``sync_inputs`` may have expired.
        """
        policy = self.policy
        session = self.session
        outcome = MorningBriefOutcome()
        # ``sync_inputs`` and ``sync_garmin_daily`` both roll back on a failed
        # step, so this instance can already be expired here. Nothing may read an
        # attribute of ``profile`` — including deriving its local date — until
        # this reload has run.
        await restore_after_rollback(session, profile)
        profile_id = profile.id
        if subject_date is None:
            subject_date = profile_today(profile)

        try:
            if not await self._inputs_ready(profile, subject_date):
                raise MorningInputsNotReady

            result = await self.morning.generate_and_store(
                profile,
                subject_date,
                client=client,
                force=policy.force_regenerate,
                # The generate step commits itself under PER_STEP rather than
                # being committed after: ``generate_and_store`` holds a
                # transaction-scoped advisory lock across the paid call, so where
                # that transaction ends is that service's decision to make, not
                # this ladder's.
                commit=policy.commit is CommitPolicy.PER_STEP,
            )
            outcome.analysis = result.analysis
            outcome.generated = result.generated
            outcome.existing = not result.generated
        except GenerationRequestInProgress:
            # Batch 232.1: another worker already holds this artifact scope and is
            # generating today's brief right now. That is not a failure and must
            # not be recorded as one — the holder will write the real outcome, and
            # marking failed here would replace a brief that is being written
            # successfully with a retryable failure card. Leave whatever status
            # row was found exactly as it is; Batch 144's stale-after guard is the
            # backstop if the holder really does die.
            await session.rollback()
            log.info(
                "morning analysis deferred to the in-flight holder",
                trigger=policy.trigger.value,
                profile_id=str(profile_id),
                subject_date=subject_date.isoformat(),
            )
            outcome.deferred = True
            return outcome
        except Exception as exc:
            await session.rollback()
            outcome.failures += 1
            if isinstance(exc, MorningInputsNotReady):
                outcome.inputs_not_ready = True
                log.warning(
                    "morning analysis held for unsynced inputs",
                    trigger=policy.trigger.value,
                    profile_id=str(profile_id),
                    subject_date=subject_date.isoformat(),
                )
            else:
                log.exception(
                    "morning analysis failed",
                    trigger=policy.trigger.value,
                    profile_id=str(profile_id),
                    subject_date=subject_date.isoformat(),
                )
            await self._record_failure(profile_id, subject_date, exc)
            return outcome

        # Everything below has an analysis. Under TERMINAL a step failure aborts
        # the run (there must be no half-written brief); under PER_STEP each step
        # is isolated so one profile's bad step cannot cost it the rest.
        analysis = outcome.analysis
        assert analysis is not None
        try:
            outcome.proposals_regenerated = await self._step_proposals(
                profile, subject_date, analysis, outcome
            )
            outcome.chronic_deload_proposals = await self._step_deload(
                profile, subject_date, analysis, outcome
            )
            if outcome.generated or policy.push_when_unchanged:
                outcome.brief_ready_pushes = await self._step_push(
                    profile, subject_date, analysis, outcome
                )
            if policy.precompute_drivers:
                outcome.drivers_cached = await self._step_drivers(profile, subject_date, outcome)
            await self._mark_ready(profile_id, subject_date)
            if policy.commit is CommitPolicy.TERMINAL:
                await session.commit()
        except Exception as exc:
            await session.rollback()
            outcome.failures += 1
            log.exception(
                "morning brief follow-through failed",
                trigger=policy.trigger.value,
                profile_id=str(profile_id),
                subject_date=subject_date.isoformat(),
            )
            await self._record_failure(profile_id, subject_date, exc)
            return outcome

        # Warms the hosted-voice cache (Batch 116 follow-up) so a consenting
        # user's first "Listen" tap is often already synthesized. Best-effort —
        # never raises, so a Piper hiccup here can't undo the brief commit above,
        # which is why it sits outside the transaction on both triggers.
        if outcome.generated:
            await restore_after_rollback(session, profile, analysis)
            await pregenerate_brief_audio(profile, analysis)
        return outcome

    # -- ladder steps ---------------------------------------------------------

    async def _inputs_ready(self, profile: Profile, subject_date: date) -> bool:
        allow_missing_sleep = self.policy.allow_missing_sleep
        if allow_missing_sleep is None:
            # The check-in's clock-dependent rule: before the backstop hour a
            # lagging but real night keeps the wake poll alive, so a missing
            # sleep session means "not synced yet", not "watch not worn".
            allow_missing_sleep = profile_now(profile).time() >= BACKSTOP
        presence = await morning_input_presence(
            self.session,
            user_id=profile.id,
            subject_date=subject_date,
        )
        return presence.ready_for_read(allow_missing_sleep=allow_missing_sleep)

    async def _step_proposals(
        self,
        profile: Profile,
        subject_date: date,
        analysis: Analysis,
        outcome: MorningBriefOutcome,
    ) -> int:
        async def run() -> int:
            proposals = await self.coaching.regenerate_for_verdict(
                profile, subject_date, analysis=analysis, commit=False
            )
            return len(proposals)

        return await self._isolated(
            run, profile, subject_date, analysis, outcome, step="amber regeneration"
        )

    async def _step_deload(
        self,
        profile: Profile,
        subject_date: date,
        analysis: Analysis,
        outcome: MorningBriefOutcome,
    ) -> int:
        async def run() -> int:
            deloads = await self.coaching.propose_chronic_deload(
                profile, subject_date, analysis=analysis, commit=False
            )
            return len(deloads)

        return await self._isolated(
            run, profile, subject_date, analysis, outcome, step="chronic deload proposal"
        )

    async def _step_push(
        self,
        profile: Profile,
        subject_date: date,
        analysis: Analysis,
        outcome: MorningBriefOutcome,
    ) -> int:
        async def run() -> int:
            sent = await self.nudges.push_brief_ready(
                profile, analysis, subject_date=subject_date, commit=False
            )
            return 1 if sent else 0

        return await self._isolated(
            run, profile, subject_date, analysis, outcome, step="brief-ready push"
        )

    async def _step_drivers(
        self,
        profile: Profile,
        subject_date: date,
        outcome: MorningBriefOutcome,
    ) -> int:
        # Batch 62.2: precompute the 120-day driver correlation once here so
        # GET /api/v1/daily-loop reads it back instead of recomputing on every open.
        async def run() -> int:
            report = await self.insights.record_drivers(profile, as_of=subject_date, commit=False)
            return 1 if report.record_count >= 1 else 0

        return await self._isolated(
            run, profile, subject_date, None, outcome, step="drivers precompute"
        )

    async def _isolated(
        self,
        run: Callable[[], Awaitable[int]],
        profile: Profile,
        subject_date: date,
        analysis: Analysis | None,
        outcome: MorningBriefOutcome,
        *,
        step: str,
    ) -> int:
        """Run one follow-through step under the policy's transaction contract.

        ``TERMINAL`` lets the exception out so the whole run aborts and nothing is
        half-written. ``PER_STEP`` commits the step, and on failure rolls back,
        reloads the instances the rollback expired (CR236-01's worst
        intra-iteration case) and returns zero so the ladder continues.
        """
        if self.policy.commit is CommitPolicy.TERMINAL:
            return await run()
        try:
            value = await run()
        except Exception:
            outcome.failures += 1
            await self.session.rollback()
            log.exception(
                "morning step failed",
                step=step,
                profile_id=str(profile.id),
                subject_date=subject_date.isoformat(),
            )
            await restore_after_rollback(self.session, profile, analysis)
            return 0
        if not await commit_step(
            self.session, step=step, profile_id=profile.id, subject_date=subject_date
        ):
            outcome.failures += 1
            await restore_after_rollback(self.session, profile, analysis)
            return 0
        return value

    # -- the single owner of BriefGenerationStatus ---------------------------

    async def _mark_ready(self, profile_id: uuid.UUID, subject_date: date) -> None:
        """Batch 141: record the ready state atomically with the brief so a cold
        reopen (no client queuedAtMs) still reads "ready", not a stale
        "generating". Batch 251: the backstop writes it too — before this, a
        backstop run left no status row at all.
        """
        await self.status.mark_ready(
            profile_id,
            subject_date,
            commit=self.policy.commit is CommitPolicy.PER_STEP,
        )

    async def _record_failure(
        self, profile_id: uuid.UUID, subject_date: date, exc: BaseException
    ) -> None:
        """Persist the failure so the app shows a retryable error instead of an
        endless "Writing your brief", and alert the operator.

        Batch 141 gave the check-in path this; Batch 248 widened its alert to every
        reason. Batch 251 gives the **backstop** the same contract — it previously
        wrote nothing, so a backstop failure produced no failure card, no Retry
        affordance and no operator alert beyond a degraded ``JobResult``.
        ``inputs`` is excluded from the alert on purpose: that is his watch not
        having synced, a user-state condition rather than a fault, and it is
        already visible to him on the screen.

        Best-effort — a failure to record the failure must never re-raise.
        """
        reason = (
            exc.reason
            if isinstance(exc, AnthropicApiError)
            else "inputs"
            if isinstance(exc, MorningInputsNotReady)
            else "other"
        )
        session = self.session
        try:
            await self.status.mark_failed(profile_id, subject_date, reason=reason, commit=True)
            if reason != "inputs":
                await self.nudges.notify_admin_generation_failure(
                    reason=reason, subject_date=subject_date, commit=True
                )
        except Exception:
            await session.rollback()
            log.exception(
                "recording brief generation failure state failed",
                profile_id=str(profile_id),
                subject_date=subject_date.isoformat(),
            )


async def run_checkin_brief(user_id: uuid.UUID, subject_date: date) -> None:
    """The check-in trigger: sync, then finish today's brief off the request path.

    Batch 222 made the "Syncing your overnight data" stage real — the wake job
    usually wins that idempotent race, and when it did not, the check-in closes the
    gap instead of reading an empty day. Before Batch 251 it did so by importing a
    *private scheduler helper* from a router; the sync now belongs to the pipeline
    both triggers share.
    """
    async with AsyncSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        if profile is None or not profile.is_active or profile.deleted_at is not None:
            log.warning(
                "morning check-in background generation skipped",
                profile_id=str(user_id),
                subject_date=subject_date.isoformat(),
            )
            return
        pipeline = MorningBriefPipeline(session, policy=CHECKIN_POLICY)
        await pipeline.sync_inputs([profile])
        await pipeline.generate_brief(profile, subject_date)
