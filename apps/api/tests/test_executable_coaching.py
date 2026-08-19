"""Tests for Batch 13 executable coaching: verdict-driven adjustment + delivery."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Analysis,
    GarminWorkoutDelivery,
    ManualEntry,
    PlannedWorkout,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.services.executable_coaching import (
    AUDIT_TYPE_DELIVERED,
    AUDIT_TYPE_MOVED,
    AUDIT_TYPE_PROPOSAL_EXPIRED,
    AUDIT_TYPE_PROPOSED,
    AUDIT_TYPE_PUSH_BLOCKED,
    AUDIT_TYPE_PUSHED,
    AUDIT_TYPE_REMOVED,
    AUDIT_TYPE_REPLACED,
    AUDIT_TYPE_SKIPPED,
    WORKOUT_STATUS_SKIPPED,
    ExecutableCoachingService,
    apply_manual_override_to_ir,
)
from src.services.garmin_sync import GarminScheduledWorkout
from src.services.interval_workout_editor import EditableIntervalBlock, IntervalLeg
from src.services.morning_analysis import MorningAnalysisResult
from src.services.verdict_scaling import (
    AMBER_POWER_CAP_PCT,
    ENDURANCE_CEILING_PCT,
    HIT_FLOOR_PCT,
    RECOVERY_CAP_PCT,
    adjust_ir_for_chronic_deload,
    adjust_ir_for_verdict,
    blocks_red_vo2,
    ease_amber_power_pct,
    ir_has_vo2,
    summarize_verdict_adjustment,
)
from src.services.workout_categories import category_for_workout_type
from src.services.workout_delivery import (
    STATUS_DELETED,
    STATUS_PUSHED,
    IntervalsCreateResult,
    WorkoutDeliveryService,
    build_structured_workout_ir,
)

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
ENDURANCE_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
        {"label": "Endurance", "minutes": 90, "target": "64-70% FTP 85rpm"},
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
    # The 108% work intervals dropped a zone and were capped at Sweet Spot (94).
    assert _max_power(adjusted) < _max_power(base)
    assert _max_power(adjusted) == AMBER_POWER_CAP_PCT
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


def test_chronic_deload_uses_lighter_transform_without_setting_verdict() -> None:
    base = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)

    adjusted = adjust_ir_for_chronic_deload(
        base,
        {
            "kind": "deload_proposal",
            "triggerSources": ["sustained_recovery_marker"],
            "recoveryMarkers": ["readiness_score"],
            "redMorningCount": 0,
            "reasons": ["Readiness repeatedly missed its personal band."],
        },
    )

    assert adjusted["origin"] == "chronic_deload"
    assert adjusted["name"].startswith("Chronic deload: ")
    assert (
        base["totalDurationSec"] * 0.70
        <= adjusted["totalDurationSec"]
        <= (base["totalDurationSec"] * 0.80)
    )
    assert _max_power(adjusted) < HIT_FLOOR_PCT
    assert adjusted["adjustment"]["changed"] is True
    assert adjusted["adjustment"]["verdict"] is None
    assert adjusted["adjustment"]["chronicAction"]["verdictImpact"] == "none"


def test_manual_override_scales_duration_and_intensity() -> None:
    base = adjust_ir_for_verdict(
        build_structured_workout_ir(_planned_workout(SWEET_SPOT_STRUCTURED), ftp_watts=280),
        "Amber",
    )

    adjusted = apply_manual_override_to_ir(base, duration_scale_pct=80, intensity_scale_pct=90)

    assert adjusted["origin"] == "manual_override"
    assert adjusted["name"].startswith("Manual override: ")
    assert adjusted["totalDurationSec"] == round(base["totalDurationSec"] * 0.8)
    assert _max_power(adjusted) < _max_power(base)
    assert adjusted["adjustment"]["manualOverride"] == {
        "durationScalePct": 80,
        "intensityScalePct": 90,
        "basisTotalDurationSec": base["totalDurationSec"],
    }


def test_amber_holds_zone_two_ride_and_cuts_duration_only() -> None:
    """Batch 173.2: an already-Zone-2 endurance ride keeps its intensity (67% FTP)
    and is only shortened — never dropped below the Zone-2 floor (the old 54%/60%)."""
    base = build_structured_workout_ir(_planned_workout(ENDURANCE_STRUCTURED), ftp_watts=280)
    base_total = base["totalDurationSec"]
    assert _max_power(base) == 67

    adjusted = adjust_ir_for_verdict(base, "Amber")

    assert _max_power(adjusted) == 67  # held at Zone 2, not 54 (−13) or 60 (×0.9)
    assert base_total * 0.70 <= adjusted["totalDurationSec"] <= base_total * 0.80
    assert adjusted["adjustment"]["zoneDropPct"] == 0  # honest: no drop was applied
    assert adjusted["adjustment"]["removedHit"] is False


def test_ease_amber_power_is_zone_aware() -> None:
    assert ease_amber_power_pct(55) == 55
    assert ease_amber_power_pct(ENDURANCE_CEILING_PCT) == ENDURANCE_CEILING_PCT
    assert ease_amber_power_pct(67) == 67  # endurance held
    assert ease_amber_power_pct(76) == ENDURANCE_CEILING_PCT  # a drop never lands below Z2
    assert ease_amber_power_pct(91) == 78  # sweet spot drops a zone
    assert ease_amber_power_pct(108) == AMBER_POWER_CAP_PCT
    assert ease_amber_power_pct(108) < HIT_FLOOR_PCT


def test_summarize_verdict_adjustment_matches_the_transform_everywhere() -> None:
    """One rule everywhere: the packet summary equals what the delivery transform
    actually produces, and mirrors ease_amber_power_pct (Batch 173.2/173.3)."""
    for structured, held in (
        (ENDURANCE_STRUCTURED, True),
        (VO2_STRUCTURED, False),
        (SWEET_SPOT_STRUCTURED, False),
    ):
        base = build_structured_workout_ir(_planned_workout(structured), ftp_watts=280)
        summary = summarize_verdict_adjustment(base, "Amber")
        adjusted = adjust_ir_for_verdict(base, "Amber")
        assert summary is not None
        assert summary["adjustedWorkPowerPct"] == _max_power(adjusted)
        assert summary["adjustedWorkPowerPct"] == ease_amber_power_pct(
            summary["plannedWorkPowerPct"]
        )
        assert summary["adjustedDurationMin"] < summary["plannedDurationMin"]
        assert summary["intensityHeldAtEndurance"] is held
        assert summary["classificationImpact"] == "none"


def test_summarize_verdict_adjustment_red_and_green() -> None:
    base = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)
    red = summarize_verdict_adjustment(base, "Red")
    assert red is not None
    assert red["adjustedWorkPowerPct"] <= RECOVERY_CAP_PCT
    assert red["intensityHeldAtEndurance"] is False
    # Green (or no verdict) is explanatory-absent — never a guessed number.
    assert summarize_verdict_adjustment(base, "Green") is None
    assert summarize_verdict_adjustment({"steps": []}, "Amber") is None


# ---------------------------------------------------------------------------
# ExecutableCoachingService — DB-backed
# ---------------------------------------------------------------------------


class _FakeIntervalsClient:
    def __init__(self, *, fail_create: bool = False, fail_update: bool = False) -> None:
        self.payloads: list[dict] = []
        self.updates: list[tuple[str, dict]] = []
        self.deletes: list[str] = []
        self.fail_create = fail_create
        self.fail_update = fail_update
        self._counter = 122  # so the first created event id is the legacy "evt_123"

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        if self.fail_create:
            raise HTTPException(status_code=503, detail="intervals.icu API key is not configured")
        self.payloads.append(payload)
        self._counter += 1
        event_id = f"evt_{self._counter}"
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def update_workout_event(self, event_id: str, payload: dict) -> IntervalsCreateResult:
        if self.fail_update:
            raise HTTPException(status_code=502, detail="intervals.icu update failed")
        self.updates.append((event_id, payload))
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def delete_workout_event(self, event_id: str) -> None:
        self.deletes.append(event_id)


OUTDOOR_STRUCTURED = {
    "format": "bike",
    "delivery": "outdoor",
    "steps": [
        {"label": "Warm-up ramp", "minutes": 10, "ramp": [45, 75]},
        {"label": "Main block", "minutes": 40, "target": "75%"},
        {"label": "Cool-down ramp", "minutes": 5, "ramp": [75, 45]},
    ],
}


class _FakeGarminClient:
    """Sync fake matching GarminConnectClient's write surface (Batch 78)."""

    def __init__(self) -> None:
        self.uploads: list[tuple[dict, date]] = []
        self.deletes: list[tuple[str | None, str | None]] = []
        self._counter = 2000

    def upload_and_schedule_workout(
        self, workout_json: dict, calendar_date: date
    ) -> GarminScheduledWorkout:
        self.uploads.append((workout_json, calendar_date))
        self._counter += 1
        return GarminScheduledWorkout(
            workout_id=f"w{self._counter}", schedule_id=f"s{self._counter}", raw={}
        )

    def delete_scheduled_workout(self, workout_id: str | None, schedule_id: str | None) -> None:
        self.deletes.append((workout_id, schedule_id))


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


