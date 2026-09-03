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

from src.models.coaching import Analysis, Experiment, PlanBlock, Sleep, TemperatureReading
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
    RemInterventionNight,
    SleepNight,
    evaluate_correlation,
    evaluate_gate_streak,
    evaluate_group_compare,
    evaluate_rem_interventions,
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
    # Strongly but not perfectly correlated, so the interval is computable and
    # comfortably clear of zero (Batch 249: a perfect r has no Fisher interval).
    outcome = [float(i) for i in range(20)]
    driver = [float(i) * 2 + (1.0 if i % 3 == 0 else 0.0) for i in range(20)]
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
    )
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["strongestDriver"] == "overnight_low_c"
    assert "range" in result.reasons[0]


def test_ten_flat_nights_cannot_refute_a_trigger() -> None:
    """Batch 249 (HS240-07): "no trigger" is a claim, and ten nights cannot make it.

    Zero correlation over ten nights has a 95% interval running roughly -0.63 to
    +0.63 — it is consistent with a *large* association in either direction. The
    old rule read that as ``refuted``, which said something about Mark when it
    only had something to say about the window.
    """
    driver = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    outcome = [1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0]
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
    )
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert "cannot separate it from no association" in result.reasons[0]


def test_correlation_none_recommends_refuted_once_the_window_can_rule_it_out() -> None:
    """``refuted`` survives — it just has to earn it with enough nights.

    Fifty-two nights of exactly zero covariance narrows the interval inside the
    module's own ``moderate`` line, which is what licenses "no identifiable
    trigger among them".
    """
    period_driver = [0.0, 1.0, 0.0, 1.0]
    period_outcome = [0.0, 0.0, 1.0, 1.0]
    driver = period_driver * 13
    outcome = period_outcome * 13
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
    )
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_REFUTED
    assert "rules out anything as large as" in result.reasons[0]


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
    nights = [LabeledNight(day=_days(40)[i], value=70.0, group="recovery") for i in range(7)]
    nights += [LabeledNight(day=_days(40)[10 + i], value=80.0, group="build") for i in range(7)]
    result = evaluate_group_compare(nights, threshold=3.0)
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["delta"] == -10.0
    assert result.evidence["deltaInterval"] == [-10.0, -10.0]


def test_group_compare_recovery_better_recommends_refuted() -> None:
    nights = [LabeledNight(day=_days(40)[i], value=85.0, group="recovery") for i in range(7)]
    nights += [LabeledNight(day=_days(40)[10 + i], value=75.0, group="build") for i in range(7)]
    result = evaluate_group_compare(nights, threshold=3.0)
    assert result.recommendation == RECOMMEND_REFUTED


def test_group_compare_small_gap_inconclusive() -> None:
    nights = [LabeledNight(day=_days(40)[i], value=79.0, group="recovery") for i in range(7)]
    nights += [LabeledNight(day=_days(40)[10 + i], value=80.0, group="build") for i in range(7)]
    result = evaluate_group_compare(nights, threshold=3.0)
    assert result.recommendation == RECOMMEND_INCONCLUSIVE


def test_group_compare_a_big_gap_inside_real_dispersion_is_not_a_direction() -> None:
    """Batch 249 (HS240-07): the threshold is necessary, not sufficient.

    A 4-point gap between two arms that each swing by ten points is not a result,
    and the old rule called it ``supported`` because 4 > 3. Mark's measured
    age-adjusted sleep SD is 9.66, so this is the shape of the real data.
    """
    recovery_values = [70.0, 80.0, 66.0, 84.0, 72.0, 78.0, 74.0]
    build_values = [76.0, 84.0, 70.0, 88.0, 76.0, 82.0, 78.0]
    nights = [
        LabeledNight(day=_days(40)[i], value=value, group="recovery")
        for i, value in enumerate(recovery_values)
    ]
    nights += [
        LabeledNight(day=_days(40)[10 + i], value=value, group="build")
        for i, value in enumerate(build_values)
    ]
    result = evaluate_group_compare(nights, threshold=3.0)
    assert result.evidence["delta"] <= -3.0
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert "cannot call it" in result.reasons[0]


def test_group_compare_insufficient_group_skips() -> None:
    nights = [LabeledNight(day=_days(20)[i], value=70.0, group="recovery") for i in range(2)]
    nights += [LabeledNight(day=_days(20)[10 + i], value=80.0, group="build") for i in range(5)]
    result = evaluate_group_compare(nights, min_per_group=4)
    assert result.status == STATUS_INSUFFICIENT
    assert result.recommendation is None


