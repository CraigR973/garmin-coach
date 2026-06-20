"""Garmin Connect client, parsers, and idempotent sync helpers."""

from __future__ import annotations

import inspect
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import Activity, ActivityTimeSeries, DailyMetric, Sleep

JsonDict = dict[str, Any]
JsonList = list[Any]


class GarminSyncError(RuntimeError):
    """Base error for Garmin sync failures."""


class GarminCredentialsError(GarminSyncError):
    """Raised when Garmin sync cannot start because credentials are incomplete."""


class GarminLoginError(GarminSyncError):
    """Raised when Garmin login fails without exposing credentials."""


@dataclass(frozen=True)
class GarminCredentials:
    email: str
    password: str
    tokenstore: Path

    @classmethod
    def from_settings(cls) -> GarminCredentials:
        return cls(
            email=settings.garmin_email,
            password=settings.garmin_password,
            tokenstore=Path(os.path.expanduser(settings.garmin_tokenstore)),
        )

    def validate(self) -> None:
        if not self.email or not self.password:
            raise GarminCredentialsError(
                "Garmin credentials are not configured; set GARMIN_EMAIL and GARMIN_PASSWORD."
            )


@dataclass(frozen=True)
class GarminDailyPayloads:
    training_readiness: Any = None
    sleep: Any = None
    hrv: Any = None
    body_battery: Any = None
    rhr: Any = None
    weigh_ins: Any = None
    max_metrics_vo2: Any = None
    training_status: Any = None
    stress: Any = None
    stats: Any = None


@dataclass(frozen=True)
class GarminActivityPayloads:
    summaries: list[JsonDict] = field(default_factory=list)
    details_by_activity_id: dict[int, JsonDict] = field(default_factory=dict)


@dataclass(frozen=True)
class GarminSyncResult:
    daily_metrics_synced: int = 0
    sleep_synced: int = 0
    activities_synced: int = 0
    timeseries_samples_synced: int = 0


class GarminConnectClient:
    """Thin wrapper around garminconnect with token-cache first login."""

    def __init__(self, credentials: GarminCredentials | None = None) -> None:
        self.credentials = credentials or GarminCredentials.from_settings()
        self._client: Any | None = None

    def login(self) -> Any:
        if self._client is not None:
            return self._client

        self.credentials.validate()
        tokenstore = str(self.credentials.tokenstore)
        try:
            from garminconnect import Garmin
        except ImportError as exc:  # pragma: no cover - exercised only in missing envs
            raise GarminSyncError("garminconnect is not installed.") from exc

        try:
            client = Garmin()
            client.login(tokenstore)
        except Exception:
            client = self._fresh_login(Garmin, tokenstore)

        self._client = client
        return client

    def _fresh_login(self, garmin_cls: Any, tokenstore: str) -> Any:
        try:
            params = inspect.signature(garmin_cls.__init__).parameters
            if "prompt_mfa" in params:
                client = garmin_cls(
                    email=self.credentials.email,
                    password=self.credentials.password,
                    prompt_mfa=_read_mfa_code,
                )
                client.login(tokenstore)
            elif "return_on_mfa" in params:
                client = garmin_cls(
                    email=self.credentials.email,
                    password=self.credentials.password,
                    return_on_mfa=True,
                )
                result = client.login(tokenstore)
                if isinstance(result, tuple) and result and result[0] == "needs_mfa":
                    client.resume_login(result[1], _read_mfa_code())
            else:
                client = garmin_cls(
                    email=self.credentials.email,
                    password=self.credentials.password,
                )
                client.login(tokenstore)

            self.credentials.tokenstore.mkdir(parents=True, exist_ok=True)
            if hasattr(client, "client") and hasattr(client.client, "dump"):
                client.client.dump(tokenstore)
            return client
        except Exception as exc:
            raise GarminLoginError(
                f"Garmin login failed; check credentials, MFA, and tokenstore {tokenstore}."
            ) from exc

    def fetch_daily_payloads(
        self, calendar_date: date, lookback_days: int = 7
    ) -> GarminDailyPayloads:
        client = self.login()
        target = calendar_date.isoformat()
        start = (calendar_date - timedelta(days=lookback_days)).isoformat()
        return GarminDailyPayloads(
            training_readiness=client.get_training_readiness(target),
            sleep=client.get_sleep_data(target),
            hrv=client.get_hrv_data(target),
            body_battery=client.get_body_battery(start, target),
            rhr=client.get_rhr_day(target),
            weigh_ins=client.get_weigh_ins(start, target),
            max_metrics_vo2=client.get_max_metrics(target),
            training_status=client.get_training_status(target),
            stress=client.get_stress_data(target),
            stats=client.get_stats(target),
        )

    def fetch_activity_payloads(
        self,
        start_date: date,
        end_date: date,
        *,
        include_details: bool = True,
    ) -> GarminActivityPayloads:
        client = self.login()
        summaries = client.get_activities_by_date(start_date.isoformat(), end_date.isoformat())
        if not isinstance(summaries, list):
            summaries = []
        details_by_activity_id: dict[int, JsonDict] = {}
        if include_details:
            for summary in summaries:
                activity_id = _to_int(summary.get("activityId"))
                if activity_id is None:
                    continue
                details = client.get_activity_details(activity_id, maxchart=2000, maxpoly=4000)
                if isinstance(details, dict):
                    details_by_activity_id[activity_id] = details
        return GarminActivityPayloads(
            summaries=summaries,
            details_by_activity_id=details_by_activity_id,
        )


class GarminSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sync_daily(
        self,
        user_id: uuid.UUID,
        calendar_date: date,
        payloads: GarminDailyPayloads,
        *,
        commit: bool = True,
    ) -> GarminSyncResult:
        metric_fields = parse_daily_metric_fields(calendar_date, payloads)
        sleep_fields = parse_sleep_fields(payloads.sleep)
        daily_count = 0
        sleep_count = 0

        if metric_fields:
            metric_result = await self.session.execute(
                select(DailyMetric).where(
                    DailyMetric.user_id == user_id,
                    DailyMetric.calendar_date == calendar_date,
                )
            )
            metric = metric_result.scalar_one_or_none()
            if metric is None:
                metric = DailyMetric(user_id=user_id, calendar_date=calendar_date)
                self.session.add(metric)
            _apply_fields(metric, metric_fields)
            daily_count = 1

        if sleep_fields:
            sleep_date = sleep_fields.get("calendar_date", calendar_date)
            sleep_result = await self.session.execute(
                select(Sleep).where(Sleep.user_id == user_id, Sleep.calendar_date == sleep_date)
            )
            sleep = sleep_result.scalar_one_or_none()
            if sleep is None:
                sleep = Sleep(user_id=user_id, calendar_date=sleep_date)
                self.session.add(sleep)
            _apply_fields(sleep, sleep_fields)
            sleep_count = 1

        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return GarminSyncResult(daily_metrics_synced=daily_count, sleep_synced=sleep_count)

    async def sync_activities(
        self,
        user_id: uuid.UUID,
        payloads: GarminActivityPayloads,
        *,
        commit: bool = True,
    ) -> GarminSyncResult:
        activity_count = 0
        sample_count = 0

        for summary in payloads.summaries:
            activity_fields = parse_activity_summary_fields(summary)
            activity_id = activity_fields.get("garmin_activity_id")
            if activity_id is None:
                continue
            result = await self.session.execute(
                select(Activity).where(
                    Activity.user_id == user_id,
                    Activity.garmin_activity_id == activity_id,
                )
            )
            activity = result.scalar_one_or_none()
            if activity is None:
                activity = Activity(user_id=user_id, **activity_fields)
                self.session.add(activity)
            else:
                _apply_fields(activity, activity_fields)
            await self.session.flush()
            activity_count += 1

            details = payloads.details_by_activity_id.get(int(activity_id))
            if details:
                await self.session.execute(
                    delete(ActivityTimeSeries).where(ActivityTimeSeries.activity_id == activity.id)
                )
                rows = parse_activity_timeseries_fields(details)
                for row in rows:
                    self.session.add(ActivityTimeSeries(activity_id=activity.id, **row))
                sample_count += len(rows)

        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return GarminSyncResult(
            activities_synced=activity_count,
            timeseries_samples_synced=sample_count,
        )