@pytest.mark.asyncio
async def test_chronic_deload_proposes_seven_day_window_and_preserves_acute_precedence(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_profile(db_conn, user_id)
    workout_ids = [uuid.uuid4() for _ in range(4)]
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for workout_id, offset in zip(workout_ids, (0, 1, 5, 7), strict=True):
            session.add(
                PlannedWorkout(
                    id=workout_id,
                    user_id=user_id,
                    workout_date=subject + timedelta(days=offset),
                    version=1,
                    title=f"Bike day {offset}",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    intensity_target="105-110% FTP",
                    structured_workout=VO2_STRUCTURED,
                    source="test",
                )
            )
        # Tomorrow already has a safer acute proposal. The chronic pass must not
        # replace it with a second, less-specific adjustment.
        session.add(
            WorkoutDeliveryProposal(
                id=uuid.uuid4(),
                user_id=user_id,
                planned_workout_id=workout_ids[1],
                planned_workout_version=1,
                workout_date=subject + timedelta(days=1),
                provider="intervals_icu",
                status="proposed",
                proposed_at_utc=datetime(2026, 6, 23, 7, 0),
                structured_workout_ir={
                    "origin": "red_substitution",
                    "adjustment": {"changed": True, "verdict": "Red"},
                },
                intervals_payload={"category": "WORKOUT", "name": "Recovery"},
                zwo_xml="<workout_file/>",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        analysis = Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=subject,
            generated_at_utc=datetime(2026, 6, 23, 7, 5),
            prompt_version="morning-analysis-v21-test",
            verdict="Green",
            context_packet={
                "verdict": {
                    "status": "Green",
                    "chronicAction": {
                        "triggered": True,
                        "kind": "deload_proposal",
                        "proposalWindowDays": 7,
                        "triggerSources": ["sustained_recovery_marker"],
                        "recoveryMarkers": ["readiness_score"],
                        "redMorningCount": 0,
                        "reasons": ["Readiness repeatedly missed its personal band."],
                        "verdictImpact": "none",
                    },
                }
            },
            output_markdown="Green verdict with a separate deload proposal.",
            raw_response={},
        )
        service = ExecutableCoachingService(session)

        created = await service.propose_chronic_deload(user, subject, analysis=analysis)

        assert {proposal.planned_workout_id for proposal in created} == {
            workout_ids[0],
            workout_ids[2],
        }
        assert analysis.verdict == "Green"
        assert all(proposal.status == "proposed" for proposal in created)
        assert all(
            proposal.structured_workout_ir["origin"] == "chronic_deload" for proposal in created
        )
        assert all(
            proposal.structured_workout_ir["adjustment"]["verdict"] is None for proposal in created
        )
        # Day +7 is outside the inclusive seven-day window; tomorrow's Red
        # proposal remains the only proposal for that workout.
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        by_workout: dict[uuid.UUID | None, list[WorkoutDeliveryProposal]] = {}
        for proposal in proposals:
            by_workout.setdefault(proposal.planned_workout_id, []).append(proposal)
        assert workout_ids[3] not in by_workout
        assert len(by_workout[workout_ids[1]]) == 1
        assert by_workout[workout_ids[1]][0].structured_workout_ir["origin"] == "red_substitution"

        audits = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PROPOSED)
                )
            )
            .scalars()
            .all()
        )
        assert {audit.context_packet["tag"] for audit in audits} == {
            f"chronic-deload:{workout_ids[0]}:v1",
            f"chronic-deload:{workout_ids[2]}:v1",
        }
        assert all(audit.verdict is None for audit in audits)

        again = await service.propose_chronic_deload(user, subject, analysis=analysis)
        assert again == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("triggered", "kind"),
    [
        (False, "deload_proposal"),
        (True, "rearrange_proposal"),
    ],
)
async def test_chronic_deload_ignores_inactive_or_rearrange_signal(
    db_conn: AsyncConnection,
    triggered: bool,
    kind: str,
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
        analysis = Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=subject,
            generated_at_utc=datetime(2026, 6, 23, 7, 5),
            prompt_version="morning-analysis-v21-test",
            verdict="Green",
            context_packet={
                "verdict": {
                    "status": "Green",
                    "chronicAction": {
                        "triggered": triggered,
                        "kind": kind,
                        "verdictImpact": "none",
                    },
                }
            },
            output_markdown="Green verdict.",
            raw_response={},
        )

        created = await ExecutableCoachingService(session).propose_chronic_deload(
            user, subject, analysis=analysis
        )

        assert created == []
        assert (await session.execute(select(WorkoutDeliveryProposal))).scalars().all() == []


@pytest.mark.asyncio
async def test_cleared_chronic_action_expires_only_undecided_future_offers(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    subject = date(2026, 8, 5)
    await _seed_profile(db_conn, user_id)

    def chronic_proposal(
        *,
        workout_date: date,
        status: str = "proposed",
        origin: str = "chronic_deload",
        event_id: str | None = None,
    ) -> WorkoutDeliveryProposal:
        proposal = _proposal(
            user_id,
            workout_date=workout_date,
            status=status,
            approved=status != "proposed",
        )
        proposal.structured_workout_ir = {
            "origin": origin,
            "adjustment": {
                "changed": True,
                "reason": "sustained_recovery_strain",
            },
        }
        proposal.intervals_event_id = event_id
        if status == "pushed":
            proposal.pushed_at_utc = datetime(2026, 8, 2, 8, 0)
        return proposal

    expires_today = chronic_proposal(workout_date=subject)
    expires_future = chronic_proposal(workout_date=subject + timedelta(days=3))
    acute_offer = chronic_proposal(
        workout_date=subject + timedelta(days=1), origin="red_substitution"
    )
    approved = chronic_proposal(workout_date=subject + timedelta(days=2), status="approved")
    pushed = chronic_proposal(
        workout_date=subject + timedelta(days=3),
        status="pushed",
        event_id="evt_stays",
    )
    past = chronic_proposal(workout_date=subject - timedelta(days=1))

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([expires_today, expires_future, acute_offer, approved, pushed, past])
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        analysis = Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=subject,
            generated_at_utc=datetime(2026, 8, 5, 7, 0),
            prompt_version="morning-analysis-v28-test",
            verdict="Green",
            context_packet={
                "verdict": {
                    "status": "Green",
                    "chronicAction": {
                        "triggered": False,
                        "kind": "deload_proposal",
                        "verdictImpact": "none",
                    },
                }
            },
            output_markdown="The chronic action has cleared.",
            raw_response={},
        )
        service = ExecutableCoachingService(session)

        created = await service.propose_chronic_deload(user, subject, analysis=analysis)

        assert created == []
        expected_statuses = {
            expires_today.id: STATUS_DELETED,
            expires_future.id: STATUS_DELETED,
            acute_offer.id: "proposed",
            approved.id: "approved",
            pushed.id: STATUS_PUSHED,
            past.id: "proposed",
        }
        for proposal_id, expected_status in expected_statuses.items():
            proposal = await session.get(WorkoutDeliveryProposal, proposal_id)
            assert proposal is not None and proposal.status == expected_status
        refreshed_pushed = await session.get(WorkoutDeliveryProposal, pushed.id)
        assert refreshed_pushed is not None
        assert refreshed_pushed.intervals_event_id == "evt_stays"

        audits = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PROPOSAL_EXPIRED)
                )
            )
            .scalars()
            .all()
        )
        assert {audit.context_packet["proposalId"] for audit in audits} == {
            str(expires_today.id),
            str(expires_future.id),
        }
        assert all(audit.context_packet["reason"] == "chronic_action_cleared" for audit in audits)
        assert all(audit.context_packet["status"] == STATUS_DELETED for audit in audits)

        again = await service.propose_chronic_deload(user, subject, analysis=analysis)
        assert again == []
        audit_count = await session.scalar(
            select(func.count(Analysis.id)).where(
                Analysis.analysis_type == AUDIT_TYPE_PROPOSAL_EXPIRED
            )
        )
        assert audit_count == 2


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


# ---------------------------------------------------------------------------
# Red-never-VO2 at the delivery gate (P1-2 fix)
# ---------------------------------------------------------------------------


def _morning_analysis(user_id: uuid.UUID, subject_date: date, verdict: str) -> Analysis:
    return Analysis(
        user_id=user_id,
        analysis_type="morning",
        subject_date=subject_date,
        generated_at_utc=datetime(2026, 6, 23, 6, 30),
        prompt_version="morning-analysis-test",
        verdict=verdict,
        context_packet={"verdict": {"status": verdict}},
        output_markdown=f"{verdict} verdict",
        raw_response={},
    )