def test_group_compare_five_nights_an_arm_is_now_below_the_floor() -> None:
    """Batch 249 raised the floor from four to seven — one full weekly cycle."""
    nights = [LabeledNight(day=_days(40)[i], value=70.0, group="recovery") for i in range(5)]
    nights += [LabeledNight(day=_days(40)[10 + i], value=80.0, group="build") for i in range(5)]
    result = evaluate_group_compare(nights)
    assert result.status == STATUS_INSUFFICIENT
    assert result.recommendation is None


# ---------------------------------------------------------------------------
# Pure: REM intervention applied-vs-not-applied comparison (Batch 221)
# ---------------------------------------------------------------------------


def _rem_night(
    index: int,
    *,
    response: str,
    rem_pct: float | None,
    awake_min: float | None,
) -> RemInterventionNight:
    return RemInterventionNight(
        day=D0 + timedelta(days=index),
        intervention_id="consistent_wake",
        response=response,
        rem_sleep_pct=rem_pct,
        awake_min=awake_min,
    )


def test_rem_intervention_unknown_and_missing_outcomes_do_not_become_comparisons() -> None:
    nights = [
        _rem_night(0, response="applied", rem_pct=24, awake_min=30),
        _rem_night(1, response="not_applied", rem_pct=20, awake_min=40),
        _rem_night(2, response="unknown", rem_pct=10, awake_min=90),
        _rem_night(3, response="not_applied", rem_pct=None, awake_min=40),
    ]

    result = evaluate_rem_interventions(nights, min_per_response=2)

    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert result.sample_count == 2
    assert result.evidence["confidence"] == "low"
    assert "Unknown application is excluded" in result.reasons[1]


def test_rem_intervention_directional_improvement_is_conservative_and_descriptive() -> None:
    nights = [
        *[
            _rem_night(index, response="applied", rem_pct=24 + index / 10, awake_min=30)
            for index in range(7)
        ],
        *[
            _rem_night(index + 7, response="not_applied", rem_pct=20, awake_min=42)
            for index in range(7)
        ],
    ]

    result = evaluate_rem_interventions(nights)

    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["interventionId"] == "consistent_wake"
    assert result.evidence["remPctDelta"] >= 2
    assert result.evidence["awakeMinDelta"] <= -10
    assert result.evidence["confidence"] == "low"
    assert result.evidence["remPctDeltaInterval"] is not None
    assert "range" in result.reasons[0]
    assert "observational comparison" in result.reasons[-1]


def test_rem_intervention_three_nights_an_arm_is_below_the_floor() -> None:
    """Batch 249 (HS240-07): the exact fixture that used to read ``supported``.

    Three nights an arm against Mark's measured REM dispersion (SD 4.80 points
    over 437 nights) gives a standard error of 3.92, so the 2.0-point decision
    line sits at half an SE — a line noise crosses a large fraction of the time.
    Seven an arm is one full week, which is the shortest window the weekly
    rotation does not confound.
    """
    nights = [
        *[
            _rem_night(index, response="applied", rem_pct=24 + index / 10, awake_min=30)
            for index in range(3)
        ],
        *[
            _rem_night(index + 3, response="not_applied", rem_pct=20, awake_min=42)
            for index in range(3)
        ],
    ]

    result = evaluate_rem_interventions(nights)

    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert result.evidence["minimumPerResponse"] == 7
    assert "still needs" in result.reasons[0]


def test_rem_intervention_a_threshold_crossing_inside_the_noise_is_described_not_called() -> None:
    """Seven an arm, a 3-point REM gap, and nights that swing by five.

    The gap clears the 2.0-point line and the awake direction agrees, so the old
    rule would have said ``supported``. The interval spans zero, so this window
    cannot tell the two apart and the loop says exactly that.
    """
    applied = [26.0, 19.0, 24.0, 17.0, 25.0, 20.0, 22.0]
    not_applied = [22.0, 16.0, 21.0, 15.0, 22.0, 17.0, 19.0]
    nights = [
        *[
            _rem_night(index, response="applied", rem_pct=value, awake_min=30)
            for index, value in enumerate(applied)
        ],
        *[
            _rem_night(index + 7, response="not_applied", rem_pct=value, awake_min=32)
            for index, value in enumerate(not_applied)
        ],
    ]

    result = evaluate_rem_interventions(nights)

    assert result.evidence["remPctDelta"] >= 2
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert any("cannot tell these apart" in reason for reason in result.reasons)


