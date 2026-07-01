"""Tests for Batch 22 hypothesis evaluation.

Covers the deterministic pure evaluators (gate / correlation / group compare and
their supported/refuted/inconclusive mapping + sample gates), the never-auto-conclude
guard, and the idempotent audit in ``analyses``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, PlanBlock, Sleep, TemperatureReading
from src.models.profile import Profile, UserRole
from src.services.experiment_evaluation import (
    AUDIT_TYPE_EVALUATION,
    EARLY_WAKING_OUTCOME,
    RECOMMEND_INCONCLUSIVE,
    RECOMMEND_REFUTED,
    RECOMMEND_SUPPORTED,
    SLUG_COLLAGEN,
    SLUG_EARLY_WAKING,
    STATUS_INSUFFICIENT,
    STATUS_NO_EVALUATOR,
    STATUS_OK,
    ExperimentEvaluationService,
    LabeledNight,
    SleepNight,
    evaluate_correlation,
    evaluate_gate_streak,
    evaluate_group_compare,
)
from src.services.experiment_tracker import ExperimentTrackerService

# ---------------------------------------------------------------------------
# Pure: gate streak (collagen)
# ---------------------------------------------------------------------------

D0 = date(2026, 6, 1)


def _days(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def test_gate_met_recommends_supported() -> None:
    # 10 consecutive nights all at/above the floor → gate (7) met.
    nights = [SleepNight(day=d, score=80.0) for d in _days(10)]
    result = evaluate_gate_streak(nights, gate_nights=7, floor=74)
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["currentStreak"] == 10
    assert result.evidence["gateMet"] is True


def test_gate_not_met_recommends_inconclusive() -> None:
    # Recent nights dip below the floor → short trailing streak.
    scores = [80, 80, 80, 80, 80, 70, 80, 80]  # last clean run is only 2
    nights = [SleepNight(day=d, score=float(s)) for d, s in zip(_days(8), scores, strict=True)]
    result = evaluate_gate_streak(nights, gate_nights=7, floor=74)
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert result.evidence["currentStreak"] == 2
    assert result.evidence["gateMet"] is False


def test_gate_streak_breaks_on_calendar_gap() -> None:
    # A missing night breaks the consecutive run even if scores are clean.
    nights = [SleepNight(day=d, score=80.0) for d in _days(10)]
    # Drop day index 7 to introduce a gap before the last two nights.
    nights = [n for n in nights if (n.day - D0).days != 7]
    result = evaluate_gate_streak(nights, gate_nights=7, floor=74)
    assert result.evidence["currentStreak"] == 2  # only the final two consecutive nights


def test_gate_insufficient_history_skips() -> None:
    nights = [SleepNight(day=d, score=80.0) for d in _days(3)]
    result = evaluate_gate_streak(nights, gate_nights=7, floor=74, min_samples=5)
    assert result.status == STATUS_INSUFFICIENT
    assert result.recommendation is None


# ---------------------------------------------------------------------------
# Pure: correlation (early waking)
# ---------------------------------------------------------------------------


def _corr_records(outcome: list[float], driver: list[float]) -> list[dict[str, float | None]]:
    return [
        {EARLY_WAKING_OUTCOME: o, "overnight_low_c": d}
        for o, d in zip(outcome, driver, strict=True)
    ]


def test_correlation_strong_recommends_supported() -> None:
    # Perfectly correlated driver and outcome.
    outcome = [float(i) for i in range(10)]
    driver = [float(i) * 2 for i in range(10)]
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
    )
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["strongestDriver"] == "overnight_low_c"


def test_correlation_none_recommends_refuted() -> None:
    # No relationship: constructed so the covariance is exactly zero.
    driver = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    outcome = [1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0]
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
    )
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_REFUTED


def test_correlation_insufficient_samples_skips() -> None:
    outcome = [1.0, 2.0, 3.0]
    driver = [1.0, 2.0, 3.0]
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
    )
    assert result.status == STATUS_INSUFFICIENT
    assert result.recommendation is None


def test_correlation_surfaces_unmeasured_drivers() -> None:
    outcome = [float(i) for i in range(10)]
    driver = [float(i) for i in range(10)]
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
        unmeasured=("alcohol", "late_snack"),
    )
    assert result.evidence["unmeasuredDrivers"] == ["alcohol", "late_snack"]


# ---------------------------------------------------------------------------
# Pure: group compare (recovery-week disruption)
# ---------------------------------------------------------------------------


def test_group_compare_recovery_worse_recommends_supported() -> None:
    nights = [LabeledNight(day=_days(20)[i], value=70.0, group="recovery") for i in range(5)]
    nights += [LabeledNight(day=_days(20)[10 + i], value=80.0, group="build") for i in range(5)]
    result = evaluate_group_compare(nights, threshold=3.0)
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["delta"] == -10.0


def test_group_compare_recovery_better_recommends_refuted() -> None:
    nights = [LabeledNight(day=_days(20)[i], value=85.0, group="recovery") for i in range(5)]
    nights += [LabeledNight(day=_days(20)[10 + i], value=75.0, group="build") for i in range(5)]
    result = evaluate_group_compare(nights, threshold=3.0)
    assert result.recommendation == RECOMMEND_REFUTED


def test_group_compare_small_gap_inconclusive() -> None:
    nights = [LabeledNight(day=_days(20)[i], value=79.0, group="recovery") for i in range(5)]
    nights += [LabeledNight(day=_days(20)[10 + i], value=80.0, group="build") for i in range(5)]
    result = evaluate_group_compare(nights, threshold=3.0)
    assert result.recommendation == RECOMMEND_INCONCLUSIVE


def test_group_compare_insufficient_group_skips() -> None:
    nights = [LabeledNight(day=_days(20)[i], value=70.0, group="recovery") for i in range(2)]
    nights += [LabeledNight(day=_days(20)[10 + i], value=80.0, group="build") for i in range(5)]
    result = evaluate_group_compare(nights, min_per_group=4)
    assert result.status == STATUS_INSUFFICIENT
    assert result.recommendation is None


# ---------------------------------------------------------------------------
# DB-backed
# ---------------------------------------------------------------------------


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name=f"Eval Test {user_id.hex[:8]}",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_service_collagen_gate_met(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    as_of = date(2026, 6, 30)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=as_of - timedelta(days=9 - i),
                    score=78,
                    age_adjusted_score=80,
                )
            )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        tracker = ExperimentTrackerService(session)
        await tracker.seed_defaults(user)
        experiments = await tracker.list_experiments(user, seed=False)
        collagen = next(
            e for e in experiments if e.success_criteria_json.get("slug") == SLUG_COLLAGEN
        )
        service = ExperimentEvaluationService(session)
        result = await service.evaluate(user, collagen, as_of=as_of)
        assert result.status == STATUS_OK
        assert result.recommendation == RECOMMEND_SUPPORTED
        assert result.evidence["currentStreak"] == 10


@pytest.mark.asyncio
async def test_service_recovery_week_uses_plan_blocks(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    as_of = date(2026, 6, 30)
    recovery_start = as_of - timedelta(days=40)
    recovery_end = as_of - timedelta(days=34)
    build_start = as_of - timedelta(days=33)
    build_end = as_of - timedelta(days=20)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlanBlock(
                user_id=user_id,
                name="Recovery",
                block_type="recovery",
                start_date=recovery_start,
                end_date=recovery_end,
            )
        )
        session.add(
            PlanBlock(
                user_id=user_id,
                name="Build 1",
                block_type="build1",
                start_date=build_start,
                end_date=build_end,
            )
        )
        # 5 worse nights in the recovery block, 5 better nights in the build block.
        for i in range(5):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=recovery_start + timedelta(days=i),
                    age_adjusted_score=70,
                )
            )
        for i in range(5):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=build_start + timedelta(days=i),
                    age_adjusted_score=82,
                )
            )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        tracker = ExperimentTrackerService(session)
        await tracker.seed_defaults(user)
        experiments = await tracker.list_experiments(user, seed=False)
        recovery = next(
            e
            for e in experiments
            if e.success_criteria_json.get("slug") == "recovery_week_disruption"
        )
        service = ExperimentEvaluationService(session)
        result = await service.evaluate(user, recovery, as_of=as_of)
        assert result.status == STATUS_OK
        assert result.recommendation == RECOMMEND_SUPPORTED
        assert result.evidence["recoveryNights"] == 5
        assert result.evidence["buildNights"] == 5


@pytest.mark.asyncio
async def test_run_records_audit_and_is_idempotent(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    as_of = date(2026, 6, 30)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=as_of - timedelta(days=9 - i),
                    age_adjusted_score=80,
                )
            )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        tracker = ExperimentTrackerService(session)
        await tracker.seed_defaults(user)
        experiments = await tracker.list_experiments(user, seed=False)
        collagen = next(
            e for e in experiments if e.success_criteria_json.get("slug") == SLUG_COLLAGEN
        )
        service = ExperimentEvaluationService(session)

        result1, analysis1 = await service.run(user, collagen.id, as_of=as_of)
        assert result1.recommendation == RECOMMEND_SUPPORTED
        assert analysis1.analysis_type == AUDIT_TYPE_EVALUATION
        assert analysis1.context_packet["experimentId"] == str(collagen.id)

        # Second run on the same subject date must not create a duplicate.
        _result2, analysis2 = await service.run(user, collagen.id, as_of=as_of)
        assert analysis2.id == analysis1.id

        rows = (
            (
                await session.execute(
                    select(Analysis).where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == AUDIT_TYPE_EVALUATION,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_evaluation_never_changes_status(db_conn: AsyncConnection) -> None:
    """The never-auto-conclude guard (#72): evaluation must not alter status."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    as_of = date(2026, 6, 30)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=as_of - timedelta(days=9 - i),
                    age_adjusted_score=80,
                )
            )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        tracker = ExperimentTrackerService(session)
        created = await tracker.seed_defaults(user)
        collagen = next(e for e in created if e.success_criteria_json.get("slug") == SLUG_COLLAGEN)
        before = collagen.status
        service = ExperimentEvaluationService(session)
        await service.run(user, collagen.id, as_of=as_of)
        await session.refresh(collagen)
        assert collagen.status == before  # still active, not concluded


