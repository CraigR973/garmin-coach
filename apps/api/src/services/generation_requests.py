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
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, GenerationRequest, ManualEntry

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

GENERATION_IDENTITY_KEY = "generationIdentity"
INPUT_VERSION_KEY = "inputVersion"

# Anthropic calls time out after 60 seconds. Three minutes leaves room for packet
# assembly/DB work while still allowing a crashed worker to be reclaimed quickly.
LEASE_DURATION = timedelta(minutes=3)


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
    prompt_version: str,
) -> str:
    return _identity(
        {
            "kind": "morning",
            "userId": str(user_id),
            "subjectDate": subject_date.isoformat(),
            "inputVersion": input_version,
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
) -> None:
    packet[GENERATION_IDENTITY_KEY] = request_identity
    packet[INPUT_VERSION_KEY] = input_version


def _advisory_key(lease_scope: str) -> int:
    digest = hashlib.sha256(f"generation:{lease_scope}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class GenerationRequestInProgress(HTTPException):
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
        self.row.lease_expires_at = _utcnow() + LEASE_DURATION
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

    A session-level advisory lock serializes workers even across transaction
    commits. Callers use a stable artifact scope (user/date or user/activity), so
    a changed input waits behind an older in-flight request rather than racing its
    state row. The unique request row then bridges the small window where a caller
    asked for ``commit=False`` and has not committed the completed analysis yet:
    a competing INSERT waits for that transaction before deciding whether it can
    claim the identity.
    """

    advisory_key = _advisory_key(lease_scope or request_identity)
    await session.scalar(select(func.pg_advisory_lock(advisory_key)))
    try:
        now = _utcnow()
        statement = (
            insert(GenerationRequest)
            .values(
                user_id=user_id,
                request_identity=request_identity,
                generation_kind=generation_kind,
                status=STATUS_RUNNING,
                lease_expires_at=now + LEASE_DURATION,
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
            # The advisory lock means an active compliant worker cannot be here;
            # this is a previously committed claim whose worker disappeared.
            raise GenerationRequestInProgress()

        row.status = STATUS_RUNNING
        row.analysis_id = None
        row.failure_reason = None
        row.lease_expires_at = now + LEASE_DURATION
        row.updated_at = now
        await session.flush()
        claim = GenerationClaim(row=row, existing_analysis=None)
        try:
            yield claim
        except Exception as exc:
            claim.mark_failed(str(getattr(exc, "reason", "generation_error")))
            await session.flush()
            raise
    finally:
        try:
            await session.scalar(select(func.pg_advisory_unlock(advisory_key)))
        except PendingRollbackError:
            # A failed statement leaves PostgreSQL's transaction aborted, but a
            # session-level lock would otherwise survive in the pooled connection.
            await session.rollback()
            await session.scalar(select(func.pg_advisory_unlock(advisory_key)))
