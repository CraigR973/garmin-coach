import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import DailyMetric, MetricBaseline, Sleep
from src.models.profile import PlayerRole, Profile
from src.services.sleep_history import (
    SPO2_HRV_RELIABLE_FROM,
    SleepHistoryImportService,
    build_metric_baselines,
    parse_sleep_history_workbook,
)

HEADERS = [
    "Sleep Score 4 Weeks",
    "Score",
    "Resting Heart Rate",
    "Body Battery Charge",
    "Pulse Ox",
    "Respiration",
    "Skin Temp Change",
    "7 Day Average HRV ",
    "Quality",
    "Duration",
    "Sleep Need",
    "Bedtime",
    "Wake Time",
]


def _excel_date_serial(day: date) -> int:
    return (day - date(1899, 12, 30)).days


def _write_workbook(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sleep (1)"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_parse_sleep_history_workbook_ignores_average_row_and_duration_column(
    tmp_path: Path,
) -> None:
    workbook_path = tmp_path / "sleep-history.xlsx"
    _write_workbook(
        workbook_path,
        [
            [
                _excel_date_serial(date(2026, 6, 15)),
                78,
                47,
                56,
                96.18,
                11.28,
                "0°",
                44,
                "Fair",
                "7h 10min",
                "7h 40min",
                2.777777777777778e-03,
                0.3215277777777778,
            ],
            [
                _excel_date_serial(date(2026, 6, 14)),
                80,
                46,
                52,
                96.84,
                11.09,
                "+0.4°",
                43,
                "Good",
                "7h 10min",
                "8h 0min",
                2.0833333333333333e-03,
                0.31458333333333333,
            ],
            ["Average ", 79, 46.5, 54, 96.51, 11.19, "", 43.5, "", "", "", "", ""],
        ],
    )

    rows, skipped = parse_sleep_history_workbook(workbook_path, "Europe/London")

    assert len(rows) == 2
    assert skipped == 1
    assert rows[0].calendar_date == date(2026, 6, 15)
    assert rows[0].age_adjusted_score == 82
    assert rows[0].duration_sec == 27540
    assert rows[0].sleep_start_utc == datetime(2026, 6, 14, 23, 4)
    assert rows[0].sleep_end_utc == datetime(2026, 6, 15, 6, 43)
    assert rows[0].raw_payload["duration"] == "7h 10min"
    assert rows[0].sleep_need_sec == 27600


def test_build_metric_baselines_excludes_unreliable_spo2_and_hrv() -> None:
    workbook_path = _build_baseline_workbook(
        [
            [
                date(2026, 6, 10),
                70,
                44,
                55,
                94.0,
                11.0,
                "0°",
                42,
                "Fair",
                "7h 10min",
                "8h 0min",
                0.99,
                0.30,
            ],
            [
                date(2026, 6, 11),
                80,
                43,
                56,
                96.0,
                10.5,
                "0°",
                45,
                "Good",
                "7h 10min",
                "8h 0min",
                0.99,
                0.30,
            ],
            [
                date(2026, 6, 12),
                78,
                42,
                57,
                97.0,
                10.0,
                "0°",
                46,
                "Good",
                "7h 10min",
                "8h 0min",
                0.99,
                0.30,
            ],
        ]
    )
    rows, _ = parse_sleep_history_workbook(workbook_path, "Europe/London")

    baselines = {baseline["metric_key"]: baseline for baseline in build_metric_baselines(rows)}

    assert baselines["average_spo2_pct"]["reliability_start_date"] == SPO2_HRV_RELIABLE_FROM
    assert baselines["average_spo2_pct"]["sample_count"] == 2
    assert baselines["average_spo2_pct"]["excluded_sample_count"] == 1
    assert baselines["average_spo2_pct"]["mean_value"] == pytest.approx(96.5)
    assert baselines["hrv_7_day_avg_ms"]["sample_count"] == 2
    assert baselines["sleep_score"]["sample_count"] == 3
    assert baselines["sleep_score"]["excluded_sample_count"] == 0


@pytest.mark.asyncio
async def test_sleep_history_import_dry_run_and_rerun_are_idempotent(
    db_conn: AsyncConnection, tmp_path: Path
) -> None:
    workbook_path = _build_baseline_workbook(
        [
            [
                date(2026, 6, 10),
                70,
                44,
                55,
                94.0,
                11.0,
                "0°",
                42,
                "Fair",
                "7h 10min",
                "8h 0min",
                0.99,
                0.30,
            ],
            [
                date(2026, 6, 11),
                80,
                43,
                56,
                96.0,
                10.5,
                "0°",
                45,
                "Good",
                "7h 10min",
                "8h 0min",
                0.99,
                0.30,
            ],
            [
                date(2026, 6, 12),
                78,
                42,
                57,
                97.0,
                10.0,
                "0°",
                46,
                "Good",
                "7h 10min",
                "8h 0min",
                0.99,
                0.30,
            ],
        ],
        tmp_path=tmp_path,
    )
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = Profile(
        id=uuid.uuid4(),
        display_name="Mark",
        pin_hash="x" * 60,
        role=PlayerRole.admin,
        timezone="Europe/London",
        is_active=True,
    )

    async with session_factory() as session:
        session.add(profile)
        await session.flush()

        service = SleepHistoryImportService(session)
        preview = await service.import_workbook(profile, workbook_path, dry_run=True)
        assert preview.rows_parsed == 3
        assert preview.sleep_created == 3
        assert preview.daily_metrics_created == 3
        assert preview.baselines_created == 7

        assert (await session.execute(select(Sleep))).scalars().all() == []

        first_run = await service.import_workbook(profile, workbook_path, dry_run=False)
        second_run = await service.import_workbook(profile, workbook_path, dry_run=False)

        sleeps = (await session.execute(select(Sleep))).scalars().all()
        metrics = (await session.execute(select(DailyMetric))).scalars().all()
        baselines = (await session.execute(select(MetricBaseline))).scalars().all()

    assert first_run.sleep_created == 3
    assert first_run.daily_metrics_created == 3
    assert first_run.baselines_created == 7
    assert second_run.sleep_created == 0
    assert second_run.sleep_updated == 0
    assert second_run.daily_metrics_created == 0
    assert second_run.daily_metrics_updated == 0
    assert second_run.baselines_created == 0
    assert second_run.baselines_updated == 0
    assert len(sleeps) == 3
    assert len(metrics) == 3
    assert len(baselines) == 7


def _build_baseline_workbook(rows: list[list[object]], tmp_path: Path | None = None) -> Path:
    base_path = tmp_path or Path.cwd()
    workbook_path = base_path / "baseline-history.xlsx"
    normalized_rows = [
        [
            _excel_date_serial(row[0]),
            *row[1:],
        ]
        for row in rows
    ]
    _write_workbook(workbook_path, normalized_rows)
    return workbook_path