def parse_daily_metric_fields(calendar_date: date, payloads: GarminDailyPayloads) -> JsonDict:
    readiness = _pick_payload_for_date(payloads.training_readiness, calendar_date)
    hrv_summary = _as_dict(payloads.hrv).get("hrvSummary", {})
    body_battery = _pick_payload_for_date(payloads.body_battery, calendar_date)
    stress = _pick_payload_for_date(payloads.stress, calendar_date)
    stats = _pick_payload_for_date(payloads.stats, calendar_date)
    training_status = _extract_training_status(payloads.training_status)
    weight_kg = _extract_weight_kg(payloads.weigh_ins, calendar_date)
    vo2max = _extract_vo2max(payloads.max_metrics_vo2, calendar_date)
    rhr = _extract_rhr(payloads.rhr, calendar_date) or _to_int(stats.get("restingHeartRate"))
    baseline = _as_dict(hrv_summary.get("baseline"))

    recorded_at = (
        _parse_garmin_datetime(readiness.get("timestamp"))
        or _parse_garmin_datetime(stats.get("lastSyncTimestampGMT"))
        or _parse_garmin_datetime(hrv_summary.get("createTimeStamp"))
    )

    return {
        "calendar_date": calendar_date,
        "recorded_at_utc": recorded_at,
        "readiness_score": _to_int(readiness.get("score")),
        "readiness_level": _to_str(readiness.get("level")),
        "readiness_sleep_score": _to_int(readiness.get("sleepScore")),
        "recovery_time_min": _to_int(readiness.get("recoveryTime")),
        "acute_load": _to_float(readiness.get("acuteLoad")),
        "training_status": training_status,
        "hrv_last_night_avg_ms": _to_int(hrv_summary.get("lastNightAvg")),
        "hrv_weekly_avg_ms": _to_int(
            hrv_summary.get("weeklyAvg") or readiness.get("hrvWeeklyAverage")
        ),
        "hrv_status": _to_str(hrv_summary.get("status")),
        "hrv_baseline_low_ms": _to_int(baseline.get("balancedLow")),
        "hrv_baseline_high_ms": _to_int(baseline.get("balancedUpper")),
        "resting_heart_rate_bpm": rhr,
        "stress_avg": _to_float(stress.get("avgStressLevel") or stats.get("averageStressLevel")),
        "body_battery_charged": _to_int(
            body_battery.get("charged") or stats.get("bodyBatteryChargedValue")
        ),
        "body_battery_drained": _to_int(
            body_battery.get("drained") or stats.get("bodyBatteryDrainedValue")
        ),
        "body_battery_end": _extract_body_battery_end(body_battery)
        or _to_int(stats.get("bodyBatteryMostRecentValue")),
        "weight_kg": weight_kg,
        "vo2max": vo2max,
        "raw_payload": {
            "training_readiness": readiness,
            "hrv": payloads.hrv,
            "body_battery": body_battery,
            "rhr": payloads.rhr,
            "weigh_ins": payloads.weigh_ins,
            "max_metrics_vo2": payloads.max_metrics_vo2,
            "training_status": payloads.training_status,
            "stress": stress,
            "stats": stats,
        },
    }


def parse_sleep_fields(payload: Any) -> JsonDict:
    sleep = _as_dict(payload)
    dto = _as_dict(sleep.get("dailySleepDTO"))
    if not dto:
        return {}
    calendar_date = _parse_date(dto.get("calendarDate"))
    if calendar_date is None:
        return {}

    scores = _as_dict(dto.get("sleepScores"))
    overall = _as_dict(scores.get("overall"))
    score = _to_int(overall.get("value"))
    deep = _to_int(dto.get("deepSleepSeconds"))
    light = _to_int(dto.get("lightSleepSeconds"))
    rem = _to_int(dto.get("remSleepSeconds"))
    awake = _to_int(dto.get("awakeSleepSeconds"))
    unmeasurable = _to_int(dto.get("unmeasurableSleepSeconds"))
    duration = _to_int(dto.get("sleepTimeSeconds"))
    if duration is None:
        duration = sum(value or 0 for value in (deep, light, rem, awake, unmeasurable))

    return {
        "calendar_date": calendar_date,
        "sleep_start_utc": _parse_garmin_datetime(dto.get("sleepStartTimestampGMT")),
        "sleep_end_utc": _parse_garmin_datetime(dto.get("sleepEndTimestampGMT")),
        "score": score,
        "age_adjusted_score": min(score + 4, 100) if score is not None else None,
        "qualifier": _to_str(overall.get("qualifierKey")),
        "duration_sec": duration,
        "deep_sleep_sec": deep,
        "light_sleep_sec": light,
        "rem_sleep_sec": rem,
        "awake_sleep_sec": awake,
        "unmeasurable_sleep_sec": unmeasurable,
        "average_spo2_pct": _to_float(dto.get("averageSpO2Value")),
        "lowest_spo2_pct": _to_float(dto.get("lowestSpO2Value")),
        "average_respiration": _to_float(dto.get("averageRespirationValue")),
        "resting_heart_rate_bpm": _to_int(
            dto.get("restingHeartRate") or sleep.get("restingHeartRate")
        ),
        "avg_overnight_hrv_ms": _to_int(sleep.get("avgOvernightHrv")),
        "hrv_status": _to_str(sleep.get("hrvStatus")),
        "avg_sleep_stress": _to_float(dto.get("avgSleepStress")),
        "restless_moments_count": _to_int(sleep.get("restlessMomentsCount")),
        "body_battery_change": _to_int(sleep.get("bodyBatteryChange")),
        "factors_json": scores,
        "raw_payload": sleep,
    }


