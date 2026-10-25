"""Hive indoor-temperature and Open-Meteo weather sync helpers."""

from __future__ import annotations

import math
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import TemperatureReading, WeatherDaily
from src.services.environment_freshness import HIVE_FRESHNESS_LIMIT
from src.services.hive_cognito import (
    HiveAuthError,
    decode_hive_token_blob,
    refresh_hive_id_token,
    token_blob_app,
    token_blob_device_key,
)
from src.services.serialised_calls import one_at_a_time

JsonDict = dict[str, Any]
JsonList = list[Any]

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
KILMARNOCK_LATITUDE = 55.6045
KILMARNOCK_LONGITUDE = -4.5249
DEFAULT_WEATHER_TIMEZONE = "Europe/London"
#: Batch 312: one Hive call at a time across the process, as Garmin's
#: ``GARMIN_CALLS``. The calls run in worker threads now, where nothing else
#: keeps two of them apart.
HIVE_CALLS = threading.RLock()


class EnvironmentSyncError(RuntimeError):
    """Base error for environmental sync failures."""


class HiveCredentialsError(EnvironmentSyncError):
    """Raised when Hive sync cannot start because no token blob is configured."""


@dataclass(frozen=True)
class HiveCredentials:
    tokenstore_b64: str = ""

    @classmethod
    def from_settings(cls) -> HiveCredentials:
        return cls(tokenstore_b64=settings.hive_tokenstore_b64)

    def validate(self) -> None:
        if not self.tokenstore_b64:
            raise HiveCredentialsError(
                "Hive is not configured; set HIVE_TOKENSTORE_B64 with "
                "scripts/bootstrap_hive_tokenstore.py. The poller never attempts a "
                "password login: the account's SMS MFA needs someone with the phone."
            )


@dataclass(frozen=True)
class HivePayloads:
    get_all: Any = None
    products: Any = None
    devices: Any = None


@dataclass(frozen=True)
class WeatherRequest:
    latitude: float = KILMARNOCK_LATITUDE
    longitude: float = KILMARNOCK_LONGITUDE
    timezone: str = DEFAULT_WEATHER_TIMEZONE
    past_days: int = 2
    forecast_days: int = 7

    @classmethod
    def from_settings(cls) -> WeatherRequest:
        return cls(
            latitude=settings.weather_latitude,
            longitude=settings.weather_longitude,
            timezone=settings.weather_timezone,
        )


@dataclass(frozen=True)
class EnvironmentSyncResult:
    temperature_readings_synced: int = 0
    weather_days_synced: int = 0


@dataclass(frozen=True)
class WeatherNightStats:
    low_c: float | None = None
    wind_max_mph: float | None = None
    wind_gust_mph: float | None = None
    wind_direction_deg: float | None = None
    relative_humidity_mean_pct: float | None = None
    sample_count: int = 0


