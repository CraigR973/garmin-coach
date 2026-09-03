"""Batch 205 / CI191-02 — the day's record means one thing.

``daily_metrics`` used to be one mutable row per date. The verdict is computed
at wake, but the next morning's ``D-1..D-3`` re-sync re-fetches each closed day
and Garmin returns its *final* training readiness, so the row that survived was
the end-of-day one and every retrospective consumer read it.

Two properties are under test here:

* the wake observation survives the closed-day re-sync, and
* each consumer gets the phase it declared — recovery readings from the wake
  row, finished local-day aggregates from the settled row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING as MORNING,
)
from src.models.coaching import (
    DAILY_METRIC_PHASE_SETTLED as SETTLED,
)
from src.models.coaching import DailyMetric, MetricBaseline, Sleep
from src.models.profile import Profile, UserRole
from src.services.daily_metric_phase import (
    index_day_aggregates_by_date,
    index_morning_by_date,
    index_post_activity_by_date,
    prefer_morning,
    prefer_settled,
)
from src.services.garmin_sync import GarminDailyPayloads, GarminSyncService
from src.services.metric_baselines import MetricBaselineBackfillService, sample_values

DAY = date(2026, 7, 30)


def _row(day: date, phase: str, readiness: int) -> DailyMetric:
    return DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=day,
        phase=phase,
        readiness_score=readiness,
    )


# --- pure collapse ---------------------------------------------------------


def test_prefer_morning_takes_the_wake_row_when_both_exist() -> None:
    """The 30 July case: MODERATE/64 at wake, POOR/19 once the day settled."""
    rows = [_row(DAY, SETTLED, 19), _row(DAY, MORNING, 64)]

    chosen = prefer_morning(rows)

    assert [row.phase for row in chosen] == [MORNING]
    assert [row.readiness_score for row in chosen] == [64]


def test_prefer_morning_is_order_independent() -> None:
    """A query returning the wake row first must not change the answer."""
    forwards = prefer_morning([_row(DAY, MORNING, 64), _row(DAY, SETTLED, 19)])
    backwards = prefer_morning([_row(DAY, SETTLED, 19), _row(DAY, MORNING, 64)])

    assert [row.readiness_score for row in forwards] == [64]
    assert [row.readiness_score for row in backwards] == [64]


def test_prefer_morning_falls_back_to_settled_when_the_morning_was_missed() -> None:
    """A day with no stored wake read still contributes, rather than dropping out."""
    rows = [_row(DAY, SETTLED, 19)]

    chosen = prefer_morning(rows)

    assert [row.phase for row in chosen] == [SETTLED]


def test_prefer_settled_mirrors_the_preference_and_falls_back() -> None:
    both = prefer_settled([_row(DAY, MORNING, 64), _row(DAY, SETTLED, 19)])
    morning_only = prefer_settled([_row(DAY, MORNING, 64)])

    assert [row.readiness_score for row in both] == [19]
    assert [row.phase for row in morning_only] == [MORNING]


def test_collapse_returns_exactly_one_row_per_date_in_date_order() -> None:
    """The property the old unique constraint used to give for free."""
    days = [DAY + timedelta(days=offset) for offset in range(3)]
    rows = [_row(day, phase, 50) for day in reversed(days) for phase in (SETTLED, MORNING)]

    chosen = prefer_morning(rows)

    assert [row.calendar_date for row in chosen] == days
    assert all(row.phase == MORNING for row in chosen)


def test_day_aggregates_index_is_the_settled_row() -> None:
    """Stress and Body Battery are finished local-day totals, not wake readings."""
    rows = [_row(DAY, MORNING, 64), _row(DAY, SETTLED, 19)]

    assert index_morning_by_date(rows)[DAY].readiness_score == 64
    assert index_day_aggregates_by_date(rows)[DAY].readiness_score == 19


# --- write path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_daily_rejects_an_unknown_phase() -> None:
    """Phase is required and closed: a typo cannot quietly write a third kind of row."""
    with pytest.raises(ValueError, match="unknown daily-metric phase"):
        await GarminSyncService(session=None).sync_daily(  # type: ignore[arg-type]
            uuid.uuid4(),
            DAY,
            GarminDailyPayloads(),
            phase="evening",
        )


@pytest.mark.asyncio
async def test_the_closed_day_resync_does_not_mutate_the_wake_row(
    db_conn: AsyncConnection,
) -> None:
    """CI191-02, at the write that caused it.

    The same date is synced twice, as the scheduler does it: today's wake pass
    and the next morning's ``D-1`` pass, which Garmin answers with the settled
    reading. Before Batch 205 the second write landed on the first row and the
    wake observation was gone.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    wake = GarminDailyPayloads(
        training_readiness=[
            {
                "calendarDate": DAY.isoformat(),
                "timestamp": "2026-07-30T06:14:00.0",
                "score": 64,
                "level": "MODERATE",
                "recoveryTime": 943,
            }
        ]
    )
    settled = GarminDailyPayloads(
        training_readiness=[
            {
                "calendarDate": DAY.isoformat(),
                "timestamp": "2026-07-30T20:41:00.0",
                "score": 19,
                "level": "POOR",
                "recoveryTime": 3233,
            }
        ]
    )

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Phase split",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()

        service = GarminSyncService(session)
        await service.sync_daily(user_id, DAY, wake, phase=MORNING, commit=False)
        await service.sync_daily(user_id, DAY, settled, phase=SETTLED, commit=False)

        rows = (
            (
                await session.execute(
                    select(DailyMetric).where(
                        DailyMetric.user_id == user_id,
                        DailyMetric.calendar_date == DAY,
                    )
                )
            )
            .scalars()
            .all()
        )

    by_phase = {row.phase: row for row in rows}
    assert set(by_phase) == {MORNING, SETTLED}
    assert (by_phase[MORNING].readiness_score, by_phase[MORNING].recovery_time_min) == (64, 943)
    assert (by_phase[SETTLED].readiness_score, by_phase[SETTLED].recovery_time_min) == (19, 3233)
    # What the verdict was computed from is what the wake row still says.
    assert by_phase[MORNING].readiness_level == "MODERATE"