def parse_activity_summary_fields(summary: Mapping[str, Any]) -> JsonDict:
    activity_type = _as_dict(summary.get("activityType"))
    type_key = _to_str(activity_type.get("typeKey")) or "unknown"
    start = _parse_garmin_datetime(summary.get("startTimeGMT") or summary.get("beginTimestamp"))
    if start is None:
        start = datetime.now(UTC).replace(tzinfo=None)
    return {
        "garmin_activity_id": _to_int(summary.get("activityId")),
        "garmin_activity_uuid": _to_str(summary.get("activityUUID")),
        "activity_name": _to_str(summary.get("activityName")) or "Garmin activity",
        "activity_type": type_key,
        "start_utc": start,
        "end_utc": _parse_garmin_datetime(summary.get("endTimeGMT")),
        "duration_sec": _to_float(summary.get("duration")),
        "elapsed_duration_sec": _to_float(summary.get("elapsedDuration")),
        "moving_duration_sec": _to_float(summary.get("movingDuration")),
        "distance_m": _to_float(summary.get("distance")),
        "calories": _to_float(summary.get("calories")),
        "avg_heart_rate_bpm": _to_int(summary.get("averageHR")),
        "max_heart_rate_bpm": _to_int(summary.get("maxHR")),
        "avg_power_watts": _to_int(summary.get("avgPower")),
        "max_power_watts": _to_int(summary.get("maxPower")),
        "normalized_power_watts": _to_int(summary.get("normPower")),
        "intensity_factor": _to_float(summary.get("intensityFactor")),
        "training_load": _to_float(summary.get("activityTrainingLoad")),
        "aerobic_training_effect": _to_float(summary.get("aerobicTrainingEffect")),
        "anaerobic_training_effect": _to_float(summary.get("anaerobicTrainingEffect")),
        "avg_cadence_rpm": _to_float(summary.get("averageBikingCadenceInRevPerMinute")),
        "max_cadence_rpm": _to_float(summary.get("maxBikingCadenceInRevPerMinute")),
        "avg_respiration": _to_float(summary.get("avgRespirationRate")),
        "max_respiration": _to_float(summary.get("maxRespirationRate")),
        "min_temperature_c": _to_float(summary.get("minTemperature")),
        "max_temperature_c": _to_float(summary.get("maxTemperature")),
        "exclude_from_recovery": "strength" in type_key.lower(),
        "raw_summary": dict(summary),
    }


def parse_metric_descriptor_keys(details: Mapping[str, Any]) -> list[str]:
    descriptors = details.get("metricDescriptors")
    if not isinstance(descriptors, list):
        return []
    return [
        str(descriptor["key"])
        for descriptor in descriptors
        if isinstance(descriptor, dict) and descriptor.get("key") is not None
    ]


