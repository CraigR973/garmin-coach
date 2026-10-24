import base64
import json
import sys
import types
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import TemperatureReading, WeatherDaily
from src.models.profile import Profile, UserRole
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.environment_sync import (
    EnvironmentSyncService,
    HiveClient,
    HiveCredentials,
    HiveCredentialsError,
    HivePayloads,
    _hive_captured_at,
    parse_hive_temperature_fields,
    parse_open_meteo_daily_fields,
)
from src.services.hive_cognito import (
    HIVE_COGNITO_CLIENT_ID,
    HiveCognitoApp,
    HiveTokenRejectedError,
    encode_hive_token_blob,
)
from src.services.retry import retry_sync

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
            "wind_direction_10m": [350, 10, 20, 0, 90, 220, 230, 240],
            "relative_humidity_2m": [80, 82, 85, 81, 65, 75, 78, 81],
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


def test_parse_hive_temperature_fields_prefers_poll_time_when_last_seen_is_stale() -> None:
    poll_started_utc = datetime(2026, 6, 21, 20, 5)

    rows = parse_hive_temperature_fields(hive_payloads(), captured_at_utc=poll_started_utc)

    assert len(rows) == 1
    assert rows[0]["captured_at_utc"] == poll_started_utc


def test_hive_captured_at_clamps_a_future_device_clock() -> None:
    # A boiler module once reported a lastSeen decades in the future, which was
    # stored verbatim and then read as perpetually "fresh". A future device clock
    # must clamp back to observation time — even when stale-preference is off.
    poll = datetime(2026, 7, 5, 1, 0)
    future_ms = int((poll + timedelta(days=1)).replace(tzinfo=UTC).timestamp() * 1000)

    assert (
        _hive_captured_at(future_ms, fallback_time=poll, prefer_fallback_when_stale=False) == poll
    )
    assert _hive_captured_at(future_ms, fallback_time=poll, prefer_fallback_when_stale=True) == poll

    # A recent device clock is still trusted (within the freshness window).
    recent = poll - timedelta(minutes=10)
    recent_ms = int(recent.replace(tzinfo=UTC).timestamp() * 1000)
    assert (
        _hive_captured_at(recent_ms, fallback_time=poll, prefer_fallback_when_stale=True) == recent
    )


def test_is_hive_temperature_fresh_rejects_future_and_stale_readings() -> None:
    now = datetime(2026, 7, 5, 1, 0)

    assert is_hive_temperature_fresh(now - timedelta(minutes=10), now_utc=now) is True
    # Stale past reading — outside the window.
    assert is_hive_temperature_fresh(now - timedelta(minutes=90), now_utc=now) is False
    # Garbage far-future reading — a negative delta must not read as fresh.
    assert is_hive_temperature_fresh(datetime(2068, 2, 13, 19, 44), now_utc=now) is False


class _NoPasswordLogin:
    """pyhiveapi's ``Auth``: constructing it is how a password login starts."""

    created = 0

    def __init__(self, *args: object, **kwargs: object) -> None:
        _NoPasswordLogin.created += 1
        raise AssertionError("the poller must never build pyhiveapi's Auth")


class _FakeHiveDataApi:
    def __init__(self, token: str) -> None:
        self.token = token

    def getAll(self) -> object:
        return load_hive_fixture("getAll.json")

    def getProducts(self) -> object:
        return load_hive_fixture("getProducts.json")

    def getDevices(self) -> object:
        return load_hive_fixture("getDevices.json")


def _fake_pyhiveapi(monkeypatch: pytest.MonkeyPatch) -> None:
    _NoPasswordLogin.created = 0
    module = types.SimpleNamespace(Auth=_NoPasswordLogin, API=_FakeHiveDataApi)
    monkeypatch.setitem(sys.modules, "pyhiveapi", module)