def test_blocks_red_vo2_predicate() -> None:
    """The safety gate is a pure predicate — testable without a database."""
    vo2 = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)
    recovery = adjust_ir_for_verdict(vo2, "Red")  # capped at RECOVERY_CAP_PCT, no VO2

    assert ir_has_vo2(vo2) is True
    assert ir_has_vo2(recovery) is False
    assert ir_has_vo2(None) is False
    assert ir_has_vo2({"steps": "not-a-list"}) is False

    # The gate fires only on Red + VO2.
    assert blocks_red_vo2("Red", vo2) is True
    assert blocks_red_vo2("red", vo2) is True  # verdict is normalised
    assert blocks_red_vo2("Red", recovery) is False  # an easy spin is fine on Red
    assert blocks_red_vo2("Amber", vo2) is False  # Amber is handled by regeneration
    assert blocks_red_vo2("Green", vo2) is False
    assert blocks_red_vo2(None, vo2) is False


@pytest.mark.asyncio
async def test_auto_push_blocks_approved_vo2_on_red_day(db_conn: AsyncConnection) -> None:
    """A VO2 proposal approved ahead of time must not auto-push on a Red morning."""
    user_id = uuid.uuid4()
    subject = date(2026, 6, 24)
    await _seed_profile(db_conn, user_id)
    vo2_ir = build_structured_workout_ir(_planned_workout(VO2_STRUCTURED), ftp_watts=280)
    proposal = WorkoutDeliveryProposal(
        id=uuid.uuid4(),
        user_id=user_id,
        planned_workout_id=None,
        planned_workout_version=1,
        workout_date=subject,
        provider="intervals_icu",
        status="approved",
        proposed_at_utc=datetime(2026, 6, 23, 9, 0),
        approved_at_utc=datetime(2026, 6, 23, 9, 0),
        structured_workout_ir=vo2_ir,
        intervals_payload={"category": "WORKOUT", "name": "VO2"},
        zwo_xml="<workout_file/>",
    )
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(proposal)
        session.add(_morning_analysis(user_id, subject, "Red"))
        await session.commit()

    now = datetime(2026, 6, 23, 9, 0, tzinfo=UTC)  # subject (24th) within today+2
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        pushed = await service.auto_push_due(user, now_utc=now, lead_days=2)

        assert pushed == []  # the VO2 was blocked, not delivered
        assert fake.payloads == []  # nothing reached intervals.icu

        refreshed = await session.get(WorkoutDeliveryProposal, proposal.id)
        assert refreshed is not None
        assert refreshed.status == "approved"  # stays approved, never pushed
        assert refreshed.pushed_at_utc is None

        blocks = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PUSH_BLOCKED)
                )
            )
            .scalars()
            .all()
        )
        assert len(blocks) == 1
        assert blocks[0].verdict == "Red"
        assert blocks[0].context_packet["tag"] == f"push-blocked:{proposal.id}"

        # Idempotent: a second sweep blocks again but writes no duplicate audit.
        again = await service.auto_push_due(user, now_utc=now, lead_days=2)
        assert again == []
        blocks_after = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PUSH_BLOCKED)
                )
            )
            .scalars()
            .all()
        )
        assert len(blocks_after) == 1


@pytest.mark.asyncio
async def test_send_today_approves_pushes_and_audits_today_workout(
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
        session.add(_morning_analysis(user_id, subject, "Amber"))
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        pushed = await service.send_today(
            user,
            planned_workout_id=workout_id,
            now_utc=datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
        )

        assert pushed.status == "pushed"
        assert pushed.intervals_event_id == "evt_123"
        assert pushed.structured_workout_ir["origin"] == "amber_regeneration"
        assert len(fake.payloads) == 1

        audits = (await session.execute(select(Analysis))).scalars().all()
        audit_types = [audit.analysis_type for audit in audits]
        assert AUDIT_TYPE_PROPOSED in audit_types
        assert AUDIT_TYPE_PUSHED in audit_types
        push_audit = next(audit for audit in audits if audit.analysis_type == AUDIT_TYPE_PUSHED)
        assert push_audit.context_packet["tag"] == f"same-day-push:{pushed.id}"


@pytest.mark.asyncio
async def test_send_today_manual_override_pushes_the_override_ir(
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
                version=1,
                title="Sweet Spot Builder",
                workout_type="bike_sweet_spot",
                status="planned",
                is_active=True,
                planned_duration_min=75,
                intensity_target="88-94% FTP",
                structured_workout=SWEET_SPOT_STRUCTURED,
                source="test",
            )
        )
        session.add(_morning_analysis(user_id, subject, "Green"))
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        pushed = await service.send_today(
            user,
            planned_workout_id=workout_id,
            duration_scale_pct=80,
            intensity_scale_pct=90,
            now_utc=datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
        )

        assert pushed.status == "pushed"
        assert pushed.structured_workout_ir["origin"] == "manual_override"
        assert (
            pushed.structured_workout_ir["adjustment"]["manualOverride"]["durationScalePct"] == 80
        )
        assert fake.payloads == [pushed.intervals_payload]
        assert "Manual override" in pushed.intervals_payload["name"]


@pytest.mark.asyncio
async def test_send_today_preserves_red_never_vo2_gate(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    workout_id = uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        session.add(
            PlannedWorkout(
                id=workout_id,
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
        session.add(_morning_analysis(user_id, subject, "Red"))
        await session.commit()
        await WorkoutDeliveryService(session).propose(player=user, planned_workout_id=workout_id)

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        with pytest.raises(HTTPException) as exc_info:
            await service.send_today(
                user,
                planned_workout_id=workout_id,
                now_utc=datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
            )

        assert "Red verdict blocks VO2" in str(exc_info.value)
        assert fake.payloads == []
        blocks = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PUSH_BLOCKED)
                )
            )
            .scalars()
            .all()
        )
        assert len(blocks) == 1


@pytest.mark.asyncio
async def test_regenerate_for_verdict_creates_red_substitution(db_conn: AsyncConnection) -> None:
    """A Red verdict regenerates an easy recovery substitution (not just Amber)."""
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

        created = await service.regenerate_for_verdict(
            user, subject, analysis=_morning_analysis(user_id, subject, "Red")
        )

        assert len(created) == 1
        proposal = created[0]
        assert proposal.status == "proposed"  # never auto-approved
        assert proposal.structured_workout_ir["origin"] == "red_substitution"
        assert _max_power(proposal.structured_workout_ir) <= RECOVERY_CAP_PCT

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
        assert audits[0].context_packet["tag"] == f"red-regen:{workout_id}:v1"
        assert audits[0].verdict == "Red"


# ---------------------------------------------------------------------------
# Morning check-in recompute (verdict + eased ride after a late subjective read)
# ---------------------------------------------------------------------------


