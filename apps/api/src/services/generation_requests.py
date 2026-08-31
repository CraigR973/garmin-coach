"""Durable request identity and lease for regenerable paid analyses (Batch 161)."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import Analysis, GenerationRequest, ManualEntry

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

GENERATION_IDENTITY_KEY = "generationIdentity"
INPUT_VERSION_KEY = "inputVersion"
INPUT_COMPLETENESS_VERSION_KEY = "inputCompletenessVersion"

# The production ``statement_timeout``, measured on 2026-08-30 against Supabase
# Postgres 17.6 behind the session-mode pooler. The app does not set this and
# cannot change it from here; it is recorded because it is the ceiling that
# killed seven queued claims that morning, and because every budget below has to
# be legible against it. ``lock_timeout`` is 0 on the same connection, so before
# Batch 232 a lock wait was bounded by nothing else.
OBSERVED_STATEMENT_TIMEOUT = timedelta(seconds=120)


def lease_duration() -> timedelta:
    """How long a claim stays valid, derived from the paid call it must outlive.

    Batch 232.2. This was a hardcoded three minutes justified by a comment that
    read "Anthropic calls time out after 60 seconds" — true when Batch 161 wrote
    it, false since Batch 234 raised the read budget to 300s. A lease shorter
    than the call it covers is a lease that expires while a compliant worker is
    still generating, at which point the request row says the work is
    reclaimable when it is not.

    Deriving it means the two numbers can no longer drift apart: raise
    ``ANTHROPIC_READ_TIMEOUT_SECONDS`` and the lease follows.
    """

    return timedelta(
        seconds=settings.anthropic_read_timeout_seconds + settings.generation_lease_overhead_seconds
    )


@dataclass(frozen=True)
class TimeoutOrdering:
    """The three budgets that govern one generation, and how they must be ordered.

    Batch 232.2 exists because these were set by three different batches, each
    correct on its own, and nothing stated the relationship between them. Batch
    234 then raised one of them past the other two, and the ordering that had
    held by accident stopped holding.

    ``holds`` is the invariant, in the order that matters:

    1. ``lease > anthropic_read`` — a claim outlives the paid call it covers, so
       a second worker can never reclaim an artifact that is still generating.
    2. ``lease > statement_timeout`` — a claim outlives any single statement's
       ceiling, so a claim can never be shorter-lived than the database's own
       patience.
    3. ``lease < brief_generation_stale_after`` — Batch 144's orphan guard fires
       *after* the lease has already freed the artifact, so the retry it offers
       Mark can actually be taken rather than answering 409.

    ``statement_timeout`` is deliberately not in the *generation* path at all:
    the claim takes a non-blocking ``pg_try_advisory_xact_lock``, so no attempt
    ever queues on the lock and none can be cancelled by it. The first two
    orderings are defence in depth for the day someone changes that.
    """

    anthropic_read: timedelta
    statement_timeout: timedelta
    lease: timedelta
    brief_generation_stale_after: timedelta

    @property
    def holds(self) -> bool:
        return (
            self.lease > self.anthropic_read
            and self.lease > self.statement_timeout
            and self.lease < self.brief_generation_stale_after
        )

    def describe(self) -> str:
        return (
            f"anthropic_read={self.anthropic_read.total_seconds():.0f}s, "
            f"statement_timeout={self.statement_timeout.total_seconds():.0f}s, "
            f"lease={self.lease.total_seconds():.0f}s, "
            f"brief_generation_stale_after="
            f"{self.brief_generation_stale_after.total_seconds():.0f}s"
        )


def timeout_ordering() -> TimeoutOrdering:
    """Resolve the ordering from the *configured* values, not their defaults."""

    return TimeoutOrdering(
        anthropic_read=timedelta(seconds=settings.anthropic_read_timeout_seconds),
        statement_timeout=OBSERVED_STATEMENT_TIMEOUT,
        lease=lease_duration(),
        brief_generation_stale_after=timedelta(
            minutes=settings.brief_generation_stale_after_minutes
        ),
    )


def validate_timeout_ordering() -> None:
    """Fail closed at startup if the three budgets have been tuned out of order."""

    ordering = timeout_ordering()
    if not ordering.holds:
        raise ValueError(
            "Generation timeout budgets are out of order — a lease must outlive both "
            "the paid call and the statement timeout, and expire before the UI calls "
            f"the generation stale. Got {ordering.describe()}."
        )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _identity(parts: dict[str, str | None]) -> str:
    encoded = json.dumps(parts, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def morning_generation_identity(
    *,
    user_id: uuid.UUID,
    subject_date: date,
    input_version: str | None,
    input_completeness_version: str,
    prompt_version: str,
) -> str:
    return _identity(
        {
            "kind": "morning",
            "userId": str(user_id),
            "subjectDate": subject_date.isoformat(),
            "inputVersion": input_version,
            "inputCompletenessVersion": input_completeness_version,
            "promptVersion": prompt_version,
        }
    )


def post_activity_generation_identity(
    *,
    user_id: uuid.UUID,
    activity_id: uuid.UUID,
    input_version: str | None,
    prompt_version: str,
) -> str:
    return _identity(
        {
            "kind": "post_activity",
            "userId": str(user_id),
            "activityId": str(activity_id),
            "inputVersion": input_version,
            "promptVersion": prompt_version,
        }
    )


def longitudinal_generation_identity(
    *,
    user_id: uuid.UUID,
    period_key: str,
    prompt_version: str,
) -> str:
    """Stable paid-request identity for one user's monthly analyst run."""

    return _identity(
        {
            "kind": "longitudinal",
            "userId": str(user_id),
            "periodKey": period_key,
            "promptVersion": prompt_version,
        }
    )