def test_rem_intervention_mixed_outcomes_remain_inconclusive() -> None:
    nights = [
        *[_rem_night(index, response="applied", rem_pct=24, awake_min=55) for index in range(7)],
        *[
            _rem_night(index + 7, response="not_applied", rem_pct=20, awake_min=35)
            for index in range(7)
        ],
    ]

    result = evaluate_rem_interventions(nights)

    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert result.evidence["remPctDelta"] == 4
    assert result.evidence["awakeMinDelta"] == 20


# ---------------------------------------------------------------------------
# DB-backed
# ---------------------------------------------------------------------------


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name=f"Eval Test {user_id.hex[:8]}",
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
        # Batch 249 raised the floor from four to seven nights an arm — one full
        # weekly cycle — so the window is seven worse recovery nights against
        # seven better build nights.
        for i in range(7):
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=recovery_start + timedelta(days=i),
                    age_adjusted_score=70,
                )
            )
        for i in range(7):
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
        assert result.evidence["recoveryNights"] == 7
        assert result.evidence["buildNights"] == 7
        # Batch 249: the direction is carried by an interval, not by the gap alone.
        assert result.evidence["deltaInterval"] == [-12.0, -12.0]


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
    # Batch 249: the old fixture ramped warm ticks and awake minutes together
    # with the day index, so the driver, the outcome and the *calendar* all
    # marched in lockstep — indistinguishable from a pure seasonal trend, and now
    # correctly refused. The warm nights are therefore scattered through the
    # window instead of accumulating across it: r(driver, date) = 0.10, so the
    # association survives adjustment at 0.91 with an interval of 0.62 to 0.98.
    warm_ticks = [3, 9, 1, 7, 5, 10, 2, 8, 4, 6]
    awake_jitter = [1, -1, 2, -2, 1, -1, 2, -2, 1, -1]
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            wake_date = as_of - timedelta(days=9 - i)
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=wake_date,
                    awake_sleep_sec=(20 + warm_ticks[i] + awake_jitter[i]) * 60,
                    avg_sleep_stress=30.0,
                )
            )
            night_start_utc = datetime(wake_date.year, wake_date.month, wake_date.day) - timedelta(
                hours=3
            )
            for j in range(warm_ticks[i]):
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
    assert result.evidence["correlations"][0]["interval"] is not None
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


def test_stored_criteria_cannot_lower_the_evidence_floor() -> None:
    """Batch 249: the live experiment carries ``minimumPerResponse: 3``.

    It was written when the constant was 3, so raising the constant alone would
    have changed nothing for the only experiment this evaluator actually runs on
    in production. Criteria may ask for *more* evidence than the power
    calculation demands; they may not ask for less.
    """
    experiment = Experiment(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="REM intervention rotation",
        hypothesis="Does the rotating lever help?",
        status="active",
        success_criteria_json={
            "kind": "rem_intervention",
            "minimumPerResponse": 3,
        },
    )
    service = ExperimentEvaluationService.__new__(ExperimentEvaluationService)
    result = service._evaluate_rem_intervention(experiment, experiment.success_criteria_json)
    assert result.evidence["minimumPerResponse"] == 7

    raised = dict(experiment.success_criteria_json)
    raised["minimumPerResponse"] = 14
    result_raised = service._evaluate_rem_intervention(experiment, raised)
    assert result_raised.evidence["minimumPerResponse"] == 14


def test_a_real_but_weak_correlation_is_not_described_as_indistinguishable() -> None:
    """Two different inconclusive answers must not share one sentence.

    Production on 2026-09-03: ``sleep_stress_avg`` at r = +0.34 over 121 nights
    has an interval of +0.17 to +0.49 — it *does* separate from zero, and calling
    that "cannot separate it from no association" would be a new false statement
    installed by the batch that exists to remove one.
    """
    outcome = [float((i * 11) % 17) for i in range(121)]
    driver = [value * 0.15 + float((i * 5) % 7) for i, value in enumerate(outcome)]
    result = evaluate_correlation(
        _corr_records(outcome, driver),
        outcome_key=EARLY_WAKING_OUTCOME,
        driver_keys=("overnight_low_c",),
        min_samples=8,
    )
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert "a real but weak association" in result.reasons[0]
    assert "cannot separate it from no association" not in result.reasons[0]