def _cognito(
    seen: list[httpx.Request], *, status: int = 200, payload: dict[str, object] | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = payload if payload is not None else {"AuthenticationResult": {"IdToken": "id-tok"}}
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _pre_348_blob(refresh_token: str) -> str:
    """The shape every blob had before Batch 348: no record of the issuing client."""
    return base64.b64encode(
        json.dumps({"username": "mark@example.com", "refresh_token": refresh_token}).encode()
    ).decode()


def test_hive_resumes_a_pre_348_blob_through_the_known_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_pyhiveapi(monkeypatch)
    seen: list[httpx.Request] = []
    client = HiveClient(
        HiveCredentials(tokenstore_b64=_pre_348_blob("r3fr3sh-t0ken")),
        cognito_transport=_cognito(seen),
    )

    payloads = client.fetch_payloads()

    assert isinstance(client._api, _FakeHiveDataApi)
    assert client._api.token == "id-tok"
    (request,) = seen
    assert json.loads(request.content) == {
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "ClientId": HIVE_COGNITO_CLIENT_ID,
        "AuthParameters": {"REFRESH_TOKEN": "r3fr3sh-t0ken"},
    }
    assert parse_hive_temperature_fields(payloads)[0]["temperature_c"] == pytest.approx(18.66)
    assert _NoPasswordLogin.created == 0


def test_hive_refreshes_through_the_client_recorded_in_the_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_pyhiveapi(monkeypatch)
    seen: list[httpx.Request] = []
    app = HiveCognitoApp("eu-west-2_NewPool", "newclient")
    blob = encode_hive_token_blob(username="mark@example.com", refresh_token="r", app=app)

    HiveClient(HiveCredentials(tokenstore_b64=blob), cognito_transport=_cognito(seen)).login()

    (request,) = seen
    assert str(request.url) == "https://cognito-idp.eu-west-2.amazonaws.com/"
    assert json.loads(request.content)["ClientId"] == "newclient"


async def test_a_dead_token_never_becomes_a_password_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DS328-03, closed in code: three refreshes per poll under the real retry, no logins.

    Before Batch 348, with ``HIVE_EMAIL``/``HIVE_PASSWORD`` set (as they are in
    production), each failed refresh fell through to a password login, and Cognito
    texts the account phone as soon as that password verifies.
    """
    _fake_pyhiveapi(monkeypatch)
    seen: list[httpx.Request] = []
    rejected = _cognito(
        seen,
        status=400,
        payload={"__type": "NotAuthorizedException", "message": "Invalid Refresh Token"},
    )
    client = HiveClient(
        HiveCredentials(tokenstore_b64=_pre_348_blob("r3fr3sh-t0ken")), cognito_transport=rejected
    )

    with pytest.raises(HiveTokenRejectedError) as exc_info:
        await retry_sync(client.fetch_payloads, delay_sec=0)

    assert len(seen) == 3
    assert _NoPasswordLogin.created == 0
    assert "r3fr3sh-t0ken" not in str(exc_info.value)


def test_hive_without_a_token_blob_calls_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_pyhiveapi(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no token blob means no network call at all")

    client = HiveClient(HiveCredentials(), cognito_transport=httpx.MockTransport(handler))

    with pytest.raises(HiveCredentialsError) as exc_info:
        client.login()

    assert "HIVE_TOKENSTORE_B64" in str(exc_info.value)
    assert _NoPasswordLogin.created == 0


def test_hive_credentials_ignore_the_old_password_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production still holds HIVE_EMAIL/HIVE_PASSWORD until Craig deletes them."""
    from src.config import Settings

    monkeypatch.setenv("HIVE_EMAIL", "mark@example.com")
    monkeypatch.setenv("HIVE_PASSWORD", "super-secret")
    monkeypatch.setenv("HIVE_TOKENSTORE_B64", "blob")

    loaded = Settings()

    assert not hasattr(loaded, "hive_email")
    assert not hasattr(loaded, "hive_password")
    assert loaded.hive_tokenstore_b64 == "blob"


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
    assert first["overnight_wind_direction_deg"] == pytest.approx(5.0, abs=0.1)
    assert first["overnight_relative_humidity_mean_pct"] == pytest.approx(82.0)
    assert first["wind_max_mph"] == pytest.approx(14.2)
    assert first["wind_gust_mph"] == pytest.approx(24.1)
    assert first["sunrise_utc"] == datetime(2026, 6, 18, 3, 31)
    assert first["sunset_utc"] == datetime(2026, 6, 18, 21, 8)

    second = rows[1]
    assert second["overnight_low_c"] == pytest.approx(9.6)
    assert second["overnight_wind_max_mph"] == pytest.approx(12.5)
    assert second["overnight_wind_direction_deg"] == pytest.approx(230.0)
    assert second["overnight_relative_humidity_mean_pct"] == pytest.approx(78.0)
    assert second["raw_payload"]["overnight"]["sample_count"] == 3


def test_overnight_wind_direction_normalizes_rounded_north_to_zero() -> None:
    rows = parse_open_meteo_daily_fields(
        {
            "daily": {"time": ["2026-06-18"]},
            "hourly": {
                "time": ["2026-06-17T22:00", "2026-06-18T01:00"],
                "wind_direction_10m": [350, 10],
            },
        },
        timezone="Europe/London",
    )

    assert rows[0]["overnight_wind_direction_deg"] == 0.0


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
                role=UserRole.admin,
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
            (await session.execute(select(WeatherDaily).where(WeatherDaily.user_id == user_id)))
            .scalars()
            .all()
        )

    assert len(temps) == 1
    assert temps[0].temperature_c == pytest.approx(18.66)
    assert len(weather) == 2
    assert weather[0].overnight_wind_gust_mph is not None
    assert weather[0].overnight_wind_direction_deg is not None
    assert weather[0].overnight_relative_humidity_mean_pct is not None
