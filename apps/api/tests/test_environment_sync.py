import json
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import TemperatureReading, WeatherDaily
from src.models.profile import PlayerRole, Profile
from src.services.environment_sync import (
    EnvironmentSyncService,
    HiveClient,
    HiveCredentials,
    HiveLoginError,
    HivePayloads,
    parse_hive_temperature_fields,
    parse_open_meteo_daily_fields,
)

HIVE_FIXTURES = Path(__file__).parent / "fixtures" / "hive"


def load_hive_fixture(name: str) -> object:
    return json.loads((HIVE_FIXTURES / name).read_text())


def hive_payloads() -> HivePayloads:
    return HivePayloads(
        get_all=load_hive_fixture("getAll.json"),
        products=load_hive_fixture("getProducts.json"),
        devices=load_hive_fixture("getDevices.json"),
    )


def open_meteo_payload() -> dict[str, object]:
    return {
        "latitude": 55.6045,
        "longitude": -4.5249,
        "timezone": "Europe/London",
        "daily": {
            "time": ["2026-06-18", "2026-06-19"],
            "temperature_2m_max": [17.8, 19.1],
            "temperature_2m_min": [8.9, 9.7],
            "precipitation_sum": [0.2, 1.4],
            "wind_speed_10m_max": [14.2, 18.5],
            "wind_gusts_10m_max": [24.1, 31.3],
            "sunrise": ["2026-06-18T04:31", "2026-06-19T04:31"],
            "sunset": ["2026-06-18T22:08", "2026-06-19T22:08"],
        },
        "hourly": {
            "time": [
                "2026-06-17T20:00",
                "2026-06-17T23:00",
                "2026-06-18T04:00",
                "2026-06-18T08:00",
                "2026-06-18T12:00",
                "2026-06-18T20:00",
                "2026-06-19T02:00",
                "2026-06-19T08:00",
            ],
            "temperature_2m": [11.8, 10.2, 8.4, 9.1, 15.0, 12.9, 9.6, 10.4],
            "wind_speed_10m": [7.1, 8.0, 5.5, 6.2, 10.0, 9.2, 12.5, 11.1],
            "wind_gusts_10m": [14.0, 15.5, 11.4, 12.2, 20.0, 18.0, 24.8, 22.2],
        },
    }


def test_parse_hive_temperature_fields_from_real_spike_fixtures() -> None:
    rows = parse_hive_temperature_fields(hive_payloads())

    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "hive"
    assert row["product_id"] == "f3e3c059-308c-411b-9bcc-d5bb5cc54c8b"
    assert row["device_id"] == "1f56cad1-b481-4242-9b59-1fb4d964fdf6"
    assert row["captured_at_utc"] == datetime(2026, 6, 16, 15, 10, 56, 874000)
    assert row["temperature_c"] == pytest.approx(18.66)
    assert row["target_temperature_c"] == pytest.approx(9)
    assert row["raw_payload"]["product"]["props"]["temperature"] == pytest.approx(18.66)
    assert row["raw_payload"]["device"]["type"] == "boilermodule"


def test_hive_login_error_does_not_expose_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenAuth:
        def __init__(self, email: str, password: str) -> None:
            self.email = email
            self.password = password

        def login(self) -> None:
            raise RuntimeError(f"bad login for {self.email} with {self.password}")

    class FakeApi:
        def __init__(self, token: str) -> None:  # noqa: ARG002
            pass

    import sys
    import types

    module = types.SimpleNamespace(Auth=BrokenAuth, API=FakeApi)
    monkeypatch.setitem(sys.modules, "pyhiveapi", module)
    client = HiveClient(HiveCredentials(email="mark@example.com", password="super-secret"))

    with pytest.raises(HiveLoginError) as exc_info:
        client.login()

    message = str(exc_info.value)
    assert "super-secret" not in message
    assert "mark@example.com" not in message


def test_parse_open_meteo_daily_fields_captures_daily_and_overnight_weather() -> None:
    rows = parse_open_meteo_daily_fields(open_meteo_payload(), timezone="Europe/London")

    assert len(rows) == 2
    first = rows[0]
    assert first["calendar_date"] == date(2026, 6, 18)
    assert first["latitude"] == pytest.approx(55.6045)
    assert first["longitude"] == pytest.approx(-4.5249)
    assert first["temp_high_c"] == pytest.approx(17.8)
    assert first["temp_low_c"] == pytest.approx(8.9)
    assert first["overnight_low_c"] == pytest.approx(8.4)
    assert first["overnight_wind_max_mph"] == pytest.approx(8.0)
    assert first["overnight_wind_gust_mph"] == pytest.approx(15.5)
    assert first["wind_max_mph"] == pytest.approx(14.2)
    assert first["wind_gust_mph"] == pytest.approx(24.1)
    assert first["sunrise_utc"] == datetime(2026, 6, 18, 3, 31)
    assert first["sunset_utc"] == datetime(2026, 6, 18, 21, 8)

    second = rows[1]
    assert second["overnight_low_c"] == pytest.approx(9.6)
    assert second["overnight_wind_max_mph"] == pytest.approx(12.5)
    assert second["raw_payload"]["overnight"]["sample_count"] == 3


@pytest.mark.asyncio
async def test_environment_sync_upserts_without_duplicate_rows(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Environment Sync Test",
                pin_hash="x" * 60,
                role=PlayerRole.admin,
                timezone="Europe/London",
                hive_home_id="aa1fbb37-6b65-4622-b609-5d75534fafd3",
                latitude=55.6045,
                longitude=-4.5249,
                is_active=True,
            )
        )
        await session.flush()

        service = EnvironmentSyncService(session)
        await service.sync_hive_temperatures(user_id, hive_payloads(), commit=False)
        await service.sync_weather_daily(user_id, open_meteo_payload(), commit=False)
        await service.sync_hive_temperatures(user_id, hive_payloads(), commit=False)
        await service.sync_weather_daily(user_id, open_meteo_payload(), commit=False)

        temps = (
            (
                await session.execute(
                    select(TemperatureReading).where(TemperatureReading.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        weather = (
            (
                await session.execute(select(WeatherDaily).where(WeatherDaily.user_id == user_id))
            )
            .scalars()
            .all()
        )

    assert len(temps) == 1
    assert temps[0].temperature_c == pytest.approx(18.66)
    assert len(weather) == 2
    assert weather[0].overnight_wind_gust_mph is not None
