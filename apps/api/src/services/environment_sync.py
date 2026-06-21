"""Hive indoor-temperature and Open-Meteo weather sync helpers."""

from __future__ import annotations

import base64
import json
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

JsonDict = dict[str, Any]
JsonList = list[Any]

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
KILMARNOCK_LATITUDE = 55.6045
KILMARNOCK_LONGITUDE = -4.5249
DEFAULT_WEATHER_TIMEZONE = "Europe/London"


class EnvironmentSyncError(RuntimeError):
    """Base error for environmental sync failures."""


class HiveCredentialsError(EnvironmentSyncError):
    """Raised when Hive sync cannot start because credentials are incomplete."""


class HiveLoginError(EnvironmentSyncError):
    """Raised when Hive login fails without exposing credentials."""


@dataclass(frozen=True)
class HiveCredentials:
    email: str
    password: str
    tokenstore_b64: str = ""

    @classmethod
    def from_settings(cls) -> HiveCredentials:
        return cls(
            email=settings.hive_email,
            password=settings.hive_password,
            tokenstore_b64=settings.hive_tokenstore_b64,
        )

    def validate(self) -> None:
        if self.tokenstore_b64:
            return
        if not self.email or not self.password:
            raise HiveCredentialsError(
                "Hive credentials are not configured; set HIVE_TOKENSTORE_B64 "
                "(preferred — full login needs SMS MFA) or HIVE_EMAIL and HIVE_PASSWORD."
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
    sample_count: int = 0


class HiveClient:
    """Sync pyhiveapi wrapper with a headless Cognito refresh-token resume path.

    Mark's Hive account authenticates through AWS Cognito with ``SMS_MFA``, so a
    headless email/password login is impossible — it returns an SMS challenge.
    The unattended path resumes from a persisted Cognito **refresh token**
    (``HIVE_TOKENSTORE_B64``) via ``REFRESH_TOKEN_AUTH``; seed it once with a
    one-time SMS-2FA login (``scripts/bootstrap_hive_tokenstore.py``). A full
    email/password login remains only as a last-ditch fallback and will fail on
    SMS_MFA accounts.
    """

    def __init__(self, credentials: HiveCredentials | None = None) -> None:
        self.credentials = credentials or HiveCredentials.from_settings()
        self._api: Any | None = None

    def login(self) -> Any:
        if self._api is not None:
            return self._api

        self.credentials.validate()
        api_cls, auth_cls = self._import_pyhiveapi()

        if self.credentials.tokenstore_b64:
            try:
                token = self._resume_id_token(auth_cls)
            except HiveLoginError:
                # Fall back to a full login only when password creds exist;
                # otherwise surface the failure so the operator re-seeds the blob.
                if not self.credentials.email or not self.credentials.password:
                    raise
            else:
                self._api = api_cls(token=token)
                return self._api

        return self._full_login(auth_cls, api_cls)

    def _resume_id_token(self, auth_cls: Any) -> str:
        """Exchange the persisted refresh token for a fresh Cognito id token."""
        blob = _decode_hive_token_blob(self.credentials.tokenstore_b64)
        username = _to_str(blob.get("username"))
        refresh_token = _to_str(blob.get("refresh_token"))
        if not username or not refresh_token:
            raise HiveLoginError("Hive token blob is missing username or refresh_token.")
        try:
            # pyhiveapi's Auth.refresh_token() is broken (a stray trailing comma
            # makes AuthParameters a tuple), so call Cognito directly. Auth.__init__
            # builds the boto3 client and populates the private client id for us.
            auth = auth_cls(username, "")
            params: dict[str, str] = {"REFRESH_TOKEN": refresh_token}
            device_key = getattr(auth, "device_key", None)
            if device_key:
                params["DEVICE_KEY"] = str(device_key)
            result = auth.client.initiate_auth(
                ClientId=_hive_client_id(auth),
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters=params,
            )
        except HiveLoginError:
            raise
        except Exception as exc:
            raise HiveLoginError("Hive token refresh failed; re-seed HIVE_TOKENSTORE_B64.") from exc
        return _extract_hive_id_token(result)

    def _full_login(self, auth_cls: Any, api_cls: Any) -> Any:
        try:
            auth = auth_cls(self.credentials.email, self.credentials.password)
            result = auth.login()
            if isinstance(result, dict) and result.get("ChallengeName") == "SMS_MFA":
                raise HiveLoginError(
                    "Hive login requires SMS MFA; seed HIVE_TOKENSTORE_B64 via a "
                    "one-time SMS-2FA login instead of a headless password login."
                )
            token = _extract_hive_id_token(result)
            self._api = api_cls(token=token)
            return self._api
        except HiveLoginError:
            raise
        except Exception as exc:
            raise HiveLoginError("Hive login failed; check configured credentials.") from exc

    @staticmethod
    def _import_pyhiveapi() -> tuple[Any, Any]:
        try:
            from pyhiveapi import (  # type: ignore[import-untyped, unused-ignore]
                API,
                Auth,
            )
        except ImportError as exc:  # pragma: no cover - exercised only in missing envs
            raise EnvironmentSyncError("pyhiveapi is not installed.") from exc
        return API, Auth

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
        captured_at = _parse_epoch_ms(product.get("lastSeen")) or fallback_time
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
                        "sample_count": night.sample_count,
                    },
                },
            }
        )
    return rows


def _extract_hive_id_token(result: Any) -> str:
    if not isinstance(result, dict):
        raise HiveLoginError("Hive login returned an unexpected response.")
    auth_result = _as_dict(result.get("AuthenticationResult"))
    token = _to_str(auth_result.get("IdToken"))
    if not token:
        raise HiveLoginError("Hive login did not return an id token.")
    return token


def _decode_hive_token_blob(blob: str) -> JsonDict:
    try:
        decoded = base64.b64decode(blob, validate=True)
        data = json.loads(decoded)
    except (ValueError, TypeError) as exc:
        raise HiveLoginError("Hive token blob is not valid base64 JSON.") from exc
    if not isinstance(data, dict):
        raise HiveLoginError("Hive token blob did not decode to an object.")
    return data


def _hive_client_id(auth: Any) -> str:
    client_id = getattr(auth, "_HiveAuth__client_id", None)
    if not client_id:
        raise HiveLoginError("Hive Cognito client id is unavailable.")
    return str(client_id)


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
    samples_by_date: dict[date, list[tuple[float | None, float | None, float | None]]] = {}

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
            )
        )

    return {
        sample_date: WeatherNightStats(
            low_c=_min_not_none(temp for temp, _, _ in samples),
            wind_max_mph=_max_not_none(wind for _, wind, _ in samples),
            wind_gust_mph=_max_not_none(gust for _, _, gust in samples),
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