@pytest.mark.asyncio
async def test_a_second_wake_sync_of_the_same_day_still_updates_in_place(
    db_conn: AsyncConnection,
) -> None:
    """Phase splits observations, it does not make the table append-only."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    def readiness(score: int) -> GarminDailyPayloads:
        return GarminDailyPayloads(
            training_readiness=[
                {
                    "calendarDate": DAY.isoformat(),
                    "timestamp": "2026-07-30T06:14:00.0",
                    "score": score,
                }
            ]
        )

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Wake idempotence",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()

        service = GarminSyncService(session)
        await service.sync_daily(user_id, DAY, readiness(64), phase=MORNING, commit=False)
        await service.sync_daily(user_id, DAY, readiness(66), phase=MORNING, commit=False)

        rows = (
            (await session.execute(select(DailyMetric).where(DailyMetric.user_id == user_id)))
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].readiness_score == 66


# --- the consumers ---------------------------------------------------------


def _seed_phase_pair(session: object, user_id: uuid.UUID, day: date) -> None:
    """A wake row and a settled row for one date, as production now writes them.

    Readiness diverges the way it really does after a training day (wake high,
    settled low). Body Battery is a running local-day total, so the wake row's
    window stops at 08:00 — genuinely partial, and reported as such by
    ``daily_metric_coverage`` — while the settled row spans the whole day.
    """
    session.add(  # type: ignore[attr-defined]
        Sleep(user_id=user_id, calendar_date=day, score=80, age_adjusted_score=84)
    )
    session.add(  # type: ignore[attr-defined]
        DailyMetric(
            user_id=user_id,
            calendar_date=day,
            phase=MORNING,
            readiness_score=64,
            recovery_time_min=943,
            resting_heart_rate_bpm=44,
            hrv_weekly_avg_ms=48,
            body_battery_charged=30,
            body_battery_drained=1,
            body_battery_end=92,
            stress_avg=12.0,
            raw_payload={
                "stress": {
                    "avgStressLevel": 12,
                    "startTimestampLocal": f"{day.isoformat()}T00:00:00.0",
                    "endTimestampLocal": f"{day.isoformat()}T08:00:00.0",
                },
                "body_battery": {
                    "charged": 30,
                    "drained": 1,
                    "startTimestampLocal": f"{day.isoformat()}T00:00:00.0",
                    "endTimestampLocal": f"{day.isoformat()}T08:00:00.0",
                },
            },
        )
    )
    session.add(  # type: ignore[attr-defined]
        DailyMetric(
            user_id=user_id,
            calendar_date=day,
            phase=SETTLED,
            readiness_score=19,
            recovery_time_min=3233,
            resting_heart_rate_bpm=51,
            hrv_weekly_avg_ms=41,
            body_battery_charged=62,
            body_battery_drained=70,
            body_battery_end=16,
            stress_avg=28.0,
            raw_payload={
                "stress": {
                    "avgStressLevel": 28,
                    "startTimestampLocal": f"{day.isoformat()}T00:00:00.0",
                    "endTimestampLocal": f"{(day + timedelta(days=1)).isoformat()}T00:00:00.0",
                },
                "body_battery": {
                    "charged": 62,
                    "drained": 70,
                    "startTimestampLocal": f"{day.isoformat()}T00:00:00.0",
                    "endTimestampLocal": f"{(day + timedelta(days=1)).isoformat()}T00:00:00.0",
                },
            },
        )
    )


@pytest.mark.asyncio
async def test_baselines_use_wake_readiness_and_settled_body_battery(
    db_conn: AsyncConnection,
) -> None:
    """CI191-02 consequence 2, and the field-level exception to it.

    The personal baselines the readiness floor keys off are compared against a
    *morning* reading, so they must be built from morning readings — built from
    the settled rows they were an apples-to-oranges comparison biased toward a
    lower floor. Body Battery charge is the exception: it is a finished
    local-day total, and the wake row's partial figure is gated to ``None`` by
    coverage, so taking it from the settled row is what keeps that baseline
    alive at all.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = Profile(
        id=uuid.uuid4(),
        display_name="Phase baselines",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    days = [date(2026, 6, 11) + timedelta(days=offset) for offset in range(6)]

    async with session_factory() as session:
        session.add(profile)
        await session.flush()
        for day in days:
            _seed_phase_pair(session, profile.id, day)
        await session.flush()

        await MetricBaselineBackfillService(session).rebuild(profile, window_days=None)

        baselines = {
            row.metric_key: row
            for row in (
                (
                    await session.execute(
                        select(MetricBaseline).where(MetricBaseline.user_id == profile.id)
                    )
                )
                .scalars()
                .all()
            )
        }

    assert baselines["readiness_score"].median_value == 64
    assert baselines["resting_heart_rate_bpm"].median_value == 44
    assert baselines["hrv_7_day_avg_ms"].median_value == 48
    # The settled total, not the wake row's partial 30 — and not blanked.
    assert baselines["body_battery_charge"].median_value == 62
    assert baselines["body_battery_charge"].sample_count == len(days)


def test_sample_values_blanks_body_battery_from_a_partial_wake_row() -> None:
    """Why ``day_aggregates`` exists: the coverage gate is doing its job.

    Handed only the wake row, the charge figure is correctly refused — which is
    exactly what would have happened to every historical day had the baselines
    simply switched to morning rows wholesale.
    """
    morning = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=DAY,
        phase=MORNING,
        body_battery_charged=30,
        raw_payload={
            "body_battery": {
                "charged": 30,
                "startTimestampLocal": f"{DAY.isoformat()}T00:00:00.0",
                "endTimestampLocal": f"{DAY.isoformat()}T08:00:00.0",
            }
        },
    )
    settled = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=DAY,
        phase=SETTLED,
        body_battery_charged=62,
        raw_payload={
            "body_battery": {
                "charged": 62,
                "startTimestampLocal": f"{DAY.isoformat()}T00:00:00.0",
                "endTimestampLocal": f"{(DAY + timedelta(days=1)).isoformat()}T00:00:00.0",
            }
        },
    )

    assert sample_values(None, morning)["body_battery_charge"] is None
    assert sample_values(None, morning, day_aggregates=settled)["body_battery_charge"] == 62


