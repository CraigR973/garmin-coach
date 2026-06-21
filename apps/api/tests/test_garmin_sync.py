import json
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity, ActivityTimeSeries, DailyMetric, Sleep
from src.models.profile import Profile, UserRole
from src.services.garmin_sync import (
    GarminActivityPayloads,
    GarminConnectClient,
    GarminCredentials,
    GarminDailyPayloads,
    GarminLoginError,
    GarminSyncService,
    parse_activity_summary_fields,
    parse_activity_timeseries_fields,
    parse_daily_metric_fields,
    parse_metric_descriptor_keys,
    parse_sleep_fields,
)

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"


def load_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def daily_payloads() -> GarminDailyPayloads:
    return GarminDailyPayloads(
        training_readiness=load_fixture("training_readiness.json"),
        sleep=load_fixture("sleep.json"),
        hrv=load_fixture("hrv.json"),
        body_battery=load_fixture("body_battery.json"),
        rhr=load_fixture("rhr.json"),
        weigh_ins=load_fixture("weigh_ins.json"),
        max_metrics_vo2=load_fixture("max_metrics_vo2.json"),
        training_status=load_fixture("training_status.json"),
        stress=load_fixture("stress.json"),
    )


def test_parse_daily_metric_fields_from_representative_garmin_fixtures() -> None:
    fields = parse_daily_metric_fields(date(2026, 6, 18), daily_payloads())

    assert fields["readiness_score"] == 12
    assert fields["readiness_level"] == "POOR"
    assert fields["readiness_sleep_score"] == 79
    assert fields["recovery_time_min"] == 4317
    assert fields["acute_load"] == 1074
    assert fields["training_status"] == "PRODUCTIVE_9"
    assert fields["hrv_last_night_avg_ms"] == 55
    assert fields["hrv_weekly_avg_ms"] == 49
    assert fields["hrv_status"] == "BALANCED"
    assert fields["hrv_baseline_low_ms"] == 43
    assert fields["hrv_baseline_high_ms"] == 56
    assert fields["resting_heart_rate_bpm"] == 45
    assert fields["stress_avg"] == 28
    assert fields["body_battery_charged"] == 66
    assert fields["body_battery_drained"] == 67
    assert fields["body_battery_end"] == 26
    assert fields["weight_kg"] == pytest.approx(75.349)
    assert fields["vo2max"] == pytest.approx(53.6)
    assert fields["raw_payload"]["training_readiness"]["recoveryTime"] == 4317


def test_parse_sleep_fields_from_representative_garmin_fixture() -> None:
    fields = parse_sleep_fields(load_fixture("sleep.json"))

    assert fields["calendar_date"] == date(2026, 6, 18)
    assert fields["sleep_start_utc"] == datetime(2026, 6, 17, 23, 4, 24)
    assert fields["sleep_end_utc"] == datetime(2026, 6, 18, 5, 48, 24)
    assert fields["score"] == 79
    assert fields["age_adjusted_score"] == 83
    assert fields["qualifier"] == "FAIR"
    assert fields["duration_sec"] == 24240
    assert fields["rem_sleep_sec"] == 3780
    assert fields["average_spo2_pct"] == 96
    assert fields["lowest_spo2_pct"] == 86
    assert fields["average_respiration"] == 11
    assert fields["resting_heart_rate_bpm"] == 45
    assert fields["avg_overnight_hrv_ms"] == 55
    assert fields["hrv_status"] == "BALANCED"
    assert fields["restless_moments_count"] == 45


def test_parse_activity_summary_and_timeseries_channels() -> None:
    activity = load_fixture("activities.json")[0]  # type: ignore[index]
    details = load_fixture("activity_details.json")
    expected_channels = load_fixture("activity_metric_channels.json")

    summary = parse_activity_summary_fields(activity)
    rows = parse_activity_timeseries_fields(details)  # type: ignore[arg-type]

    assert summary["garmin_activity_id"] == 23294062909
    assert summary["garmin_activity_uuid"] == "5b98f253-751f-412a-9180-b6c5a6bfa5a0"
    assert summary["activity_type"] == "indoor_cycling"
    assert summary["start_utc"] == datetime(2026, 6, 18, 11, 0, 5)
    assert summary["avg_power_watts"] == 221
    assert summary["normalized_power_watts"] == 234
    assert summary["aerobic_training_effect"] == pytest.approx(4.7)
    assert summary["avg_cadence_rpm"] == pytest.approx(85)
    assert summary["exclude_from_recovery"] is False
    assert parse_metric_descriptor_keys(details) == expected_channels  # type: ignore[arg-type]

    assert len(rows) == 2
    assert rows[0]["sample_index"] == 0
    assert rows[0]["timestamp_utc"] == datetime(2026, 6, 18, 11, 0, 5)
    assert rows[0]["power_watts"] == 56
    assert rows[0]["heart_rate_bpm"] == 68
    assert rows[0]["cadence_rpm"] == 73
    assert rows[1]["respiration"] == 32
    assert rows[1]["performance_condition"] == -1
    assert rows[1]["available_stamina"] == 95
    assert rows[1]["potential_stamina"] == 95


def test_garmin_login_error_does_not_expose_credentials(tmp_path: Path) -> None:
    class BrokenGarmin:
        def __init__(self, email: str, password: str) -> None:
            self.email = email
            self.password = password

        def login(self, tokenstore: str) -> None:  # noqa: ARG002
            raise RuntimeError(f"bad login for {self.email} with {self.password}")

    credentials = GarminCredentials(
        email="mark@example.com",
        password="super-secret-password",
        tokenstore=tmp_path / "garmin",
    )
    client = GarminConnectClient(credentials)

    with pytest.raises(GarminLoginError) as exc_info:
        client._fresh_login(BrokenGarmin, str(credentials.tokenstore))

    message = str(exc_info.value)
    assert "super-secret-password" not in message
    assert "mark@example.com" not in message


@pytest.mark.asyncio
async def test_garmin_sync_upserts_without_duplicate_rows(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    activity_payloads = GarminActivityPayloads(
        summaries=load_fixture("activities.json"),  # type: ignore[arg-type]
        details_by_activity_id={
            23294062909: load_fixture("activity_details.json"),  # type: ignore[dict-item]
        },
    )

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Garmin Sync Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()

        service = GarminSyncService(session)
        await service.sync_daily(user_id, date(2026, 6, 18), daily_payloads(), commit=False)
        await service.sync_activities(user_id, activity_payloads, commit=False)
        await service.sync_daily(user_id, date(2026, 6, 18), daily_payloads(), commit=False)
        await service.sync_activities(user_id, activity_payloads, commit=False)

        metrics = (
            (await session.execute(select(DailyMetric).where(DailyMetric.user_id == user_id)))
            .scalars()
            .all()
        )
        sleeps = (
            (await session.execute(select(Sleep).where(Sleep.user_id == user_id))).scalars().all()
        )
        activities = (
            (await session.execute(select(Activity).where(Activity.user_id == user_id)))
            .scalars()
            .all()
        )
        samples = (
            (
                await session.execute(
                    select(ActivityTimeSeries).where(
                        ActivityTimeSeries.activity_id == activities[0].id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(metrics) == 1
    assert len(sleeps) == 1
    assert len(activities) == 1
    assert len(samples) == 2
