"""Batch 387 — a 30-day window on the job log that always keeps each job's newest run.

The readers look back 48 hours at most (the Zwift rail) or take each job's newest
run (the freshness watchdog), so these tests pin the window's boundary, the
newest-run exception the watchdog depends on, the batching, and that a second
pass is a no-op.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.operations import JobRun
from src.services import job_runs_retention
from src.services.job_runs_retention import (
    RETENTION_DAYS,
    purge_old_job_runs,
    retention_cutoff,
)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
NAIVE_NOW = NOW.replace(tzinfo=None)


def test_the_window_is_thirty_days() -> None:
    assert RETENTION_DAYS == 30
    assert retention_cutoff(NOW) == NAIVE_NOW - timedelta(days=30)


def _run(job_name: str, started: datetime) -> JobRun:
    return JobRun(
        id=uuid.uuid4(),
        job_name=job_name,
        scheduled_window_start_utc=started,
        scheduled_window_end_utc=started + timedelta(minutes=15),
        started_at_utc=started,
        finished_at_utc=started + timedelta(seconds=2),
        status="succeeded",
        counters={},
    )


async def _seed(db_conn: AsyncConnection, runs: list[JobRun]) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(runs)
        await session.commit()


async def _started_by_job(session: AsyncSession) -> dict[str, list[datetime]]:
    rows = (
        await session.execute(
            select(JobRun.job_name, JobRun.started_at_utc).order_by(
                JobRun.job_name, JobRun.started_at_utc
            )
        )
    ).all()
    found: dict[str, list[datetime]] = {}
    for name, started in rows:
        found.setdefault(name, []).append(started)
    return found


def _savepoint_session(db_conn: AsyncConnection) -> AsyncSession:
    # The purge commits each batch; a savepoint keeps the seeded rows and the
    # fixture's search_path alive across those commits.
    return AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.mark.asyncio
async def test_old_runs_go_and_runs_inside_the_window_stay(db_conn: AsyncConnection) -> None:
    window = timedelta(days=RETENTION_DAYS)
    just_outside = NAIVE_NOW - window - timedelta(minutes=1)
    just_inside = NAIVE_NOW - window + timedelta(minutes=1)
    await _seed(
        db_conn,
        [
            _run("hive-poll", NAIVE_NOW - timedelta(days=31)),
            # The boundary itself, a minute either side of it.
            _run("hive-poll", just_outside),
            _run("hive-poll", just_inside),
            _run("hive-poll", NAIVE_NOW - timedelta(days=1)),
        ],
    )

    async with _savepoint_session(db_conn) as session:
        result = await purge_old_job_runs(session, now_utc=NOW)
        remaining = await _started_by_job(session)

    assert result.deleted_rows == 2
    assert result.cutoff_utc == NAIVE_NOW - window
    assert remaining == {"hive-poll": [just_inside, NAIVE_NOW - timedelta(days=1)]}


@pytest.mark.asyncio
async def test_a_job_keeps_its_newest_run_however_old(db_conn: AsyncConnection) -> None:
    """The freshness watchdog reads each job's newest run: a job that stopped must
    still read "last ran N days ago", never "never ran"."""
    newest_weekly = NAIVE_NOW - timedelta(days=38)
    lone_drill = NAIVE_NOW - timedelta(days=60)
    await _seed(
        db_conn,
        [
            _run("weekly-review", NAIVE_NOW - timedelta(days=45)),
            _run("weekly-review", newest_weekly),
            _run("backup-drill", lone_drill),
            _run("hive-poll", NAIVE_NOW - timedelta(hours=1)),
        ],
    )

    async with _savepoint_session(db_conn) as session:
        result = await purge_old_job_runs(session, now_utc=NOW)
        remaining = await _started_by_job(session)

    assert result.deleted_rows == 1
    assert remaining == {
        "backup-drill": [lone_drill],
        "hive-poll": [NAIVE_NOW - timedelta(hours=1)],
        "weekly-review": [newest_weekly],
    }


@pytest.mark.asyncio
async def test_a_second_pass_removes_nothing(db_conn: AsyncConnection) -> None:
    await _seed(
        db_conn,
        [
            _run("wake-check", NAIVE_NOW - timedelta(days=40)),
            _run("wake-check", NAIVE_NOW - timedelta(days=35)),
            _run("wake-check", NAIVE_NOW - timedelta(days=2)),
        ],
    )

    async with _savepoint_session(db_conn) as session:
        first = await purge_old_job_runs(session, now_utc=NOW)
        second = await purge_old_job_runs(session, now_utc=NOW)

    assert first.deleted_rows == 2
    assert second.deleted_rows == 0


@pytest.mark.asyncio
async def test_the_purge_works_through_bounded_batches(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_runs_retention, "DELETE_BATCH_ROWS", 2)
    await _seed(
        db_conn,
        [_run("fan-control", NAIVE_NOW - timedelta(days=40, minutes=i)) for i in range(5)]
        + [_run("fan-control", NAIVE_NOW - timedelta(minutes=5))],
    )

    async with _savepoint_session(db_conn) as session:
        result = await purge_old_job_runs(session, now_utc=NOW)
        left = await session.scalar(select(func.count()).select_from(JobRun))

    # Five old runs in batches of two (2 + 2 + 1); the recent run is the newest.
    assert result.deleted_rows == 5
    assert left == 1
