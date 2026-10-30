"""Batch 341 (DS328-05): the egress meter's month so far is one server-side sum.

Each 15-minute run read back every ``egress-budget`` row of the month (quadratic in
the day of the month, about 1 GB of September's egress) and booked only today's
backup, at its compressed size. This drives the real aggregate on Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.operations import JobRun
from src.scheduler import _egress_sums

MONTH_START = datetime(2026, 11, 1)
TODAY = datetime(2026, 11, 12)


def _run(job_name: str, started: datetime, counters: dict[str, int]) -> JobRun:
    return JobRun(
        id=uuid.uuid4(),
        job_name=job_name,
        scheduled_window_start_utc=started,
        scheduled_window_end_utc=started + timedelta(minutes=15),
        started_at_utc=started,
        finished_at_utc=started + timedelta(seconds=5),
        status="succeeded",
        counters=counters,
    )


@pytest.mark.asyncio
async def test_the_month_so_far_is_summed_by_the_server(db_conn: AsyncConnection) -> None:
    yesterday = TODAY - timedelta(hours=10)
    last_month = MONTH_START - timedelta(days=2)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                _run(
                    "egress-budget",
                    yesterday,
                    {"http_response_bytes_delta": 100, "alert_stage_ordinal": 2},
                ),
                # The Batch 247 rename: an old row's key still counts.
                _run(
                    "egress-budget",
                    TODAY + timedelta(hours=1),
                    {
                        "response_bytes_delta": 50,
                        "alert_stage_ordinal": 1,
                        "storage_stage_ordinal": 3,
                    },
                ),
                _run("egress-budget", last_month, {"http_response_bytes_delta": 999}),
                # A backup counts at its wire size; an older one at its archive size.
                _run("backup", yesterday, {"backups": 1, "size_bytes": 100, "wire_bytes": 1_000}),
                _run("backup", TODAY + timedelta(hours=3), {"backups": 1, "size_bytes": 70}),
                _run("backup", TODAY + timedelta(hours=4), {"backups": 0, "audit_rows": 1}),
                _run(
                    "backup", last_month, {"backups": 1, "size_bytes": 5_000, "wire_bytes": 50_000}
                ),
                # Another job's counters never count.
                _run("hive-poll", TODAY + timedelta(hours=2), {"http_response_bytes_delta": 7_777}),
            ]
        )
        await session.flush()

        sums = await _egress_sums(session, month_start=MONTH_START, day_start=TODAY)

    assert sums.http_month == 150
    assert sums.http_today == 50
    assert sums.backup_month == 1_070
    assert sums.backup_today == 70
    assert sums.alert_ordinal_today == 1
    assert sums.storage_ordinal_today == 3