def parse_activity_timeseries_fields(details: Mapping[str, Any]) -> list[JsonDict]:
    descriptors = {
        str(descriptor["key"]): int(descriptor["metricsIndex"])
        for descriptor in details.get("metricDescriptors", [])
        if isinstance(descriptor, dict)
        and descriptor.get("key") is not None
        and descriptor.get("metricsIndex") is not None
    }
    rows: list[JsonDict] = []
    for index, sample in enumerate(details.get("activityDetailMetrics", [])):
        if not isinstance(sample, dict):
            continue
        values = sample.get("metrics")
        if not isinstance(values, list):
            continue
        metric_map = {
            key: values[position] if position < len(values) else None
            for key, position in descriptors.items()
        }
        rows.append(
            {
                "sample_index": index,
                "timestamp_utc": _parse_garmin_datetime(metric_map.get("directTimestamp")),
                "elapsed_sec": _to_float(metric_map.get("sumElapsedDuration")),
                "moving_duration_sec": _to_float(metric_map.get("sumMovingDuration")),
                "distance_m": _to_float(metric_map.get("sumDistance")),
                "power_watts": _to_float(metric_map.get("directPower")),
                "heart_rate_bpm": _to_float(metric_map.get("directHeartRate")),
                "cadence_rpm": _to_float(
                    metric_map.get("directBikeCadence")
                    if metric_map.get("directBikeCadence") is not None
                    else metric_map.get("directFractionalCadence")
                ),
                "respiration": _to_float(metric_map.get("directRespirationRate")),
                "performance_condition": _to_float(metric_map.get("directPerformanceCondition")),
                "available_stamina": _to_float(metric_map.get("directAvailableStamina")),
                "potential_stamina": _to_float(metric_map.get("directPotentialStamina")),
                "speed_mps": _to_float(metric_map.get("directSpeed")),
                "air_temperature_c": _to_float(metric_map.get("directAirTemperature")),
                "raw_metrics": metric_map,
            }
        )
    return rows


def _read_mfa_code() -> str:
    return input("Garmin two-factor code: ").strip()


def _apply_fields(instance: Any, fields: Mapping[str, Any]) -> None:
    for key, value in fields.items():
        setattr(instance, key, value)


def _as_dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _pick_payload_for_date(payload: Any, calendar_date: date) -> JsonDict:
    if isinstance(payload, list):
        for item in payload:
            item_dict = _as_dict(item)
            if _payload_date(item_dict) == calendar_date:
                return item_dict
        return _as_dict(payload[0]) if payload else {}
    item = _as_dict(payload)
    return item if not item or _payload_date(item) in (None, calendar_date) else {}


def _payload_date(payload: Mapping[str, Any]) -> date | None:
    for key in ("calendarDate", "date", "summaryDate"):
        parsed = _parse_date(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _parse_garmin_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value) / 1000, UTC).replace(tzinfo=None)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


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


def _extract_training_status(payload: Any) -> str | None:
    status_data = _as_dict(
        _as_dict(_as_dict(payload).get("mostRecentTrainingStatus")).get("latestTrainingStatusData")
    )
    if not status_data:
        return None
    primary = next(
        (value for value in status_data.values() if isinstance(value, dict)),
        {},
    )
    return _to_str(primary.get("trainingStatusFeedbackPhrase") or primary.get("trainingStatus"))


def _extract_rhr(payload: Any, calendar_date: date) -> int | None:
    metrics_map = _as_dict(_as_dict(_as_dict(payload).get("allMetrics")).get("metricsMap"))
    values = metrics_map.get("WELLNESS_RESTING_HEART_RATE")
    if not isinstance(values, list):
        return None
    for item in values:
        item_dict = _as_dict(item)
        if _parse_date(item_dict.get("calendarDate")) == calendar_date:
            return _to_int(item_dict.get("value"))
    return None


def _extract_weight_kg(payload: Any, calendar_date: date) -> float | None:
    summaries = _as_dict(payload).get("dailyWeightSummaries")
    if not isinstance(summaries, list):
        return None
    for summary in summaries:
        summary_dict = _as_dict(summary)
        if _parse_date(summary_dict.get("summaryDate")) != calendar_date:
            continue
        latest = _as_dict(summary_dict.get("latestWeight"))
        grams = _to_float(latest.get("weight"))
        return grams / 1000 if grams is not None else None
    return None


def _extract_vo2max(payload: Any, calendar_date: date) -> float | None:
    item = _as_dict(payload[0]) if isinstance(payload, list) and payload else _as_dict(payload)
    for key in ("cycling", "generic"):
        section = _as_dict(item.get(key))
        section_date = _parse_date(section.get("calendarDate"))
        if section_date not in (None, calendar_date):
            continue
        value = _to_float(section.get("vo2MaxPreciseValue") or section.get("vo2MaxValue"))
        if value is not None:
            return value
    return None


def _extract_body_battery_end(payload: Mapping[str, Any]) -> int | None:
    values = payload.get("bodyBatteryValuesArray")
    if not isinstance(values, list) or not values:
        return None
    last = values[-1]
    if not isinstance(last, list) or len(last) < 2:
        return None
    return _to_int(last[1])