@pytest.mark.asyncio
async def test_readiness_history_is_built_from_wake_readings(
    db_conn: AsyncConnection,
) -> None:
    """The 84-day readiness history behind the baseline trend, same argument."""
    from src.services.morning_analysis import MorningAnalysisService

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    days = [DAY - timedelta(days=offset) for offset in range(3)]

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Readiness history",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        for day in days:
            _seed_phase_pair(session, user_id, day)
        await session.flush()

        history = await MorningAnalysisService(session)._readiness_history(user_id, DAY)

    assert [score for _, score in history] == [64, 64, 64]
    assert [day for day, _ in history] == sorted(days)


@pytest.mark.asyncio
async def test_acute_physiology_history_is_projected_from_prior_wake_rows(
    db_conn: AsyncConnection,
) -> None:
    """The acute rail excludes today and cannot pull either raw JSON payload."""
    from src.services.morning_analysis import MorningAnalysisService

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    days = [DAY - timedelta(days=offset) for offset in range(3)]

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Acute physiology history",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        for day in days:
            _seed_phase_pair(session, user_id, day)
        await session.flush()

        metrics, sleeps = await MorningAnalysisService(session)._acute_physiology_history(
            user_id, DAY
        )

    expected_dates = sorted([DAY - timedelta(days=2), DAY - timedelta(days=1)])
    assert [row.calendar_date for row in metrics] == expected_dates
    assert [row.resting_heart_rate_bpm for row in metrics] == [44, 44]
    assert [row.calendar_date for row in sleeps] == expected_dates
    assert all("raw_payload" in inspect(row).unloaded for row in [*metrics, *sleeps])


