"""Batch 275 — Mark's observation becomes a testable question.

On 19 September 2026 Mark said his HRV drops in recovery weeks — three cycles, his
own numbers — and the coach spent three paragraphs declining to call it
established. It was right that nothing had tested it, and the reason was
structural: the one comparator that could have answered him read the ``sleep``
table only, and HRV lives in ``daily_metrics``.

275.2 is the binding half. Making the comparator generic over the metric without
giving each metric its own threshold and direction would replace an honest refusal
with a confident wrong answer, so the fixtures below are built from Mark's real
measured dispersion rather than from round numbers.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import DailyMetric, PlanBlock, Sleep
from src.models.profile import Profile, UserRole
from src.services.experiment_evaluation import (
    KIND_GROUP_COMPARE,
    KIND_NONE,
    RECOMMEND_INCONCLUSIVE,
    RECOMMEND_REFUTED,
    RECOMMEND_SUPPORTED,
    STATUS_OK,
    ExperimentEvaluationService,
    LabeledNight,
    binds_to_an_evaluator,
    evaluate_group_compare,
    failed_binding_attempt,
)
from src.services.experiment_metrics import COMPARABLE_METRICS, comparable_metric
from src.services.experiment_tracker import (
    DEFAULT_EXPERIMENTS,
    ExperimentTrackerService,
)

HRV = COMPARABLE_METRICS["hrv_last_night_avg_ms"]
RESTING_HR = COMPARABLE_METRICS["resting_heart_rate_bpm"]
SLEEP_SCORE = COMPARABLE_METRICS["age_adjusted_sleep_score"]

#: Mark's measured September HRV, 37–54 ms on a 47 median (SD 5.16 over 120 days).
#: Seven nights an arm is `GROUP_MIN_PER_GROUP`.
HRV_BUILD = [47.0, 44.0, 51.0, 45.0, 49.0, 42.0, 53.0]
#: The same spread, shifted down by exactly 3 ms — the gap 275.2 names.
HRV_RECOVERY = [44.0, 41.0, 48.0, 42.0, 46.0, 39.0, 50.0]


def _nights(recovery: list[float], build: list[float]) -> list[LabeledNight]:
    day = date(2026, 9, 1)
    return [
        LabeledNight(day=day + timedelta(days=i), value=v, group=group)
        for group, values in (("recovery", recovery), ("build", build))
        for i, v in enumerate(values)
    ]


# -- 275.2: a threshold in the metric's own units ----------------------------


def test_a_three_millisecond_hrv_gap_is_inside_his_noise_and_stays_inconclusive() -> None:
    """The regression 275.2 exists to prevent. Three milliseconds is 0.6 of Mark's
    night-to-night standard deviation; at seven nights an arm the interval around
    it spans zero, so the honest answer is that this window cannot call it."""
    result = evaluate_group_compare(_nights(HRV_RECOVERY, HRV_BUILD), metric=HRV)
    assert result.status == STATUS_OK
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    assert result.evidence["delta"] == -3.0
    low, high = result.evidence["deltaInterval"]
    assert low < 0 < high, "the interval must span zero for this to be inconclusive"


def test_a_real_hrv_drop_that_separates_from_zero_is_supported() -> None:
    """The rule is not simply "HRV can never be called". A consistent drop with
    tight dispersion does separate, and is reported with its effect size."""
    build = [47.0] * 7
    recovery = [41.0, 42.0, 41.0, 42.0, 41.0, 42.0, 41.0]
    result = evaluate_group_compare(_nights(recovery, build), metric=HRV)
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["standardisedEffect"] is not None
    assert "ms" in result.reasons[0]


def test_each_metric_carries_its_own_threshold_in_its_own_units() -> None:
    """The flat 3.0 was commented "age-adjusted sleep points". Applied to resting
    heart rate it is two whole standard deviations of a 1.47 bpm spread."""
    assert SLEEP_SCORE.units == "points"
    assert HRV.units == "ms"
    assert RESTING_HR.units == "bpm"
    for metric in COMPARABLE_METRICS.values():
        ratio = metric.threshold / metric.measured_sd
        assert 0.25 <= ratio <= 0.35, (
            f"{metric.key} threshold {metric.threshold} is {ratio:.2f} SD, "
            "not the 0.3 SD effect size the table is built on"
        )


# -- 275.2: direction is read, not assumed -----------------------------------


def test_a_lower_is_better_metric_is_supported_when_recovery_is_higher() -> None:
    """Resting heart rate points the other way. A recovery arm *above* the build
    arm is worse, and the old hardcoded "recovery lower ⇒ supported" would have
    called this refuted — exactly the wrong verdict."""
    assert RESTING_HR.higher_is_better is False
    build = [44.0] * 7
    recovery = [46.0, 47.0, 46.0, 47.0, 46.0, 47.0, 46.0]
    result = evaluate_group_compare(_nights(recovery, build), metric=RESTING_HR)
    assert result.recommendation == RECOMMEND_SUPPORTED
    assert result.evidence["delta"] > 0
    assert result.evidence["worseByDelta"] > 0


def test_a_lower_is_better_metric_is_refuted_when_recovery_is_lower() -> None:
    build = [46.5] * 7
    recovery = [44.0, 45.0, 44.0, 45.0, 44.0, 45.0, 44.0]
    result = evaluate_group_compare(_nights(recovery, build), metric=RESTING_HR)
    assert result.recommendation == RECOMMEND_REFUTED


def test_a_higher_is_better_metric_keeps_the_direction_it_always_had() -> None:
    build = [80.0] * 7
    recovery = [70.0, 72.0, 70.0, 72.0, 70.0, 72.0, 70.0]
    result = evaluate_group_compare(_nights(recovery, build), metric=SLEEP_SCORE)
    assert result.recommendation == RECOMMEND_SUPPORTED


# -- 275.2: the interval gate from Batch 249 still binds ---------------------


def test_the_welch_interval_still_gates_every_directional_verdict() -> None:
    """A large mean gap with dispersion to match is still not a direction."""
    build = [47.0, 33.0, 60.0, 40.0, 55.0, 36.0, 58.0]
    recovery = [38.0, 55.0, 34.0, 52.0, 36.0, 57.0, 35.0]
    result = evaluate_group_compare(_nights(recovery, build), metric=HRV)
    assert result.recommendation == RECOMMEND_INCONCLUSIVE


# -- 275.4 boundary: the existing experiment is untouched --------------------


def test_the_sleep_score_experiment_answers_exactly_as_it_did() -> None:
    """3.0 points is unchanged, and it is still the default when no metric is named."""
    assert SLEEP_SCORE.threshold == 3.0
    nights = _nights([74.0] * 7, [80.0] * 7)
    with_metric = evaluate_group_compare(nights, metric=SLEEP_SCORE)
    default = evaluate_group_compare(nights)
    assert default.recommendation == with_metric.recommendation == RECOMMEND_SUPPORTED
    assert default.evidence["delta"] == with_metric.evidence["delta"] == -6.0
    assert default.evidence["metric"] == "age_adjusted_sleep_score"


def test_the_four_default_experiments_are_unchanged_and_all_bindable() -> None:
    slugs = [d.slug for d in DEFAULT_EXPERIMENTS]
    assert slugs == [
        "collagen",
        "recovery_week_disruption",
        "early_waking_0400",
        "rem_intervention_rotation",
    ]
    recovery = next(d for d in DEFAULT_EXPERIMENTS if d.slug == "recovery_week_disruption")
    assert recovery.success_criteria["metric"] == "age_adjusted_sleep_score"
    assert recovery.success_criteria["compare"] == "recovery_week_vs_build_week"
    for default in DEFAULT_EXPERIMENTS:
        assert binds_to_an_evaluator({"slug": default.slug, **default.success_criteria})


# -- 275.3: a hypothesis that binds to nothing -------------------------------


@pytest.mark.parametrize(
    "criteria",
    [
        # Names a comparison the app cannot run.
        {"compare": "phase_of_the_moon"},
        # Names the comparison it can run, but no metric it can read.
        {"compare": "recovery_week_vs_build_week"},
        {"compare": "recovery_week_vs_build_week", "metric": "vibes"},
        # Names a metric but nothing to compare it across.
        {"metric": "hrv_last_night_avg_ms"},
    ],
)
def test_a_binding_that_was_attempted_and_failed_is_refused(
    criteria: dict[str, object],
) -> None:
    assert failed_binding_attempt(criteria) is not None
    assert binds_to_an_evaluator(criteria) is False


@pytest.mark.parametrize(
    "criteria",
    [
        None,
        {},
        {"note": "I think caffeine after 3pm wrecks my sleep"},
    ],
)
def test_an_experiment_that_attempts_no_binding_is_still_allowed(
    criteria: dict[str, object] | None,
) -> None:
    """275.3 proposed refusing every hypothesis that binds to no evaluator. That
    would delete the manually-tracked path the tracker has on purpose — an
    experiment with no criteria is evaluated as ``no_evaluator`` with "conclude it
    manually from your own observations", which ``test_no_evaluator_for_plain_experiment``
    has pinned since Batch 22. The refusal is narrowed to an *attempted* binding."""
    assert failed_binding_attempt(criteria) is None
    assert binds_to_an_evaluator(criteria) is False


@pytest.mark.parametrize(
    "criteria",
    [
        {"slug": "collagen"},
        {"candidateDrivers": ["overnight_temp"]},
        {"compare": "recovery_week_vs_build_week", "metric": "hrv_last_night_avg_ms"},
        {"compare": "recovery_week_vs_build_week", "metric": "resting_heart_rate_bpm"},
    ],
)
def test_a_bindable_hypothesis_is_accepted(criteria: dict[str, object]) -> None:
    assert binds_to_an_evaluator(criteria) is True
    assert failed_binding_attempt(criteria) is None


@pytest.mark.asyncio
async def test_creating_an_unanswerable_experiment_is_refused_not_stored(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Batch 275 create",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        service = ExperimentTrackerService(session)
        with pytest.raises(HTTPException) as excinfo:
            await service.create_experiment(
                player,
                title="Caffeine",
                hypothesis="Caffeine after 3pm wrecks my sleep",
                success_criteria={
                    "compare": "recovery_week_vs_build_week",
                    "metric": "vibes",
                },
                commit=False,
            )
        assert excinfo.value.status_code == 422
        assert "not a metric" in str(excinfo.value.detail)

        # An experiment that attempts no binding is still created and tracked.
        manual = await service.create_experiment(
            player,
            title="Magnesium",
            hypothesis="Improves deep sleep",
            commit=False,
        )
        assert manual.id is not None

        created = await service.create_experiment(
            player,
            title="Recovery-week HRV",
            hypothesis="My HRV drops in recovery weeks",
            success_criteria={
                "compare": "recovery_week_vs_build_week",
                "metric": "hrv_last_night_avg_ms",
            },
            commit=False,
        )
        assert created.id is not None


# -- 275.1 / 275.3: the question Mark actually asked, end to end -------------


@pytest.mark.asyncio
async def test_marks_recovery_week_hrv_question_is_answerable_at_all(
    db_conn: AsyncConnection,
) -> None:
    """Against today's code this returns ``KIND_NONE`` — a user-created group
    comparison fell to ``_no_evaluator`` and could never be answered, however well
    specified — and the HRV it names was unreachable from the sleep-only reader."""
    end = date(2026, 9, 22)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Batch 275 HRV",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                PlanBlock(
                    user_id=player.id,
                    name="Build",
                    version=1,
                    sequence_index=1,
                    block_type="build",
                    start_date=end - timedelta(days=30),
                    end_date=end - timedelta(days=16),
                ),
                PlanBlock(
                    user_id=player.id,
                    name="Recovery",
                    version=1,
                    sequence_index=2,
                    block_type="recovery",
                    start_date=end - timedelta(days=15),
                    end_date=end,
                ),
            ]
        )
        for offset, value in enumerate(HRV_BUILD):
            session.add(
                DailyMetric(
                    user_id=player.id,
                    calendar_date=end - timedelta(days=30 - offset),
                    phase="morning",
                    hrv_last_night_avg_ms=int(value),
                    raw_payload={},
                )
            )
        for offset, value in enumerate(HRV_RECOVERY):
            session.add(
                DailyMetric(
                    user_id=player.id,
                    calendar_date=end - timedelta(days=14 - offset),
                    phase="morning",
                    hrv_last_night_avg_ms=int(value),
                    raw_payload={},
                )
            )
        await session.flush()

        tracker = ExperimentTrackerService(session)
        experiment = await tracker.create_experiment(
            player,
            title="Recovery-week HRV",
            hypothesis="My HRV drops in recovery weeks",
            success_criteria={
                "compare": "recovery_week_vs_build_week",
                "metric": "hrv_last_night_avg_ms",
            },
            commit=False,
        )
        result = await ExperimentEvaluationService(session).evaluate(player, experiment, as_of=end)

    assert result.kind == KIND_GROUP_COMPARE
    assert result.kind != KIND_NONE
    assert result.status == STATUS_OK
    assert result.evidence["metric"] == "hrv_last_night_avg_ms"
    assert result.evidence["units"] == "ms"
    # The 3 ms gap he described, correctly reported as unresolved by this window.
    assert result.recommendation == RECOMMEND_INCONCLUSIVE


@pytest.mark.asyncio
async def test_the_daily_metrics_reader_takes_the_wake_observation(
    db_conn: AsyncConnection,
) -> None:
    """``daily_metrics`` holds up to two rows per date and they diverge after a
    training day. A recovery-week comparison is about the reads Mark was given at
    wake, so the settled row must not be the one that lands in the arm."""
    end = date(2026, 9, 22)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Batch 275 phase",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                PlanBlock(
                    user_id=player.id,
                    name="Build",
                    version=1,
                    sequence_index=1,
                    block_type="build",
                    start_date=end - timedelta(days=30),
                    end_date=end - timedelta(days=16),
                ),
                PlanBlock(
                    user_id=player.id,
                    name="Recovery",
                    version=1,
                    sequence_index=2,
                    block_type="recovery",
                    start_date=end - timedelta(days=15),
                    end_date=end,
                ),
            ]
        )
        for offset in range(7):
            day = end - timedelta(days=30 - offset)
            session.add_all(
                [
                    DailyMetric(
                        user_id=player.id,
                        calendar_date=day,
                        phase="morning",
                        hrv_last_night_avg_ms=47,
                        raw_payload={},
                    ),
                    DailyMetric(
                        user_id=player.id,
                        calendar_date=day,
                        phase="settled",
                        hrv_last_night_avg_ms=99,
                        raw_payload={},
                    ),
                ]
            )
        for offset in range(7):
            session.add(
                DailyMetric(
                    user_id=player.id,
                    calendar_date=end - timedelta(days=14 - offset),
                    phase="morning",
                    hrv_last_night_avg_ms=41,
                    raw_payload={},
                )
            )
        await session.flush()

        service = ExperimentEvaluationService(session)
        result = await service._evaluate_recovery_week(player, end=end, metric=HRV)

    assert result.evidence["buildMean"] == 47.0, "the settled 99 ms row must not be read"
    assert result.evidence["recoveryMean"] == 41.0


@pytest.mark.asyncio
async def test_the_sleep_backed_experiment_still_reads_the_sleep_table(
    db_conn: AsyncConnection,
) -> None:
    end = date(2026, 9, 22)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Batch 275 sleep",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                PlanBlock(
                    user_id=player.id,
                    name="Build",
                    version=1,
                    sequence_index=1,
                    block_type="build",
                    start_date=end - timedelta(days=30),
                    end_date=end - timedelta(days=16),
                ),
                PlanBlock(
                    user_id=player.id,
                    name="Recovery",
                    version=1,
                    sequence_index=2,
                    block_type="recovery",
                    start_date=end - timedelta(days=15),
                    end_date=end,
                ),
            ]
        )
        for offset in range(7):
            session.add(
                Sleep(
                    user_id=player.id,
                    calendar_date=end - timedelta(days=30 - offset),
                    age_adjusted_score=80,
                    raw_payload={},
                )
            )
        for offset in range(7):
            session.add(
                Sleep(
                    user_id=player.id,
                    calendar_date=end - timedelta(days=14 - offset),
                    age_adjusted_score=72,
                    raw_payload={},
                )
            )
        await session.flush()

        service = ExperimentEvaluationService(session)
        result = await service._evaluate_recovery_week(player, end=end)

    assert result.evidence["metric"] == "age_adjusted_sleep_score"
    assert result.evidence["buildMean"] == 80.0
    assert result.evidence["recoveryMean"] == 72.0
    assert result.recommendation == RECOMMEND_SUPPORTED


def test_an_unknown_metric_key_binds_to_nothing() -> None:
    assert comparable_metric("vibes") is None
    assert comparable_metric(None) is None
