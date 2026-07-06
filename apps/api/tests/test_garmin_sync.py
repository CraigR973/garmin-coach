import json
import sys
import types
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
    # age_adjusted_score is no longer baked at sync (was a flat +4). It is a real
    # age-band recompute needing profile age/sex, done at analysis time and
    # written back to the row there (Batch 61 #135), so sync omits it entirely.
    assert "age_adjusted_score" not in fields
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


def test_garmin_login_uses_token_blob_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    class TokenGarmin:
        def login(self, tokenstore: str) -> None:
            calls.append(tokenstore)

    monkeypatch.setitem(
        sys.modules,
        "garminconnect",
        types.SimpleNamespace(Garmin=TokenGarmin),
    )

    credentials = GarminCredentials(
        email="",
        password="",
        tokenstore=tmp_path / "garmin",
        tokenstore_b64="x" * 600,
    )
    client = GarminConnectClient(credentials)

    assert isinstance(client.login(), TokenGarmin)
    assert calls == ["x" * 600]


class _StubGarmin:
    """Underlying garminconnect stub recording which activities got a detail call."""

    def __init__(self, summaries: list[dict[str, object]]) -> None:
        self._summaries = summaries
        self.detail_calls: list[int] = []

    def get_activities_by_date(self, _start: str, _end: str) -> list[dict[str, object]]:
        return self._summaries

    def get_activity_details(self, activity_id: int, **_kw: object) -> dict[str, object]:
        self.detail_calls.append(activity_id)
        return {"activityId": activity_id}


def _client_with_stub(stub: _StubGarmin) -> GarminConnectClient:
    client = GarminConnectClient(
        GarminCredentials(
            email="", password="", tokenstore=Path("/tmp/x"), tokenstore_b64="x" * 600
        )
    )
    client._client = stub  # bypass login()
    return client


_MIXED_SUMMARIES = [
    {"activityId": 1, "activityType": {"typeKey": "indoor_cycling"}},
    {"activityId": 2, "activityType": {"typeKey": "walking"}},
    {"activityId": 3, "activityType": {"typeKey": "breathwork"}},
    {"activityId": 4, "activityType": {"typeKey": "strength_training"}},
]


def test_fetch_activity_payloads_filters_details_by_type() -> None:
    stub = _StubGarmin(_MIXED_SUMMARIES)
    payloads = _client_with_stub(stub).fetch_activity_payloads(
        date(2025, 6, 1), date(2025, 6, 30), detail_types={"indoor_cycling", "walking"}
    )

    # All summaries are kept; only matching types incur a get_activity_details call.
    assert [s["activityId"] for s in payloads.summaries] == [1, 2, 3, 4]
    assert sorted(stub.detail_calls) == [1, 2]
    assert set(payloads.details_by_activity_id) == {1, 2}


def test_fetch_activity_payloads_default_fetches_all_details() -> None:
    stub = _StubGarmin(_MIXED_SUMMARIES)
    payloads = _client_with_stub(stub).fetch_activity_payloads(date(2025, 6, 1), date(2025, 6, 30))

    assert sorted(stub.detail_calls) == [1, 2, 3, 4]  # detail_types=None => all types
    assert set(payloads.details_by_activity_id) == {1, 2, 3, 4}


def test_fetch_activity_payloads_skips_all_details_when_excluded() -> None:
    stub = _StubGarmin(_MIXED_SUMMARIES)
    payloads = _client_with_stub(stub).fetch_activity_payloads(
        date(2025, 6, 1), date(2025, 6, 30), include_details=False, detail_types={"indoor_cycling"}
    )

    assert stub.detail_calls == []  # include_details=False short-circuits the filter
    assert payloads.details_by_activity_id == {}
    assert len(payloads.summaries) == 4  # summaries still returned


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


@pytest.mark.asyncio
async def test_sync_activities_strips_raw_metrics_for_high_volume_types(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    details = {
        "metricDescriptors": [
            {"key": "directPower", "metricsIndex": 0},
            {"key": "directHeartRate", "metricsIndex": 1},
        ],
        "activityDetailMetrics": [{"metrics": [200.0, 150.0]}, {"metrics": [205.0, 151.0]}],
    }
    payloads = GarminActivityPayloads(
        summaries=[
            {"activityId": 111, "activityType": {"typeKey": "indoor_cycling"}},
            {"activityId": 222, "activityType": {"typeKey": "road_biking"}},
        ],
        details_by_activity_id={111: details, 222: details},
    )

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Strip Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        await GarminSyncService(session).sync_activities(user_id, payloads, commit=False)

        by_type: dict[str, list[ActivityTimeSeries]] = {}
        for act in (
            (await session.execute(select(Activity).where(Activity.user_id == user_id)))
            .scalars()
            .all()
        ):
            ts = (
                (
                    await session.execute(
                        select(ActivityTimeSeries).where(ActivityTimeSeries.activity_id == act.id)
                    )
                )
                .scalars()
                .all()
            )
            by_type[act.activity_type] = ts

    # indoor_cycling: typed channels kept, redundant raw_metrics dropped on write
    assert by_type["indoor_cycling"]
    assert all(r.raw_metrics == {} for r in by_type["indoor_cycling"])
    assert all(r.power_watts is not None for r in by_type["indoor_cycling"])
    # road_biking (outdoor): raw_metrics preserved so GPS/elevation survive
    assert by_type["road_biking"]
    assert all(r.raw_metrics != {} for r in by_type["road_biking"])
    assert by_type["road_biking"][0].raw_metrics["directPower"] == 200.0