@pytest.mark.asyncio
async def test_early_waking_evaluator_uses_bedroom_temperature_candidates(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    as_of = date(2026, 7, 10)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            wake_date = as_of - timedelta(days=9 - i)
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=wake_date,
                    awake_sleep_sec=(i + 1) * 60,
                    avg_sleep_stress=30.0,
                )
            )
            night_start_utc = datetime(wake_date.year, wake_date.month, wake_date.day) - timedelta(
                hours=3
            )
            for j in range(i + 1):
                session.add(
                    TemperatureReading(
                        user_id=user_id,
                        captured_at_utc=night_start_utc + timedelta(minutes=15 * j),
                        temperature_c=20.2,
                    )
                )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        tracker = ExperimentTrackerService(session)
        await tracker.seed_defaults(user)
        experiments = await tracker.list_experiments(user, seed=False)
        early_waking = next(
            e for e in experiments if e.success_criteria_json.get("slug") == SLUG_EARLY_WAKING
        )
        service = ExperimentEvaluationService(session)
        result = await service.evaluate(user, early_waking, as_of=as_of)

    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["strongestDriver"] == "bedroom_warning_minutes"
    assert result.evidence["correlations"][0]["summary"] is not None
    assert any("Nights with 60+ min above 19.5C" in reason for reason in result.reasons)


@pytest.mark.asyncio
async def test_no_evaluator_for_plain_experiment(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        tracker = ExperimentTrackerService(session)
        experiment = await tracker.create_experiment(
            user, title="Magnesium", hypothesis="Improves deep sleep."
        )
        service = ExperimentEvaluationService(session)
        result = await service.evaluate(user, experiment, as_of=date(2026, 6, 30))
        assert result.status == STATUS_NO_EVALUATOR
        assert result.recommendation is None