class HiveClient:
    """Sync pyhiveapi wrapper that resumes from a stored Cognito refresh token.

    Mark's Hive account authenticates through AWS Cognito with ``SMS_MFA``, so an
    unattended password login is impossible: Cognito texts the code as soon as
    the password verifies, before it returns a challenge nobody here can answer.
    The poller therefore only resumes from the persisted refresh token
    (``HIVE_TOKENSTORE_B64``) via ``REFRESH_TOKEN_AUTH``; seed it with
    ``scripts/bootstrap_hive_tokenstore.py``, which logs in once with someone
    holding the account phone.

    Batch 348 removed the password fallback (DS328-03). With a dead token and the
    password variables set, every poll made three password logins — three SMS
    codes every 15 minutes once Hive's page could be read again — and the logs
    showed that fallback's failure instead of the refresh's. The refresh itself
    no longer goes through pyhiveapi's ``Auth``, whose constructor scrapes the
    sign-on page (see ``services/hive_cognito``); pyhiveapi still reads the data.
    """

    def __init__(
        self,
        credentials: HiveCredentials | None = None,
        *,
        cognito_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.credentials = credentials or HiveCredentials.from_settings()
        self._cognito_transport = cognito_transport
        self._api: Any | None = None

    @one_at_a_time(HIVE_CALLS)
    def login(self) -> Any:
        if self._api is not None:
            return self._api

        self.credentials.validate()
        api_cls = self._import_pyhiveapi_api()
        blob = decode_hive_token_blob(self.credentials.tokenstore_b64)
        refresh_token = blob.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise HiveAuthError(
                "Hive token blob has no refresh_token; re-seed HIVE_TOKENSTORE_B64."
            )
        token = refresh_hive_id_token(
            token_blob_app(blob),
            refresh_token,
            device_key=token_blob_device_key(blob),
            transport=self._cognito_transport,
        )
        self._api = api_cls(token=token)
        return self._api

    @staticmethod
    def _import_pyhiveapi_api() -> Any:
        try:
            from pyhiveapi import API  # type: ignore[import-untyped, unused-ignore]
        except ImportError as exc:  # pragma: no cover - exercised only in missing envs
            raise EnvironmentSyncError("pyhiveapi is not installed.") from exc
        return API

    @one_at_a_time(HIVE_CALLS)
    def fetch_payloads(self) -> HivePayloads:
        api = self.login()
        return HivePayloads(
            get_all=api.getAll(),
            products=api.getProducts(),
            devices=api.getDevices(),
        )


class OpenMeteoClient:
    """Async Open-Meteo client for Kilmarnock daily and overnight weather."""

    def __init__(self, url: str = OPEN_METEO_FORECAST_URL) -> None:
        self.url = url

    async def fetch_daily_payload(self, request: WeatherRequest | None = None) -> JsonDict:
        request = request or WeatherRequest.from_settings()
        params: dict[str, str | int | float] = {
            "latitude": request.latitude,
            "longitude": request.longitude,
            "timezone": request.timezone,
            "wind_speed_unit": "mph",
            "past_days": request.past_days,
            "forecast_days": request.forecast_days,
            "daily": ",".join(
                (
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "wind_speed_10m_max",
                    "wind_gusts_10m_max",
                    "sunrise",
                    "sunset",
                )
            ),
            "hourly": ",".join(
                (
                    "temperature_2m",
                    "wind_speed_10m",
                    "wind_gusts_10m",
                    "wind_direction_10m",
                    "relative_humidity_2m",
                )
            ),
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self.url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise EnvironmentSyncError("Open-Meteo response was not a JSON object.")
        return payload


class EnvironmentSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sync_hive_temperatures(
        self,
        user_id: uuid.UUID,
        payloads: HivePayloads,
        *,
        captured_at_utc: datetime | None = None,
        commit: bool = True,
    ) -> EnvironmentSyncResult:
        fields_list = parse_hive_temperature_fields(payloads, captured_at_utc=captured_at_utc)
        synced = 0
        for fields in fields_list:
            result = await self.session.execute(
                select(TemperatureReading).where(
                    TemperatureReading.user_id == user_id,
                    TemperatureReading.source == fields["source"],
                    TemperatureReading.product_id == fields["product_id"],
                    TemperatureReading.captured_at_utc == fields["captured_at_utc"],
                )
            )
            reading = result.scalar_one_or_none()
            if reading is None:
                reading = TemperatureReading(user_id=user_id, **fields)
                self.session.add(reading)
            else:
                _apply_fields(reading, fields)
            synced += 1

        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return EnvironmentSyncResult(temperature_readings_synced=synced)

    async def sync_weather_daily(
        self,
        user_id: uuid.UUID,
        payload: Mapping[str, Any],
        *,
        timezone: str = DEFAULT_WEATHER_TIMEZONE,
        commit: bool = True,
    ) -> EnvironmentSyncResult:
        fields_list = parse_open_meteo_daily_fields(payload, timezone=timezone)
        synced = 0
        for fields in fields_list:
            result = await self.session.execute(
                select(WeatherDaily).where(
                    WeatherDaily.user_id == user_id,
                    WeatherDaily.calendar_date == fields["calendar_date"],
                    WeatherDaily.source == fields["source"],
                )
            )
            weather = result.scalar_one_or_none()
            if weather is None:
                weather = WeatherDaily(user_id=user_id, **fields)
                self.session.add(weather)
            else:
                _apply_fields(weather, fields)
            synced += 1

        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return EnvironmentSyncResult(weather_days_synced=synced)


def parse_hive_temperature_fields(
    payloads: HivePayloads,
    *,
    captured_at_utc: datetime | None = None,
) -> list[JsonDict]:
    products = _hive_products(payloads)
    devices_by_id = {
        str(device["id"]): device for device in _hive_devices(payloads) if device.get("id")
    }
    fallback_time = _naive_utc(captured_at_utc or datetime.now(UTC))
    rows: list[JsonDict] = []

    for product in products:
        props = _as_dict(product.get("props"))
        state = _as_dict(product.get("state"))
        temperature = _to_float(props.get("temperature"))
        if temperature is None:
            continue
        product_id = _to_str(product.get("id"))
        device_id = (
            _to_str(props.get("zone"))
            or _to_str(product.get("parent"))
            or _to_str(product.get("deviceId"))
        )
        device = devices_by_id.get(device_id or "")
        captured_at = _hive_captured_at(
            product.get("lastSeen"),
            fallback_time=fallback_time,
            prefer_fallback_when_stale=captured_at_utc is not None,
        )
        rows.append(
            {
                "source": "hive",
                "product_id": product_id,
                "device_id": device_id,
                "captured_at_utc": captured_at,
                "temperature_c": temperature,
                "target_temperature_c": _to_float(state.get("target")),
                "raw_payload": {
                    "product": product,
                    "device": device,
                },
            }
        )
    return rows


def _hive_captured_at(
    last_seen: Any,
    *,
    fallback_time: datetime,
    prefer_fallback_when_stale: bool,
) -> datetime:
    parsed = _parse_epoch_ms(last_seen)
    if parsed is None:
        return fallback_time
    # A device can report a garbage far-future timestamp (a Hive boiler module
    # once reported a lastSeen decades ahead → a "2068" reading that then read as
    # perpetually fresh and shadowed the real latest temperature). Never trust a
    # future device clock: clamp anything meaningfully ahead of observation time
    # back to the fallback, regardless of the stale-preference flag.
    if parsed - fallback_time > HIVE_FRESHNESS_LIMIT:
        return fallback_time
    if prefer_fallback_when_stale and fallback_time - parsed > HIVE_FRESHNESS_LIMIT:
        return fallback_time
    return parsed


def parse_open_meteo_daily_fields(
    payload: Mapping[str, Any],
    *,
    timezone: str = DEFAULT_WEATHER_TIMEZONE,
) -> list[JsonDict]:
    tz = _zoneinfo(timezone)
    daily = _as_dict(payload.get("daily"))
    dates = _as_list(daily.get("time"))
    night_stats = _overnight_stats_by_date(payload, tz)
    rows: list[JsonDict] = []

    for index, value in enumerate(dates):
        calendar_date = _parse_date(value)
        if calendar_date is None:
            continue
        night = night_stats.get(calendar_date, WeatherNightStats())
        rows.append(
            {
                "calendar_date": calendar_date,
                "source": "open_meteo",
                "latitude": _to_float(payload.get("latitude")) or KILMARNOCK_LATITUDE,
                "longitude": _to_float(payload.get("longitude")) or KILMARNOCK_LONGITUDE,
                "temp_high_c": _to_float(_nth(daily.get("temperature_2m_max"), index)),
                "temp_low_c": _to_float(_nth(daily.get("temperature_2m_min"), index)),
                "overnight_low_c": night.low_c,
                "overnight_wind_max_mph": night.wind_max_mph,
                "overnight_wind_gust_mph": night.wind_gust_mph,
                "overnight_wind_direction_deg": night.wind_direction_deg,
                "overnight_relative_humidity_mean_pct": night.relative_humidity_mean_pct,
                "wind_max_mph": _to_float(_nth(daily.get("wind_speed_10m_max"), index)),
                "wind_gust_mph": _to_float(_nth(daily.get("wind_gusts_10m_max"), index)),
                "precipitation_mm": _to_float(_nth(daily.get("precipitation_sum"), index)),
                "sunrise_utc": _parse_local_datetime(_nth(daily.get("sunrise"), index), tz),
                "sunset_utc": _parse_local_datetime(_nth(daily.get("sunset"), index), tz),
                "raw_payload": {
                    "daily": _daily_payload_for_index(daily, index),
                    "overnight": {
                        "low_c": night.low_c,
                        "wind_max_mph": night.wind_max_mph,
                        "wind_gust_mph": night.wind_gust_mph,
                        "wind_direction_deg": night.wind_direction_deg,
                        "relative_humidity_mean_pct": night.relative_humidity_mean_pct,
                        "sample_count": night.sample_count,
                    },
                },
            }
        )
    return rows


def _hive_products(payloads: HivePayloads) -> list[JsonDict]:
    products = [
        *_extract_hive_items(payloads.get_all, "products"),
        *_extract_hive_items(payloads.products, "products"),
    ]
    seen: set[str] = set()
    unique: list[JsonDict] = []
    for product in products:
        product_id = _to_str(product.get("id")) or f"anonymous-{len(unique)}"
        if product_id in seen:
            continue
        seen.add(product_id)
        unique.append(product)
    return unique


def _hive_devices(payloads: HivePayloads) -> list[JsonDict]:
    return [
        *_extract_hive_items(payloads.get_all, "devices"),
        *_extract_hive_items(payloads.devices, "devices"),
    ]


def _extract_hive_items(payload: Any, key: str) -> list[JsonDict]:
    parsed = _as_dict(payload).get("parsed")
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    parsed_dict = _as_dict(parsed)
    values = parsed_dict.get(key)
    if isinstance(values, list):
        return [item for item in values if isinstance(item, dict)]
    values = _as_dict(payload).get(key)
    if isinstance(values, list):
        return [item for item in values if isinstance(item, dict)]
    return []


def _overnight_stats_by_date(
    payload: Mapping[str, Any], tz: ZoneInfo
) -> dict[date, WeatherNightStats]:
    hourly = _as_dict(payload.get("hourly"))
    times = _as_list(hourly.get("time"))
    temps = _as_list(hourly.get("temperature_2m"))
    winds = _as_list(hourly.get("wind_speed_10m"))
    gusts = _as_list(hourly.get("wind_gusts_10m"))
    directions = _as_list(hourly.get("wind_direction_10m"))
    humidity = _as_list(hourly.get("relative_humidity_2m"))
    samples_by_date: dict[
        date,
        list[
            tuple[
                float | None,
                float | None,
                float | None,
                float | None,
                float | None,
            ]
        ],
    ] = {}

    for index, value in enumerate(times):
        local_dt = _parse_local_datetime(value, tz, keep_tz=True)
        if local_dt is None:
            continue
        sample_date = _night_sample_date(local_dt)
        if sample_date is None:
            continue
        samples_by_date.setdefault(sample_date, []).append(
            (
                _to_float(_nth(temps, index)),
                _to_float(_nth(winds, index)),
                _to_float(_nth(gusts, index)),
                _to_float(_nth(directions, index)),
                _to_float(_nth(humidity, index)),
            )
        )

    return {
        sample_date: WeatherNightStats(
            low_c=_min_not_none(temp for temp, _, _, _, _ in samples),
            wind_max_mph=_max_not_none(wind for _, wind, _, _, _ in samples),
            wind_gust_mph=_max_not_none(gust for _, _, gust, _, _ in samples),
            # Direction is circular: 350° + 10° means north, not south. A
            # vector mean preserves that geometry and returns ``None`` when
            # opposing samples cancel and no prevailing direction exists.
            wind_direction_deg=_circular_mean_degrees(
                direction for _, _, _, direction, _ in samples
            ),
            relative_humidity_mean_pct=_mean_not_none(
                humidity_pct for _, _, _, _, humidity_pct in samples
            ),
            sample_count=len(samples),
        )
        for sample_date, samples in samples_by_date.items()
    }


def _night_sample_date(value: datetime) -> date | None:
    local_time = value.timetz().replace(tzinfo=None)
    if local_time >= time(20, 0):
        return value.date() + timedelta(days=1)
    if local_time <= time(8, 0):
        return value.date()
    return None


def _daily_payload_for_index(daily: Mapping[str, Any], index: int) -> JsonDict:
    return {key: _nth(value, index) for key, value in daily.items() if isinstance(value, list)}


def _apply_fields(instance: Any, fields: Mapping[str, Any]) -> None:
    for key, value in fields.items():
        setattr(instance, key, value)


def _as_dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> JsonList:
    return value if isinstance(value, list) else []


def _nth(value: Any, index: int) -> Any:
    values = _as_list(value)
    return values[index] if index < len(values) else None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _parse_epoch_ms(value: Any) -> datetime | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    try:
        return datetime.fromtimestamp(numeric / 1000, UTC).replace(tzinfo=None)
    except (OSError, OverflowError, ValueError):
        return None


def _parse_local_datetime(
    value: Any,
    tz: ZoneInfo,
    *,
    keep_tz: bool = False,
) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    else:
        parsed = parsed.astimezone(tz)
    return parsed if keep_tz else parsed.astimezone(UTC).replace(tzinfo=None)


def _zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_WEATHER_TIMEZONE)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _min_not_none(values: Any) -> float | None:
    numeric = [value for value in values if value is not None]
    return min(numeric) if numeric else None


def _max_not_none(values: Any) -> float | None:
    numeric = [value for value in values if value is not None]
    return max(numeric) if numeric else None


def _mean_not_none(values: Any) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    return round(sum(numeric) / len(numeric), 1) if numeric else None


def _circular_mean_degrees(values: Any) -> float | None:
    numeric = [float(value) % 360.0 for value in values if value is not None]
    if not numeric:
        return None
    x = sum(math.cos(math.radians(value)) for value in numeric)
    y = sum(math.sin(math.radians(value)) for value in numeric)
    if math.hypot(x, y) < 1e-9:
        return None
    rounded = round(math.degrees(math.atan2(y, x)) % 360.0, 1)
    # Rounding a value infinitesimally below north can produce 360.0 even
    # though the modulo above is in [0, 360). Keep one canonical north value.
    return 0.0 if rounded == 360.0 else rounded


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