class _StubMorningService:
    """Controls the verdict seam so the check-in recompute can be tested apart
    from the (separately covered) morning-analysis engine.

    ``latest_analysis`` returns the verdict already stored at wake; the packet's
    ``new_status`` is what the subjective read now produces; ``generate_and_store``
    records how many times the model would have been re-run.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        stored: Analysis | None,
        new_status: str,
    ) -> None:
        self.session = session
        self._stored = stored
        self._new_status = new_status
        self.generate_calls = 0

    async def latest_analysis(self, user_id: uuid.UUID, subject_date: date) -> Analysis | None:
        return self._stored

    async def assemble_context_packet(
        self, player: Profile, subject_date: date
    ) -> dict[str, object]:
        return {"verdict": {"status": self._new_status}}

    async def generate_and_store(
        self,
        player: Profile,
        subject_date: date,
        *,
        client: object | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> MorningAnalysisResult:
        self.generate_calls += 1
        analysis = _morning_analysis(player.id, subject_date, self._new_status)
        self.session.add(analysis)
        await self.session.flush()
        return MorningAnalysisResult(analysis=analysis, generated=True)


async def _seed_bike_day(
    db_conn: AsyncConnection, user_id: uuid.UUID, workout_id: uuid.UUID, subject: date
) -> None:
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                id=workout_id,
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


@pytest.mark.asyncio
async def test_checkin_recompute_eases_ride_when_verdict_worsens(
    db_conn: AsyncConnection,
) -> None:
    """A check-in that drags the verdict Green→Amber re-runs it and proposes an
    eased ride — subjective is downgrade-only, so this only ever eases."""
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_bike_day(db_conn, user_id, workout_id, subject)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        morning = _StubMorningService(
            session, stored=_morning_analysis(user_id, subject, "Green"), new_status="Amber"
        )

        result = await service.regenerate_after_morning_checkin(
            user, subject, morning_service=morning
        )

        assert result is not None
        assert result.verdict == "Amber"
        assert morning.generate_calls == 1
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert len(proposals) == 1
        assert proposals[0].status == "proposed"  # eased, never auto-approved
        assert proposals[0].structured_workout_ir["origin"] == "amber_regeneration"


@pytest.mark.asyncio
async def test_checkin_always_regenerates_brief_when_verdict_holds(
    db_conn: AsyncConnection,
) -> None:
    """Batch 85: the check-in is the primary generate trigger, so every submit
    regenerates the brief — even a Green→Green check-in that changes nothing. A
    Green verdict still proposes no eased ride."""
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_bike_day(db_conn, user_id, workout_id, subject)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        morning = _StubMorningService(
            session, stored=_morning_analysis(user_id, subject, "Green"), new_status="Green"
        )

        result = await service.regenerate_after_morning_checkin(
            user, subject, morning_service=morning
        )

        assert result is not None  # the brief is always regenerated
        assert result.verdict == "Green"
        assert morning.generate_calls == 1
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert proposals == []  # Green → no eased ride


@pytest.mark.asyncio
async def test_checkin_recompute_leaves_an_approved_ride_untouched(
    db_conn: AsyncConnection,
) -> None:
    """A ride Mark *deliberately approved today* is never silently rewritten — even
    if the verdict would now worsen (Decision #29). Batch 173.1 keys "acted on" to
    an explicit approver (``approved_by_profile_id``), so this is the genuine
    human-approval case (distinct from a pre-delivered baseline)."""
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_bike_day(db_conn, user_id, workout_id, subject)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            WorkoutDeliveryProposal(
                id=uuid.uuid4(),
                user_id=user_id,
                planned_workout_id=workout_id,
                planned_workout_version=1,
                workout_date=subject,
                provider="intervals_icu",
                status="approved",
                proposed_at_utc=datetime(2026, 6, 23, 6, 30),
                approved_at_utc=datetime(2026, 6, 23, 6, 45),
                approved_by_profile_id=user_id,
                structured_workout_ir={"origin": "baseline"},
                intervals_payload={"category": "WORKOUT", "name": "Test"},
                zwo_xml="<workout_file/>",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        morning = _StubMorningService(
            session, stored=_morning_analysis(user_id, subject, "Green"), new_status="Red"
        )

        result = await service.regenerate_after_morning_checkin(
            user, subject, morning_service=morning
        )

        # Batch 85: the brief still regenerates (so his notes/question fold in), but
        # the approved ride is never silently re-adjusted (Decision #29).
        assert result is not None
        assert result.verdict == "Red"
        assert morning.generate_calls == 1
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert len(proposals) == 1  # no new eased proposal was created
        assert proposals[0].status == "approved"  # left exactly as Mark approved it


@pytest.mark.asyncio
async def test_checkin_proposes_adjustment_on_pre_delivered_ride(
    db_conn: AsyncConnection,
) -> None:
    """Batch 173.1: a ride the plan pre-delivered to Zwift (push-on-plan-set,
    Decision #99) is *not* "acted on", so an Amber check-in proposes the eased ride
    then and there — the fix for an adjustment that used to appear only at the 11:00
    backstop. The baseline is never overwritten and the eased ride is never
    auto-pushed."""
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_bike_day(db_conn, user_id, workout_id, subject)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            WorkoutDeliveryProposal(
                id=uuid.uuid4(),
                user_id=user_id,
                planned_workout_id=workout_id,
                planned_workout_version=1,
                workout_date=subject,
                provider="intervals_icu",
                status="pushed",
                proposed_at_utc=datetime(2026, 6, 15, 6, 0),
                pushed_at_utc=datetime(2026, 6, 15, 6, 5),
                intervals_event_id="evt-baseline",
                structured_workout_ir={
                    "origin": "as_planned",
                    "adjustment": {"verdict": None, "changed": False},
                    "plannedWorkoutId": str(workout_id),
                    "plannedWorkoutVersion": 1,
                },
                intervals_payload={"category": "WORKOUT", "name": "Test"},
                zwo_xml="<workout_file/>",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        morning = _StubMorningService(
            session, stored=_morning_analysis(user_id, subject, "Green"), new_status="Amber"
        )

        await service.regenerate_after_morning_checkin(user, subject, morning_service=morning)

        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        eased = [p for p in proposals if p.status == "proposed"]
        baseline = [p for p in proposals if p.status == "pushed"]
        assert len(eased) == 1  # a new proposed adjustment at check-in
        assert eased[0].structured_workout_ir["origin"] == "amber_regeneration"
        assert eased[0].structured_workout_ir["adjustment"]["changed"] is True
        assert len(baseline) == 1  # baseline untouched, never auto-pushed the adjustment


@pytest.mark.asyncio
async def test_regenerate_for_verdict_skips_a_deliberately_edited_ride(
    db_conn: AsyncConnection,
) -> None:
    """Batch 173.1: the acted-on-today guard lives in regenerate_for_verdict, so the
    check-in *and* the 11:00 backstop share one rule. A ride Mark hand-edited
    (pushed, ``adjustment.changed``) is skipped — never silently re-adjusted."""
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_bike_day(db_conn, user_id, workout_id, subject)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            WorkoutDeliveryProposal(
                id=uuid.uuid4(),
                user_id=user_id,
                planned_workout_id=workout_id,
                planned_workout_version=1,
                workout_date=subject,
                provider="intervals_icu",
                status="pushed",
                proposed_at_utc=datetime(2026, 6, 23, 6, 0),
                pushed_at_utc=datetime(2026, 6, 23, 6, 5),
                intervals_event_id="evt-edited",
                structured_workout_ir={
                    "origin": "manual_override",
                    "adjustment": {"changed": True},
                    "plannedWorkoutId": str(workout_id),
                    "plannedWorkoutVersion": 1,
                },
                intervals_payload={"category": "WORKOUT", "name": "Test"},
                zwo_xml="<workout_file/>",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)

        created = await service.regenerate_for_verdict(
            user, subject, analysis=_amber_analysis(user_id, subject)
        )

        assert created == []  # the hand-edited ride is left exactly as Mark set it
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert len(proposals) == 1  # only the manual override remains


@pytest.mark.asyncio
async def test_checkin_regenerates_brief_on_a_no_bike_day(
    db_conn: AsyncConnection,
) -> None:
    """Batch 85: a check-in on a rest / no-ride day still regenerates today's brief
    (a bike-less day is no longer a short-circuit) and proposes nothing."""
    user_id = uuid.uuid4()
    subject = date(2026, 6, 23)
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        morning = _StubMorningService(session, stored=None, new_status="Green")

        result = await service.regenerate_after_morning_checkin(
            user, subject, morning_service=morning
        )

        assert result is not None  # the brief is generated even with no bike workout
        assert morning.generate_calls == 1
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert proposals == []


# ---------------------------------------------------------------------------
# Batch 29 — push-on-plan-set reconciliation
# ---------------------------------------------------------------------------


async def _seed_bike(
    db_conn: AsyncConnection,
    user_id: uuid.UUID,
    workout_id: uuid.UUID,
    *,
    workout_date: date,
    version: int = 1,
    source: str = "test",
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        if await session.get(Profile, user_id) is None:
            session.add(
                Profile(
                    id=user_id,
                    display_name=f"Reconcile {user_id.hex[:6]}",
                    role=UserRole.admin,
                    timezone="Europe/London",
                    is_active=True,
                )
            )
            await session.flush()
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=workout_date,
                version=version,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                intensity_target="105-110% FTP",
                structured_workout=VO2_STRUCTURED,
                source=source,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_reconcile_delivers_baseline_without_approval_and_is_idempotent(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike(db_conn, user_id, workout_id, workout_date=date(2026, 7, 1))
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        delivered = await service.reconcile_deliveries(
            user, start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
        )

        assert len(delivered) == 1
        proposal = delivered[0]
        # Baseline reaches Zwift without any approval step (Decision #99 reversal).
        assert proposal.status == "pushed"
        assert proposal.approved_at_utc is None
        assert proposal.intervals_event_id == "evt_123"
        assert len(fake.payloads) == 1

        audits = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_DELIVERED)
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1

        # Re-running the pass is a no-op: same version already on Zwift.
        again = await service.reconcile_deliveries(
            user, start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
        )
        assert again == []
        assert len(fake.payloads) == 1  # no duplicate create
        assert fake.updates == []


@pytest.mark.asyncio
async def test_reconcile_routes_indoor_to_zwift_and_outdoor_to_garmin(
    db_conn: AsyncConnection,
) -> None:
    """Batch 78: indoor rides deliver to Zwift, outdoor rides to Garmin — isolated."""
    user_id, indoor_id, outdoor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    indoor_day, outdoor_day = date(2026, 7, 20), date(2026, 7, 21)
    # Indoor reuses the default (no delivery key → indoor); outdoor carries the flag.
    await _seed_bike(db_conn, user_id, indoor_id, workout_date=indoor_day)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                id=outdoor_id,
                user_id=user_id,
                workout_date=outdoor_day,
                version=1,
                title="Outdoor endurance",
                workout_type="bike_endurance",
                status="planned",
                is_active=True,
                planned_duration_min=55,
                intensity_target="75% FTP",
                structured_workout=OUTDOOR_STRUCTURED,
                source="test",
            )
        )
        await session.commit()

    fake_intervals = _FakeIntervalsClient()
    fake_garmin = _FakeGarminClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(
            session, intervals_client=fake_intervals, garmin_client=fake_garmin
        )

        delivered = await service.reconcile_deliveries(
            user, start_date=indoor_day, end_date=outdoor_day
        )

        # Only the indoor ride is a Zwift proposal; outdoor never reaches Zwift.
        assert len(delivered) == 1
        assert delivered[0].workout_date == indoor_day
        assert len(fake_intervals.payloads) == 1
        # The outdoor ride went to Garmin instead.
        assert len(fake_garmin.uploads) == 1
        assert fake_garmin.uploads[0][1] == outdoor_day
        garmin_row = await session.scalar(
            select(GarminWorkoutDelivery).where(
                GarminWorkoutDelivery.user_id == user_id,
                GarminWorkoutDelivery.workout_date == outdoor_day,
            )
        )
        assert garmin_row is not None
        assert garmin_row.status == STATUS_PUSHED
        assert garmin_row.planned_workout_id == outdoor_id


@pytest.mark.asyncio
async def test_reconcile_replaces_event_when_slot_is_reversioned(
    db_conn: AsyncConnection,
) -> None:
    user_id, v1_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike(db_conn, user_id, v1_id, workout_date=date(2026, 7, 2), version=1)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        # Deliver the v1 baseline.
        await service.reconcile_deliveries(
            user, start_date=date(2026, 7, 2), end_date=date(2026, 7, 2)
        )
        event_id = await service.rail.latest_delivered_for_date(user_id, date(2026, 7, 2))
        assert event_id is not None
        live_event_id = event_id.intervals_event_id

        # A restructure-style re-version: deactivate v1, add an active v2 same date.
        v1 = await session.get(PlannedWorkout, v1_id)
        assert v1 is not None
        v1.is_active = False
        session.add(
            PlannedWorkout(
                id=uuid.uuid4(),
                user_id=user_id,
                workout_date=date(2026, 7, 2),
                version=2,
                title="Sweet Spot Builder",
                workout_type="bike_sweet_spot",
                status="planned",
                is_active=True,
                planned_duration_min=75,
                intensity_target="88-94% FTP",
                structured_workout=SWEET_SPOT_STRUCTURED,
                source="weekly_restructure",
            )
        )
        await session.commit()

        delivered = await service.reconcile_deliveries(
            user, start_date=date(2026, 7, 2), end_date=date(2026, 7, 2)
        )

        assert len(delivered) == 1
        # Updated in place — same event id, no second create.
        assert [eid for eid, _ in fake.updates] == [live_event_id]
        assert len(fake.payloads) == 1
        assert delivered[0].planned_workout_version == 2
        replaced_audits = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_REPLACED)
                )
            )
            .scalars()
            .all()
        )
        assert len(replaced_audits) == 1


@pytest.mark.asyncio
async def test_reconcile_isolates_a_delivery_failure(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike(db_conn, user_id, workout_id, workout_date=date(2026, 7, 3))
    fake = _FakeIntervalsClient(fail_create=True)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        # A cloud failure must not raise out of the pass (block lock must survive).
        delivered = await service.reconcile_deliveries(
            user, start_date=date(2026, 7, 3), end_date=date(2026, 7, 3)
        )
        assert delivered == []

    # The failure is honestly recorded (Decision #97): a failed proposal, no event.
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        rows = (
            (
                await session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].status == "failed"
        assert rows[0].intervals_event_id is None
        assert rows[0].last_error is not None


@pytest.mark.asyncio
async def test_reconcile_failed_replace_keeps_pointer_and_retries_from_ir_fingerprint(
    db_conn: AsyncConnection,
) -> None:
    user_id, v1_id, v2_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 4)
    await _seed_bike(db_conn, user_id, v1_id, workout_date=day, version=1)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day, end_date=day)

        v1 = await session.get(PlannedWorkout, v1_id)
        assert v1 is not None
        v1.is_active = False
        session.add(
            PlannedWorkout(
                id=v2_id,
                user_id=user_id,
                workout_date=day,
                version=2,
                title="Sweet Spot Builder",
                workout_type="bike_sweet_spot",
                status="planned",
                is_active=True,
                planned_duration_min=75,
                intensity_target="88-94% FTP",
                structured_workout=SWEET_SPOT_STRUCTURED,
                source="weekly_restructure",
            )
        )
        await session.commit()

        fake.fail_update = True
        assert await service.reconcile_deliveries(user, start_date=day, end_date=day) == []

    # The desired v2 plan persists, but the live pointer and delivered IR both
    # remain on v1 after the failed cloud update.
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        live = await session.scalar(
            select(WorkoutDeliveryProposal).where(
                WorkoutDeliveryProposal.user_id == user_id,
                WorkoutDeliveryProposal.status == STATUS_PUSHED,
            )
        )
        assert live is not None
        assert live.planned_workout_id == v1_id
        assert live.planned_workout_version == 1
        assert live.structured_workout_ir["plannedWorkoutId"] == str(v1_id)
        assert live.last_error is not None
        failure = json.loads(live.last_error)
        assert failure["code"] == "intervals_update_failed"
        assert failure["plannedWorkoutId"] == str(v2_id)
        assert failure["plannedWorkoutVersion"] == 2
        assert failure["retryable"] is True

        # Simulate the false pointer persisted by the pre-Batch-158 bug. The IR
        # fingerprint must still force a retry instead of trusting these columns.
        live.planned_workout_id = v2_id
        live.planned_workout_version = 2
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        fake.fail_update = False
        service = ExecutableCoachingService(session, intervals_client=fake)
        delivered = await service.reconcile_deliveries(user, start_date=day, end_date=day)

        assert len(delivered) == 1
        assert len(fake.payloads) == 1
        assert [event_id for event_id, _ in fake.updates] == ["evt_123"]
        assert delivered[0].planned_workout_id == v2_id
        assert delivered[0].planned_workout_version == 2
        assert delivered[0].structured_workout_ir["plannedWorkoutId"] == str(v2_id)
        assert delivered[0].structured_workout_ir["plannedWorkoutVersion"] == 2
        assert delivered[0].last_error is None


@pytest.mark.asyncio
async def test_generic_resync_failed_replace_advances_pointer_only_on_retry_success(
    db_conn: AsyncConnection,
) -> None:
    user_id, v1_id, v2_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 5)
    await _seed_bike(db_conn, user_id, v1_id, workout_date=day, version=1)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day, end_date=day)
        v1 = await session.get(PlannedWorkout, v1_id)
        assert v1 is not None
        v1.is_active = False
        session.add(
            PlannedWorkout(
                id=v2_id,
                user_id=user_id,
                workout_date=day,
                version=2,
                title="Sweet Spot Builder",
                workout_type="bike_sweet_spot",
                status="planned",
                is_active=True,
                planned_duration_min=75,
                intensity_target="88-94% FTP",
                structured_workout=SWEET_SPOT_STRUCTURED,
                source="generic_resync",
            )
        )
        await session.commit()

        fake.fail_update = True
        with pytest.raises(HTTPException, match="intervals.icu update failed"):
            await service.edit_today(
                user,
                planned_workout_id=v2_id,
                duration_scale_pct=80,
                intensity_scale_pct=90,
            )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        live = await session.scalar(
            select(WorkoutDeliveryProposal).where(
                WorkoutDeliveryProposal.user_id == user_id,
                WorkoutDeliveryProposal.status == STATUS_PUSHED,
            )
        )
        assert live is not None
        assert live.planned_workout_id == v1_id
        assert live.planned_workout_version == 1
        assert live.structured_workout_ir["plannedWorkoutId"] == str(v1_id)
        assert live.last_error is not None
        failure = json.loads(live.last_error)
        assert failure["plannedWorkoutId"] == str(v2_id)
        assert failure["plannedWorkoutVersion"] == 2

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        fake.fail_update = False
        service = ExecutableCoachingService(session, intervals_client=fake)
        delivered = await service.edit_today(
            user,
            planned_workout_id=v2_id,
            duration_scale_pct=80,
            intensity_scale_pct=90,
        )

        assert delivered.planned_workout_id == v2_id
        assert delivered.planned_workout_version == 2
        assert delivered.structured_workout_ir["plannedWorkoutId"] == str(v2_id)
        assert delivered.structured_workout_ir["origin"] == "manual_override"
        assert delivered.last_error is None
        assert [event_id for event_id, _ in fake.updates] == ["evt_123"]


@pytest.mark.asyncio
async def test_reconcile_persists_malformed_workout_failure(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 5)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        workout = await session.get(PlannedWorkout, workout_id)
        assert workout is not None
        workout.structured_workout = {}
        await session.commit()
        user = await session.get(Profile, user_id)
        assert user is not None

        service = ExecutableCoachingService(session, intervals_client=fake)
        assert await service.reconcile_deliveries(user, start_date=day, end_date=day) == []

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        failure_row = await session.scalar(
            select(WorkoutDeliveryProposal).where(
                WorkoutDeliveryProposal.planned_workout_id == workout_id
            )
        )
        assert failure_row is not None
        assert failure_row.status == "failed"
        assert failure_row.last_error is not None
        failure = json.loads(failure_row.last_error)
        assert failure["code"] == "malformed_workout"
        assert failure["stage"] == "build_ir"
        assert failure["retryable"] is False
        assert failure["userId"] == str(user_id)
        assert failure["plannedWorkoutId"] == str(workout_id)
        assert failure["plannedWorkoutVersion"] == 1
        assert failure_row.structured_workout_ir["deliveryFailure"] == failure
        assert fake.payloads == []
        assert fake.updates == []


@pytest.mark.asyncio
async def test_reconcile_persists_missing_ftp_failure(
    db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 6)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        async def missing_ftp(_user_id: uuid.UUID) -> int:
            raise HTTPException(status_code=422, detail="FTP is unavailable")

        monkeypatch.setattr(service.rail, "_ftp_watts", missing_ftp)
        assert await service.reconcile_deliveries(user, start_date=day, end_date=day) == []

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        failure_row = await session.scalar(
            select(WorkoutDeliveryProposal).where(
                WorkoutDeliveryProposal.planned_workout_id == workout_id
            )
        )
        assert failure_row is not None
        assert failure_row.last_error is not None
        failure = json.loads(failure_row.last_error)
        assert failure["code"] == "missing_ftp"
        assert failure["stage"] == "load_ftp"
        assert failure["retryable"] is False
        assert failure["plannedWorkoutId"] == str(workout_id)
        assert fake.payloads == []
        assert fake.updates == []


@pytest.mark.asyncio
async def test_reconcile_non_bike_is_an_intentional_no_op_without_failure(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 7)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Non-bike no-op",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=day,
                version=1,
                title="Strength maintenance",
                workout_type="strength_maintenance",
                status="planned",
                is_active=True,
                planned_duration_min=40,
                intensity_target="Moderate",
                structured_workout={
                    "format": "strength",
                    "steps": [{"label": "Lift", "minutes": 40}],
                },
                source="test",
            )
        )
        await session.commit()
        user = await session.get(Profile, user_id)
        assert user is not None
        fake = _FakeIntervalsClient()
        service = ExecutableCoachingService(session, intervals_client=fake)

        assert await service.reconcile_deliveries(user, start_date=day, end_date=day) == []
        assert (
            await session.scalar(
                select(WorkoutDeliveryProposal).where(WorkoutDeliveryProposal.user_id == user_id)
            )
            is None
        )
        assert fake.payloads == []
        assert fake.updates == []


# ---------------------------------------------------------------------------
# Batch 29.3 — Today-card actions: Edit / Approve / Skip / Swap
# ---------------------------------------------------------------------------


async def _active_on(session: AsyncSession, user_id: uuid.UUID, day: date) -> PlannedWorkout | None:
    return await session.scalar(
        select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.workout_date == day,
            PlannedWorkout.is_active.is_(True),
        )
        .order_by(PlannedWorkout.version.desc())
        .limit(1)
    )


async def _active_all_on(
    session: AsyncSession, user_id: uuid.UUID, day: date
) -> list[PlannedWorkout]:
    return list(
        (
            await session.execute(
                select(PlannedWorkout)
                .where(
                    PlannedWorkout.user_id == user_id,
                    PlannedWorkout.workout_date == day,
                    PlannedWorkout.is_active.is_(True),
                )
                .order_by(PlannedWorkout.version)
            )
        )
        .scalars()
        .all()
    )


def _by_category(workouts: list[PlannedWorkout], category: str) -> PlannedWorkout:
    match = [w for w in workouts if category_for_workout_type(w.workout_type) == category]
    assert len(match) == 1, f"expected exactly one {category} workout, got {len(match)}"
    return match[0]


@pytest.mark.asyncio
async def test_edit_today_replaces_live_event_with_override(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 10)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        # Push-on-plan-set has already delivered the baseline event.
        await service.reconcile_deliveries(user, start_date=day, end_date=day)

        delivered = await service.edit_today(
            user, planned_workout_id=workout_id, duration_scale_pct=80, intensity_scale_pct=90
        )

        # Re-synced in place: same event id updated, no second create.
        assert delivered.status == STATUS_PUSHED
        assert delivered.intervals_event_id == "evt_123"
        assert delivered.structured_workout_ir["origin"] == "manual_override"
        override = delivered.structured_workout_ir["adjustment"]["manualOverride"]
        assert override["durationScalePct"] == 80
        assert [eid for eid, _ in fake.updates] == ["evt_123"]
        assert len(fake.payloads) == 1  # the original baseline create only

        audits = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type.like("workout_%"))
                )
            )
            .scalars()
            .all()
        )
        edit_tag = f"edit:{workout_id}:v1"
        edit_audit = next(a for a in audits if a.context_packet.get("tag") == edit_tag)
        assert edit_audit.analysis_type == AUDIT_TYPE_REPLACED


@pytest.mark.asyncio
async def test_edit_today_creates_event_when_slot_has_none(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 11)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        # No baseline delivered yet — Edit must create the event from scratch.
        delivered = await service.edit_today(
            user, planned_workout_id=workout_id, intensity_scale_pct=85
        )

        assert delivered.status == STATUS_PUSHED
        assert delivered.intervals_event_id == "evt_123"
        assert delivered.structured_workout_ir["origin"] == "manual_override"
        assert len(fake.payloads) == 1
        assert fake.updates == []


@pytest.mark.asyncio
async def test_interval_edit_versions_source_and_approves_existing_event_update(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 11)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day, end_date=day)

        delivered = await service.approve_interval_edit(
            user,
            planned_workout_id=workout_id,
            block=EditableIntervalBlock(
                repeat=3,
                work=IntervalLeg(duration_sec=600, power_pct=90, cadence_rpm=85),
                rest=IntervalLeg(duration_sec=300, power_pct=55, cadence_rpm=70),
            ),
        )

        assert delivered.status == STATUS_PUSHED
        assert delivered.approved_at_utc is not None
        assert delivered.intervals_event_id == "evt_123"
        assert delivered.structured_workout_ir["origin"] == "interval_editor"
        assert [event_id for event_id, _ in fake.updates] == ["evt_123"]
        assert 'Power="0.55" Cadence="70"' in delivered.zwo_xml

        rows = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(PlannedWorkout.user_id == user_id)
                    .order_by(PlannedWorkout.version)
                )
            )
            .scalars()
            .all()
        )
        assert [(row.version, row.is_active) for row in rows] == [(1, False), (2, True)]
        edited = rows[1]
        assert edited.source == "interval_editor"
        assert edited.structured_workout["steps"][0] == VO2_STRUCTURED["steps"][0]
        assert edited.structured_workout["steps"][2] == VO2_STRUCTURED["steps"][2]
        assert edited.structured_workout["steps"][1]["block"]["rest"] == {
            "durationSec": 300,
            "powerPct": 55,
            "cadenceRpm": 70,
        }


@pytest.mark.asyncio
async def test_interval_edit_failed_replace_persists_intent_then_reconciles(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 11)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day, end_date=day)
        fake.fail_update = True

        with pytest.raises(HTTPException, match="intervals.icu update failed"):
            await service.approve_interval_edit(
                user,
                planned_workout_id=workout_id,
                block=EditableIntervalBlock(
                    repeat=3,
                    work=IntervalLeg(duration_sec=600, power_pct=90, cadence_rpm=85),
                    rest=IntervalLeg(duration_sec=300, power_pct=55, cadence_rpm=70),
                ),
            )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        workouts = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(PlannedWorkout.user_id == user_id)
                    .order_by(PlannedWorkout.version)
                )
            )
            .scalars()
            .all()
        )
        assert [(workout.version, workout.is_active) for workout in workouts] == [
            (1, False),
            (2, True),
        ]
        edited = workouts[1]
        proposals = (
            (
                await session.execute(
                    select(WorkoutDeliveryProposal)
                    .where(WorkoutDeliveryProposal.user_id == user_id)
                    .order_by(WorkoutDeliveryProposal.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [proposal.status for proposal in proposals] == ["pushed", "failed"]
        live, failed_edit = proposals
        assert live.planned_workout_id == workout_id
        assert live.planned_workout_version == 1
        assert live.structured_workout_ir["plannedWorkoutId"] == str(workout_id)
        assert failed_edit.planned_workout_id == edited.id
        assert failed_edit.planned_workout_version == 2
        assert failed_edit.structured_workout_ir["origin"] == "interval_editor"
        assert failed_edit.last_error is not None
        failure = json.loads(failed_edit.last_error)
        assert failure["code"] == "intervals_update_failed"
        assert failure["plannedWorkoutId"] == str(edited.id)
        assert failure["plannedWorkoutVersion"] == 2
        assert failure["retryable"] is True

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        fake.fail_update = False
        service = ExecutableCoachingService(session, intervals_client=fake)
        delivered = await service.reconcile_deliveries(user, start_date=day, end_date=day)

        assert len(delivered) == 1
        assert delivered[0].id == failed_edit.id
        assert delivered[0].status == STATUS_PUSHED
        assert delivered[0].intervals_event_id == "evt_123"
        assert delivered[0].planned_workout_id == edited.id
        assert delivered[0].planned_workout_version == 2
        assert delivered[0].structured_workout_ir["origin"] == "interval_editor"
        assert delivered[0].last_error is None
        assert [event_id for event_id, _ in fake.updates] == ["evt_123"]
        latest = await service.rail.latest_delivered_for_workout(user_id, edited.id)
        assert latest is not None
        assert latest.id == failed_edit.id
        assert (
            await session.scalar(
                select(WorkoutDeliveryProposal).where(
                    WorkoutDeliveryProposal.user_id == user_id,
                    WorkoutDeliveryProposal.status == "failed",
                )
            )
            is None
        )


@pytest.mark.asyncio
async def test_interval_edit_keeps_red_never_vo2_hard_before_versioning(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 12)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(_morning_analysis(user_id, day, "Red"))
        await session.commit()
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        with pytest.raises(HTTPException, match="Red verdict blocks VO2"):
            await service.approve_interval_edit(
                user,
                planned_workout_id=workout_id,
                block=EditableIntervalBlock(
                    repeat=5,
                    work=IntervalLeg(duration_sec=120, power_pct=120, cadence_rpm=95),
                    rest=IntervalLeg(duration_sec=120, power_pct=60, cadence_rpm=70),
                ),
            )

        rows = (
            (await session.execute(select(PlannedWorkout).where(PlannedWorkout.user_id == user_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == workout_id
        assert rows[0].is_active is True
        assert fake.payloads == []
        assert fake.updates == []


@pytest.mark.asyncio
async def test_approve_adjustment_replaces_event_and_consumes_pending(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 12)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        # Baseline as-planned event is live; the morning produced an Amber adjustment.
        await service.reconcile_deliveries(user, start_date=day, end_date=day)
        await service.regenerate_for_verdict(
            user, day, analysis=_morning_analysis(user_id, day, "Amber")
        )
        workout = await service.rail._planned_workout(user_id, workout_id)
        pending = await service._pending_adjustment(user_id, workout)
        assert pending is not None

        delivered = await service.approve_adjustment(user, planned_workout_id=workout_id)

        # The live event now carries the Amber-adjusted IR (updated in place).
        assert delivered.intervals_event_id == "evt_123"
        assert delivered.structured_workout_ir["origin"] == "amber_regeneration"
        assert [eid for eid, _ in fake.updates] == ["evt_123"]

        # The pending coach adjustment is consumed → the card returns to no-changes.
        await session.refresh(pending)
        assert pending.approved_at_utc is not None
        adherence = await session.scalar(
            select(ManualEntry).where(ManualEntry.planned_workout_id == workout_id)
        )
        assert adherence is not None
        assert adherence.adherence_status == "modified"
        assert adherence.actual_workout_json["source"] == "accepted_adjustment"
        assert adherence.actual_workout_json["changeSummary"] == "Accepted the coach's eased ride."
        assert adherence.actual_workout_json["type"] == "Eased ride"
        assert adherence.actual_workout_json["intensity"] == "75% duration, 14 points easier"
        again = await service._pending_adjustment(
            user_id, await service.rail._planned_workout(user_id, workout_id)
        )
        assert again is None

        approve_audit = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PUSHED)
                )
            )
            .scalars()
            .all()
        )
        assert any(a.context_packet.get("tag") == f"approve:{workout_id}:v1" for a in approve_audit)


@pytest.mark.asyncio
async def test_approve_adjustment_blocks_red_vo2(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 13)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        session.add(_morning_analysis(user_id, day, "Red"))
        await session.commit()
        service = ExecutableCoachingService(session, intervals_client=fake)

        # A pending "changed" proposal that still carries VO2 must never reach Zwift
        # on a Red day, even via Approve (the safety net beyond the transform).
        workout = await service.rail._planned_workout(user_id, workout_id)
        ftp = await service.rail._ftp_watts(user_id)
        vo2_ir = build_structured_workout_ir(workout, ftp_watts=ftp)
        vo2_ir["adjustment"] = {"verdict": "Amber", "changed": True}
        vo2_ir["origin"] = "amber_regeneration"
        assert ir_has_vo2(vo2_ir)
        await service.rail.propose_from_ir(player=user, workout=workout, ir=vo2_ir, commit=True)

        with pytest.raises(HTTPException) as exc_info:
            await service.approve_adjustment(user, planned_workout_id=workout_id)

        assert "Red verdict blocks VO2" in str(exc_info.value)
        assert fake.updates == []
        assert fake.payloads == []
        blocks = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_PUSH_BLOCKED)
                )
            )
            .scalars()
            .all()
        )
        assert len(blocks) == 1


@pytest.mark.asyncio
async def test_skip_deletes_event_and_marks_skipped(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 14)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day, end_date=day)

        workout = await service.skip_workout(user, planned_workout_id=workout_id)

        assert workout.status == WORKOUT_STATUS_SKIPPED
        assert fake.deletes == ["evt_123"]
        live = await service.rail.latest_delivered_for_date(user_id, day)
        assert live is None  # the deleted proposal no longer counts as delivered
        deleted = (
            (
                await session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.planned_workout_id == workout_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert all(p.status == STATUS_DELETED for p in deleted)
        skip_audit = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_SKIPPED)
                )
            )
            .scalars()
            .all()
        )
        assert skip_audit[0].context_packet["intervalsEventId"] == "evt_123"


@pytest.mark.asyncio
async def test_skip_without_live_event_just_marks(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 15)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        workout = await service.skip_workout(user, planned_workout_id=workout_id)

        assert workout.status == WORKOUT_STATUS_SKIPPED
        assert fake.deletes == []
        skip_audit = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_SKIPPED)
                )
            )
            .scalars()
            .all()
        )
        assert skip_audit[0].context_packet["intervalsEventId"] is None


@pytest.mark.asyncio
async def test_skip_refuses_a_logged_done_session(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 15)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            ManualEntry(
                user_id=user_id,
                planned_workout_id=workout_id,
                entry_date=day,
                entry_at_utc=datetime(2026, 7, 15, 9, 0, 0),
                adherence_status="modified",
            )
        )
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        with pytest.raises(HTTPException) as exc:
            await service.skip_workout(user, planned_workout_id=workout_id)

        assert exc.value.status_code == 409
        assert "already done" in str(exc.value.detail)
        workout = await session.get(PlannedWorkout, workout_id)
        assert workout is not None
        assert workout.status == "planned"
        assert fake.deletes == []


@pytest.mark.asyncio
async def test_remove_deactivates_added_workout_and_deletes_event(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 16)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day, source="plan_action_add")
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day, end_date=day)

        workout = await service.remove_workout(user, planned_workout_id=workout_id)

        assert workout.is_active is False
        assert workout.status == "planned"
        assert fake.deletes == ["evt_123"]
        live = await service.rail.latest_delivered_for_workout(user_id, workout_id)
        assert live is None
        removed_audit = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_REMOVED)
                )
            )
            .scalars()
            .all()
        )
        assert removed_audit[0].context_packet["intervalsEventId"] == "evt_123"
        assert removed_audit[0].context_packet["status"] == "removed"


@pytest.mark.asyncio
async def test_remove_rejects_non_added_workout(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 17)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day, source="seed")
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)

        with pytest.raises(HTTPException, match="Only user-added workouts can be removed"):
            await service.remove_workout(user, planned_workout_id=workout_id)


@pytest.mark.asyncio
async def test_swap_moves_into_empty_day_and_stays_idempotent(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    mon, wed = date(2026, 7, 20), date(2026, 7, 22)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=mon)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=mon, end_date=mon)

        new_source = await service.swap_day(user, planned_workout_id=workout_id, target_date=wed)

        # The event moved to the new date; the slot it vacated is now empty.
        assert new_source.workout_date == wed
        assert [eid for eid, _ in fake.updates] == ["evt_123"]
        assert await _active_on(session, user_id, mon) is None
        moved = await _active_on(session, user_id, wed)
        assert moved is not None and moved.title == "VO2 Max 30/30"
        live = await service.rail.latest_delivered_for_date(user_id, wed)
        assert live is not None and live.workout_date == wed
        # Re-pointed at the freshly versioned row (the idempotency-fix invariant).
        assert live.planned_workout_id == moved.id
        assert live.planned_workout_version == moved.version

        move_audit = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_MOVED)
                )
            )
            .scalars()
            .all()
        )
        assert move_audit[0].output_markdown.startswith("Moved")

        # A subsequent reconcile is a no-op — the moved event already matches.
        again = await service.reconcile_deliveries(user, start_date=mon, end_date=wed)
        assert again == []
        assert [eid for eid, _ in fake.updates] == ["evt_123"]  # no extra cloud writes


@pytest.mark.asyncio
async def test_swap_onto_a_skipped_day_deactivates_the_ghost(db_conn: AsyncConnection) -> None:
    """Batch 213, the exact 08-11 production shape: ``_active_workout_on``
    treats a skipped occupant as "no swap partner" (nothing to swap with), but
    that must not leave the skipped row as a second active row once its date
    gets a reslotted replacement — the ghost `weekly_mix` was double-counting."""
    user_id = uuid.uuid4()
    ghost_id, source_id = uuid.uuid4(), uuid.uuid4()
    mon, wed = date(2026, 8, 10), date(2026, 8, 12)
    await _seed_bike(db_conn, user_id, source_id, workout_date=mon)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                id=ghost_id,
                user_id=user_id,
                workout_date=wed,
                version=1,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="skipped",
                is_active=True,
                planned_duration_min=60,
                intensity_target="105-110% FTP",
                structured_workout=VO2_STRUCTURED,
                source="test",
            )
        )
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=mon, end_date=mon)

        new_source = await service.swap_day(user, planned_workout_id=source_id, target_date=wed)
        assert new_source.workout_date == wed

        # Exactly one active row remains on the target date — the skipped ghost
        # is gone, not sitting beside the new session.
        active_on_wed = await _active_all_on(session, user_id, wed)
        assert [w.id for w in active_on_wed] == [new_source.id]
        ghost = await session.get(PlannedWorkout, ghost_id)
        assert ghost is not None and ghost.is_active is False


@pytest.mark.asyncio
async def test_swap_swaps_two_occupied_days(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    a_id, b_id = uuid.uuid4(), uuid.uuid4()
    mon, wed = date(2026, 7, 27), date(2026, 7, 29)
    await _seed_bike(db_conn, user_id, a_id, workout_date=mon)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                id=b_id,
                user_id=user_id,
                workout_date=wed,
                version=1,
                title="Sweet Spot Builder",
                workout_type="bike_sweet_spot",
                status="planned",
                is_active=True,
                planned_duration_min=75,
                intensity_target="88-94% FTP",
                structured_workout=SWEET_SPOT_STRUCTURED,
                source="test",
            )
        )
        await session.commit()
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=mon, end_date=wed)

        await service.swap_day(user, planned_workout_id=a_id, target_date=wed)

        # Both days swapped content; both events moved (two cloud updates).
        assert len(fake.updates) == 2
        mon_now = await _active_on(session, user_id, mon)
        wed_now = await _active_on(session, user_id, wed)
        assert mon_now is not None and mon_now.title == "Sweet Spot Builder"
        assert wed_now is not None and wed_now.title == "VO2 Max 30/30"

        move_audit = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_MOVED)
                )
            )
            .scalars()
            .all()
        )
        assert move_audit[0].output_markdown.startswith("Swapped")

        # Re-pointing holds for both slots → reconcile is idempotent.
        again = await service.reconcile_deliveries(user, start_date=mon, end_date=wed)
        assert again == []
        assert len(fake.updates) == 2


@pytest.mark.asyncio
async def test_swap_is_honest_when_the_cloud_move_fails(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    mon, wed = date(2026, 8, 3), date(2026, 8, 5)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=mon)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        # Deliver the baseline with a working client first.
        await ExecutableCoachingService(
            session, intervals_client=_FakeIntervalsClient()
        ).reconcile_deliveries(user, start_date=mon, end_date=mon)

        # Now the cloud move fails: the local plan must not diverge (Decision #97).
        failing = ExecutableCoachingService(
            session, intervals_client=_FakeIntervalsClient(fail_update=True)
        )
        with pytest.raises(HTTPException):
            await failing.swap_day(user, planned_workout_id=workout_id, target_date=wed)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        # The source workout is untouched and no row was re-slotted to the target.
        source = await _active_on(session, user_id, mon)
        assert source is not None and source.id == workout_id
        assert await _active_on(session, user_id, wed) is None


@pytest.mark.asyncio
async def test_swap_day_refuses_a_completed_session(db_conn: AsyncConnection) -> None:
    """Batch 60: a completed session can't be re-slotted — swap_day 409s before it
    touches Zwift, so a finished ride stays put."""
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    source_date, target_date = date(2026, 8, 3), date(2026, 8, 4)
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=source_date,
                version=1,
                title="Tempo ride",
                workout_type="bike_tempo",
                status="completed",
                is_active=True,
                source="test",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)
        with pytest.raises(HTTPException) as exc:
            await service.swap_day(user, planned_workout_id=workout_id, target_date=target_date)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_swap_ride_off_a_two_session_day_leaves_strength(db_conn: AsyncConnection) -> None:
    """Batch 65: moving a ride off a split day (ride + Bodyweight) relocates only the
    ride — the same-day strength stays put because swap-target detection is
    category-scoped (never drags a second same-day workout)."""
    user_id = uuid.uuid4()
    ride_id, strength_id = uuid.uuid4(), uuid.uuid4()
    sat, thu = date(2026, 7, 11), date(2026, 7, 9)
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                PlannedWorkout(
                    id=ride_id,
                    user_id=user_id,
                    workout_date=sat,
                    version=1,
                    title="Z2 + Neuromuscular",
                    workout_type="bike_endurance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=58,
                    intensity_target="Zone 2 ~65-72% FTP",
                    structured_workout=VO2_STRUCTURED,
                    source="test",
                ),
                PlannedWorkout(
                    id=strength_id,
                    user_id=user_id,
                    workout_date=sat,
                    version=2,
                    title="Bodyweight",
                    workout_type="strength_maintenance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=15,
                    intensity_target="Bodyweight circuit",
                    structured_workout={"format": "strength", "focus": "bodyweight"},
                    source="test",
                ),
            ]
        )
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=sat, end_date=sat)

        moved = await service.swap_day(user, planned_workout_id=ride_id, target_date=thu)

        assert moved.workout_date == thu
        # Saturday keeps exactly the Bodyweight strength; the ride has left.
        sat_active = await _active_all_on(session, user_id, sat)
        assert [w.title for w in sat_active] == ["Bodyweight"]
        # Thursday now holds only the ride — no strength dragged along.
        thu_active = await _active_all_on(session, user_id, thu)
        assert [w.workout_type for w in thu_active] == ["bike_endurance"]
        # Only the ride carries a Zwift event, so exactly one cloud move happened.
        assert [eid for eid, _ in fake.updates] == ["evt_123"]


@pytest.mark.asyncio
async def test_swap_two_ride_days_each_keep_their_strength(db_conn: AsyncConnection) -> None:
    """Batch 65: swapping two ride days exchanges the rides only — each day's
    strength session stays exactly where it was."""
    user_id = uuid.uuid4()
    ride_a, strength_a = uuid.uuid4(), uuid.uuid4()
    ride_b, strength_b = uuid.uuid4(), uuid.uuid4()
    day_a, day_b = date(2026, 7, 7), date(2026, 7, 11)
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                PlannedWorkout(
                    id=ride_a,
                    user_id=user_id,
                    workout_date=day_a,
                    version=1,
                    title="VO2 A",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    intensity_target="105-110% FTP",
                    structured_workout=VO2_STRUCTURED,
                    source="test",
                ),
                PlannedWorkout(
                    id=strength_a,
                    user_id=user_id,
                    workout_date=day_a,
                    version=2,
                    title="Dumbbells A",
                    workout_type="strength_maintenance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=22,
                    intensity_target="Dumbbell circuit",
                    structured_workout={"format": "strength", "focus": "dumbbell"},
                    source="test",
                ),
                PlannedWorkout(
                    id=ride_b,
                    user_id=user_id,
                    workout_date=day_b,
                    version=1,
                    title="Sweet Spot B",
                    workout_type="bike_sweet_spot",
                    status="planned",
                    is_active=True,
                    planned_duration_min=75,
                    intensity_target="88-94% FTP",
                    structured_workout=SWEET_SPOT_STRUCTURED,
                    source="test",
                ),
                PlannedWorkout(
                    id=strength_b,
                    user_id=user_id,
                    workout_date=day_b,
                    version=2,
                    title="Bodyweight B",
                    workout_type="strength_maintenance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=15,
                    intensity_target="Bodyweight circuit",
                    structured_workout={"format": "strength", "focus": "bodyweight"},
                    source="test",
                ),
            ]
        )
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day_a, end_date=day_b)

        await service.swap_day(user, planned_workout_id=ride_a, target_date=day_b)

        a_active = await _active_all_on(session, user_id, day_a)
        b_active = await _active_all_on(session, user_id, day_b)
        # Rides exchanged days...
        assert _by_category(a_active, "cycle").title == "Sweet Spot B"
        assert _by_category(b_active, "cycle").title == "VO2 A"
        # ...while each day's strength stayed exactly where it was.
        assert _by_category(a_active, "weights").title == "Dumbbells A"
        assert _by_category(b_active, "weights").title == "Bodyweight B"
        # Two rides moved (two cloud updates); the strength rows carry no event.
        assert len(fake.updates) == 2
