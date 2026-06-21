"""Tests for Batch 13 executable coaching: verdict-driven adjustment + delivery."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile, UserRole
from src.services.executable_coaching import (
    AUDIT_TYPE_PROPOSED,
    AUDIT_TYPE_PUSHED,
    HIT_FLOOR_PCT,
    RECOVERY_CAP_PCT,
    ExecutableCoachingService,
    adjust_ir_for_verdict,
)
from src.services.workout_delivery import IntervalsCreateResult, build_structured_workout_ir

VO2_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
        {
            "label": "Main set",
            "repeats": 3,
            "pattern": "5x 30s on / 30s off",
            "target": "105-110% FTP 95rpm",
        },
        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
    ],
}
SWEET_SPOT_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
        {
            "label": "Main set",
            "repeats": 3,
            "pattern": "8 min on / 4 min easy",
            "target": "88-94% FTP",
        },
        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
    ],
}


def _planned_workout(structured: dict, *, version: int = 1) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        workout_date=date(2026, 6, 23),
        version=version,
        title="VO2 Max 30/30",
        workout_type="bike_vo2",
        status="planned",
        is_active=True,
        planned_duration_min=60,
        intensity_target="105-110% FTP",
        structured_workout=structured,
        source="test",
    )


def _max_power(ir: dict) -> int:
    return max(int(step["powerEndPct"]) for step in ir["steps"])


# ---------------------------------------------------------------------------
# adjust_ir_for_verdict — deterministic transform
# ---------------------------------------------------------------------------


def test_amber_cuts_duration_drops_a_zone_and_removes_hit() -> None:
    base = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)
    base_total = base["totalDurationSec"]

    adjusted = adjust_ir_for_verdict(base, "Amber")

    # Cut duration 20-30% (we scale to 75%, comfortably inside the band).
    assert base_total * 0.70 <= adjusted["totalDurationSec"] <= base_total * 0.80
    # No HIT/VO2 survives — every step is at or below threshold.
    assert _max_power(adjusted) < HIT_FLOOR_PCT
    # The 108% work intervals dropped a zone and were capped at threshold (98).
    assert _max_power(adjusted) < _max_power(base)
    assert adjusted["origin"] == "amber_regeneration"
    assert adjusted["adjustment"]["verdict"] == "Amber"
    assert adjusted["adjustment"]["removedHit"] is True
    assert adjusted["name"].startswith("Amber-adjusted: ")


def test_amber_drops_sweet_spot_by_a_zone() -> None:
    base = build_structured_workout_ir(_planned_workout(SWEET_SPOT_STRUCTURED), ftp_watts=280)
    # Sweet-spot work sits at ~91% FTP.
    assert _max_power(base) == 91

    adjusted = adjust_ir_for_verdict(base, "Amber")

    # 91% drops a zone (~13 points) to tempo, and there was no HIT to remove.
    assert _max_power(adjusted) == 78
    assert adjusted["adjustment"]["removedHit"] is False


def test_amber_preserves_cadence_on_work_steps() -> None:
    base = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)
    adjusted = adjust_ir_for_verdict(base, "Amber")

    work_steps = [s for s in adjusted["steps"] if s["label"].startswith("Main set work")]
    assert work_steps
    assert all(step.get("cadenceRpm") == 95 for step in work_steps)


def test_red_never_emits_vo2() -> None:
    base = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)

    adjusted = adjust_ir_for_verdict(base, "Red")

    # The hard guarantee: a Red substitution can never be a VO2 push.
    assert _max_power(adjusted) <= RECOVERY_CAP_PCT
    assert _max_power(adjusted) < HIT_FLOOR_PCT
    assert all(int(step["powerStartPct"]) <= RECOVERY_CAP_PCT for step in adjusted["steps"])
    assert adjusted["origin"] == "red_substitution"
    assert adjusted["name"].startswith("Recovery substitution: ")


def test_green_is_passthrough() -> None:
    base = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)

    adjusted = adjust_ir_for_verdict(base, "Green")

    assert adjusted["steps"] == base["steps"]
    assert adjusted["totalDurationSec"] == base["totalDurationSec"]
    assert adjusted["origin"] == "as_planned"
    assert adjusted["adjustment"]["changed"] is False


# ---------------------------------------------------------------------------
# ExecutableCoachingService — DB-backed
# ---------------------------------------------------------------------------


class _FakeIntervalsClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        self.payloads.append(payload)
        return IntervalsCreateResult(event_id="evt_123", raw_response={"id": "evt_123"})


def _amber_analysis(user_id: uuid.UUID, subject_date: date) -> Analysis:
    return Analysis(
        user_id=user_id,
        analysis_type="morning",
        subject_date=subject_date,
        generated_at_utc=datetime(2026, 6, 23, 6, 30),
        prompt_version="morning-analysis-test",
        verdict="Amber",
        context_packet={"verdict": {"status": "Amber"}},
        output_markdown="Amber verdict",
        raw_response={},
    )


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Coaching Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_regenerate_for_verdict_creates_amber_proposal_and_audit(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    workout_id = uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=subject,
                version=2,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                intensity_target="105-110% FTP",
                structured_workout=VO2_STRUCTURED,
                source="test",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        analysis = _amber_analysis(user_id, subject)

        created = await service.regenerate_for_verdict(user, subject, analysis=analysis)

        assert len(created) == 1
        proposal = created[0]
        assert proposal.status == "proposed"
        assert proposal.planned_workout_id == workout_id
        assert proposal.structured_workout_ir["origin"] == "amber_regeneration"

        audits = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PROPOSED)
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].context_packet["tag"] == f"amber-regen:{workout_id}:v2"
        assert audits[0].context_packet["proposalId"] == str(proposal.id)
        assert audits[0].verdict == "Amber"

        # Re-running is idempotent — no duplicate proposal or audit row.
        again = await service.regenerate_for_verdict(user, subject, analysis=analysis)
        assert again == []
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert len(proposals) == 1


@pytest.mark.asyncio
async def test_regenerate_for_verdict_skips_non_amber(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                id=uuid.uuid4(),
                user_id=user_id,
                workout_date=subject,
                version=1,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                intensity_target="105-110% FTP",
                structured_workout=VO2_STRUCTURED,
                source="test",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        green = Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=subject,
            generated_at_utc=datetime(2026, 6, 23, 6, 30),
            prompt_version="morning-analysis-test",
            verdict="Green",
            context_packet={"verdict": {"status": "Green"}},
            output_markdown="Green verdict",
            raw_response={},
        )

        created = await service.regenerate_for_verdict(user, subject, analysis=green)

        assert created == []
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert proposals == []


def _proposal(
    user_id: uuid.UUID,
    *,
    workout_date: date,
    status: str,
    approved: bool,
) -> WorkoutDeliveryProposal:
    base = datetime(2026, 6, 23, 9, 0)
    return WorkoutDeliveryProposal(
        id=uuid.uuid4(),
        user_id=user_id,
        planned_workout_id=None,
        planned_workout_version=1,
        workout_date=workout_date,
        provider="intervals_icu",
        status=status,
        proposed_at_utc=base,
        approved_at_utc=base if approved else None,
        structured_workout_ir={"origin": "amber_regeneration", "adjustment": {"verdict": "Amber"}},
        intervals_payload={"category": "WORKOUT", "name": "Test"},
        zwo_xml="<workout_file/>",
    )


@pytest.mark.asyncio
async def test_auto_push_due_pushes_only_approved_within_window(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    due = _proposal(user_id, workout_date=date(2026, 6, 24), status="approved", approved=True)
    unapproved = _proposal(
        user_id, workout_date=date(2026, 6, 24), status="proposed", approved=False
    )
    far_out = _proposal(user_id, workout_date=date(2026, 7, 5), status="approved", approved=True)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([due, unapproved, far_out])
        await session.commit()

    now = datetime(2026, 6, 23, 9, 0, tzinfo=UTC)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        pushed = await service.auto_push_due(user, now_utc=now, lead_days=2)

        assert [p.id for p in pushed] == [due.id]
        assert len(fake.payloads) == 1

        refreshed_due = await session.get(WorkoutDeliveryProposal, due.id)
        refreshed_unapproved = await session.get(WorkoutDeliveryProposal, unapproved.id)
        refreshed_far = await session.get(WorkoutDeliveryProposal, far_out.id)
        assert refreshed_due is not None and refreshed_due.status == "pushed"
        assert refreshed_due.intervals_event_id == "evt_123"
        # Approval gate + lead window are both respected.
        assert refreshed_unapproved is not None and refreshed_unapproved.status == "proposed"
        assert refreshed_far is not None and refreshed_far.status == "approved"

        audits = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PUSHED)
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].context_packet["tag"] == f"auto-push:{due.id}"
        assert audits[0].verdict == "Amber"

        # Idempotent: a second sweep finds nothing left to push.
        again = await service.auto_push_due(user, now_utc=now, lead_days=2)
        assert again == []
        assert len(fake.payloads) == 1