def manual_entry_generation_version(entry: ManualEntry | None) -> str | None:
    """Hash substantive check-in input while excluding write timestamps."""

    if entry is None:
        return None
    return _identity(
        {
            "plannedWorkoutId": str(entry.planned_workout_id) if entry.planned_workout_id else None,
            "activityId": str(entry.activity_id) if entry.activity_id else None,
            "plannedWorkoutVersion": str(entry.planned_workout_version)
            if entry.planned_workout_version is not None
            else None,
            "bpSystolic": str(entry.bp_systolic) if entry.bp_systolic is not None else None,
            "bpDiastolic": str(entry.bp_diastolic) if entry.bp_diastolic is not None else None,
            "subjectiveScore": str(entry.subjective_score)
            if entry.subjective_score is not None
            else None,
            "rpe": str(entry.rpe) if entry.rpe is not None else None,
            "feel": entry.feel,
            "adherenceStatus": entry.adherence_status,
            "actualWorkout": json.dumps(
                entry.actual_workout_json or {},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "supplements": json.dumps(
                entry.supplements_json or {},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "food": json.dumps(
                entry.food_json or {},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "notes": entry.notes,
        }
    )


def stamp_generation_identity(
    packet: dict[str, object],
    *,
    request_identity: str,
    input_version: str | None,
    input_completeness_version: str | None = None,
) -> None:
    packet[GENERATION_IDENTITY_KEY] = request_identity
    packet[INPUT_VERSION_KEY] = input_version
    if input_completeness_version is not None:
        packet[INPUT_COMPLETENESS_VERSION_KEY] = input_completeness_version


def _advisory_key(lease_scope: str) -> int:
    digest = hashlib.sha256(f"generation:{lease_scope}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class GenerationRequestInProgress(HTTPException):
    """Another worker already owns this artifact scope — do not wait, do not fail.

    Batch 232: this is not an error state and callers must not present it as one.
    A background generation that raises it should leave whatever status row it
    found alone, because the worker that *does* hold the scope is going to write
    the real outcome. Recording a failure here shows Mark a retryable failure
    card for a brief that is being written successfully in the next task along.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="This read is already being generated. Please try again shortly.",
        )


@dataclass
class GenerationClaim:
    row: GenerationRequest
    existing_analysis: Analysis | None

    def restart(self) -> None:
        self.existing_analysis = None
        self.row.status = STATUS_RUNNING
        self.row.analysis_id = None
        self.row.failure_reason = None
        self.row.lease_expires_at = _utcnow() + lease_duration()
        self.row.updated_at = _utcnow()

    def mark_completed(self, analysis: Analysis) -> None:
        self.row.status = STATUS_COMPLETED
        self.row.analysis_id = analysis.id
        self.row.failure_reason = None
        self.row.lease_expires_at = _utcnow()
        self.row.updated_at = _utcnow()

    def mark_failed(self, reason: str) -> None:
        self.row.status = STATUS_FAILED
        self.row.analysis_id = None
        self.row.failure_reason = reason[:40]
        self.row.lease_expires_at = _utcnow()
        self.row.updated_at = _utcnow()


@asynccontextmanager
async def claim_generation_request(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    request_identity: str,
    generation_kind: str,
    lease_scope: str | None = None,
) -> AsyncIterator[GenerationClaim]:
    """Serialize one artifact scope and reuse a completed request identity.

    A transaction-scoped advisory lock serializes workers until the completed
    request row and analysis commit atomically. Callers use a stable artifact
    scope (user/date or user/activity), so a changed input cannot race an older
    in-flight request's state row. The unique request row also bridges the window
    where a caller asked for ``commit=False`` and has not committed the completed
    analysis yet: a competing INSERT waits for that transaction before deciding
    whether it can claim the identity.

    **The lock is taken with ``pg_try_advisory_xact_lock``, never the blocking
    variant (Batch 232.1).** The lock is held for the whole transaction, and that
    transaction contains the paid Anthropic call, so waiting for it means parking
    a connection for the length of somebody else's generation. On 2026-08-30 that
    is exactly what happened to Mark's morning brief: fifteen attempts queued on
    the single key for ``morning:<mark>:2026-08-30``, eight acquired it after
    **40.4s to 117.6s**, and the other **seven were killed by Postgres at the
    120s ``statement_timeout``** — not generating, just waiting, and each one
    surfaced to him as a generic retryable failure. Consecutive acquisitions were
    70–80s apart, which measures the hold time and confirms the lock spans the
    call.

    Waiting also cost connections rather than merely time. Each queued attempt
    holds one session-mode pooler client slot for its whole wait, and Supavisor
    refused new clients eight times inside the same window with
    ``(EMAXCONNSESSION) … pool_size: 15``.

    So a caller that cannot have the scope is told immediately. The generation it
    wanted is already running; ``GenerationRequestInProgress`` says so in
    milliseconds instead of two minutes, and never by being cancelled.
    """

    advisory_key = _advisory_key(lease_scope or request_identity)
    acquired: bool | None = await session.scalar(
        select(func.pg_try_advisory_xact_lock(advisory_key))
    )
    if not acquired:
        raise GenerationRequestInProgress()
    now = _utcnow()
    statement = (
        insert(GenerationRequest)
        .values(
            user_id=user_id,
            request_identity=request_identity,
            generation_kind=generation_kind,
            status=STATUS_RUNNING,
            lease_expires_at=now + lease_duration(),
        )
        .on_conflict_do_nothing(index_elements=[GenerationRequest.request_identity])
        .returning(GenerationRequest.id)
    )
    inserted_id = await session.scalar(statement)
    if inserted_id is not None:
        row = await session.get(GenerationRequest, inserted_id)
        assert row is not None
        claim = GenerationClaim(row=row, existing_analysis=None)
        try:
            yield claim
        except Exception as exc:
            if claim.row.status != STATUS_FAILED:
                claim.mark_failed(str(getattr(exc, "reason", "generation_error")))
                await session.flush()
            raise
        return

    row = await session.scalar(
        select(GenerationRequest).where(GenerationRequest.request_identity == request_identity)
    )
    if row is None:  # pragma: no cover - unique conflict guarantees the row
        raise RuntimeError("generation request disappeared after identity conflict")

    if row.status == STATUS_COMPLETED and row.analysis_id is not None:
        analysis = await session.get(Analysis, row.analysis_id)
        if analysis is not None:
            yield GenerationClaim(row=row, existing_analysis=analysis)
            return

    if row.status == STATUS_RUNNING and row.lease_expires_at > now:
        # Holding the advisory lock means an active compliant worker cannot be
        # here; this is a previously committed claim whose worker disappeared
        # with its connection. The lease — not the lock — is what releases it,
        # which is why Batch 232.2 derives the lease from the paid call it has to
        # outlive rather than leaving it at a number chosen for a 60s timeout.
        raise GenerationRequestInProgress()

    row.status = STATUS_RUNNING
    row.analysis_id = None
    row.failure_reason = None
    row.lease_expires_at = now + lease_duration()
    row.updated_at = now
    await session.flush()
    claim = GenerationClaim(row=row, existing_analysis=None)
    try:
        yield claim
    except Exception as exc:
        if claim.row.status != STATUS_FAILED:
            claim.mark_failed(str(getattr(exc, "reason", "generation_error")))
            await session.flush()
        raise