@pytest.mark.asyncio
async def test_yesterdays_load_packet_reads_the_settled_row(
    db_conn: AsyncConnection,
) -> None:
    """The one deliberate settled read in the morning packet.

    "What did yesterday cost" is a whole-day question; yesterday's wake reading
    predates yesterday's session entirely. It is also the read where morning
    would be actively destructive: every figure in ``wholeDayCost`` is
    coverage-gated, so the wake row's partial window would blank all three.
    """
    from src.services.morning_analysis import MorningAnalysisService

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    yesterday = DAY - timedelta(days=1)

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Yesterday load",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        _seed_phase_pair(session, user_id, yesterday)
        await session.flush()

        packet = await MorningAnalysisService(session)._yesterday_load(
            user_id, DAY, "Europe/London"
        )

    cost = packet["wholeDayCost"]
    assert cost["allDayStressAvg"] == 28
    assert cost["bodyBatteryDrained"] == 70
    assert cost["bodyBatteryEnd"] == 16
    assert cost["coverage"]["status"] == "complete"


def test_recorded_at_is_the_readings_own_garmin_timestamp() -> None:
    """Why the overwrite was invisible: the column is Garmin's, not our sync clock."""
    from src.services.garmin_sync import parse_daily_metric_fields

    fields = parse_daily_metric_fields(
        DAY,
        GarminDailyPayloads(
            training_readiness=[
                {
                    "calendarDate": DAY.isoformat(),
                    "timestamp": "2026-07-30T20:41:00.0",
                    "score": 19,
                }
            ]
        ),
    )

    assert fields["recorded_at_utc"] == datetime(2026, 7, 30, 20, 41)


# --- Batch 225: the post-activity field-level exception ---------------------


def _vo2_row(day: date, phase: str, *, readiness: int, vo2max: float | None) -> DailyMetric:
    return DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=day,
        phase=phase,
        readiness_score=readiness,
        vo2max=vo2max,
    )


def test_post_activity_index_takes_vo2max_off_the_settled_row() -> None:
    """The July/August case: 13 settled readings, none across 30 morning rows.

    Garmin recomputes VO2 max after a qualifying activity, so the wake row is
    not holding a *worse* number — it is holding ``None``, and the collapse that
    prefers it reported ``sampleCount: 0`` for the whole summer.
    """
    rows = [
        _vo2_row(DAY, MORNING, readiness=64, vo2max=None),
        _vo2_row(DAY, SETTLED, readiness=19, vo2max=55.2),
    ]

    assert index_post_activity_by_date(rows)[DAY].vo2max == 55.2
    # The same date's recovery reads are untouched — Batch 205 still holds.
    assert index_morning_by_date(rows)[DAY].readiness_score == 64
    assert index_morning_by_date(rows)[DAY].vo2max is None


def test_post_activity_index_keeps_a_morning_only_date_in_the_window() -> None:
    """2026-06-21 — the first two-phase date, and the only morning row that has
    ever carried a ``vo2max``. A settled-only lookup would drop both the reading
    and the date's whole sample."""
    first_two_phase_day = date(2026, 6, 21)
    rows = [_vo2_row(first_two_phase_day, MORNING, readiness=58, vo2max=53.5)]

    indexed = index_post_activity_by_date(rows)

    assert set(indexed) == {first_two_phase_day}
    assert indexed[first_two_phase_day].vo2max == 53.5


def test_post_activity_and_morning_indexes_cover_the_same_dates() -> None:
    """The trends reducer looks both up per date, so a date present in one and
    absent from the other would silently drop out of a window."""
    other = DAY + timedelta(days=1)
    rows = [
        _vo2_row(DAY, MORNING, readiness=64, vo2max=None),
        _vo2_row(DAY, SETTLED, readiness=19, vo2max=55.2),
        _vo2_row(other, SETTLED, readiness=61, vo2max=None),
    ]

    assert set(index_post_activity_by_date(rows)) == set(index_morning_by_date(rows))
