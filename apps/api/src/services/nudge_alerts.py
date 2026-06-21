"""Evening nudges, thermal monitoring, and source freshness alerts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, DailyMetric, TemperatureReading, WeatherDaily
from src.models.profile import Profile
from src.services.push_notification_service import send_notification

ANALYSIS_TYPE_EVENING_NUDGE = "evening_nudge"
ANALYSIS_TYPE_THERMAL_ALERT = "thermal_alert"
ANALYSIS_TYPE_STALE_SOURCE_ALERT = "stale_source_alert"
PROMPT_VERSION = "notification-rules:v1"

EVENING_NUDGE_TIME = time(20, 0)
EVENING_NUDGE_WINDOW_MIN = 20
HIVE_FRESHNESS_LIMIT = timedelta(minutes=45)
GARMIN_FRESHNESS_HOUR = 8


@dataclass(frozen=True)
class NotificationPlan:
    analysis_type: str
    tag: str
    title: str
    body: str
    severity: str
    data: dict[str, object]
    context: dict[str, object]


@dataclass(frozen=True)
class FreshnessSnapshot:
    local_date: date
    local_now: datetime
    now_utc: datetime
    last_garmin_recorded_at_utc: datetime | None
    last_hive_captured_at_utc: datetime | None
    latest_weather_date: date | None


def local_now(timezone_name: str, now_utc: datetime | None = None) -> datetime:
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return now.astimezone(timezone).replace(tzinfo=None)


def is_evening_nudge_due(
    *,
    timezone_name: str,
    now_utc: datetime | None = None,
    target: time = EVENING_NUDGE_TIME,
    window_min: int = EVENING_NUDGE_WINDOW_MIN,
) -> bool:
    current = local_now(timezone_name, now_utc)
    target_dt = datetime.combine(current.date(), target)
    return target_dt <= current < target_dt + timedelta(minutes=window_min)


def build_evening_nudge_plan(subject_date: date) -> NotificationPlan:
    return NotificationPlan(
        analysis_type=ANALYSIS_TYPE_EVENING_NUDGE,
        tag=f"sleep-protocol-{subject_date.isoformat()}",
        title="Evening sleep protocol",
        body=(
            "20:00 breathing, pre-cool the room toward 17C, finish snack by "
            "21:30, seal the bedroom near 22:00, bed 23:15."
        ),
        severity="info",
        data={"url": "/", "kind": "evening_nudge"},
        context={"subjectDate": subject_date.isoformat(), "rule": "sleep_protocol"},
    )


def evaluate_thermal_alert(
    reading: TemperatureReading | None,
    *,
    timezone_name: str,
    now_utc: datetime | None = None,
) -> NotificationPlan | None:
    if reading is None:
        return None

    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    captured = reading.captured_at_utc
    captured_aware = captured.replace(tzinfo=UTC) if captured.tzinfo is None else captured
    if now - captured_aware > HIVE_FRESHNESS_LIMIT:
        return None

    current = local_now(timezone_name, now)
    temp_c = round(float(reading.temperature_c), 1)
    subject_date = current.date()
    context = {
        "subjectDate": subject_date.isoformat(),
        "temperatureC": temp_c,
        "capturedAtUtc": captured_aware.replace(tzinfo=None).isoformat(),
    }

    if temp_c >= 20.0:
        return NotificationPlan(
            analysis_type=ANALYSIS_TYPE_THERMAL_ALERT,
            tag=f"thermal-peak-20-{subject_date.isoformat()}",
            title="Bedroom temperature high",
            body=(
                f"Bedroom is {temp_c:.1f}C, above the 20C disruption threshold. "
                "Pre-cool now and keep airflow moving until it drops."
            ),
            severity="critical",
            data={"url": "/", "kind": "thermal", "severity": "critical"},
            context={**context, "rule": "peak_20c"},
        )

    if temp_c >= 19.5:
        return NotificationPlan(
            analysis_type=ANALYSIS_TYPE_THERMAL_ALERT,
            tag=f"thermal-peak-195-{subject_date.isoformat()}",
            title="Bedroom nearing disruption range",
            body=(
                f"Bedroom is {temp_c:.1f}C. Above 19.5C risks thermal sleep "
                "disruption, so cool it before bed."
            ),
            severity="warning",
            data={"url": "/", "kind": "thermal", "severity": "warning"},
            context={**context, "rule": "peak_19_5c"},
        )

    if time(21, 45) <= current.time() <= time(22, 15) and 17.0 <= temp_c <= 19.4:
        return NotificationPlan(
            analysis_type=ANALYSIS_TYPE_THERMAL_ALERT,
            tag=f"thermal-seal-{subject_date.isoformat()}",
            title="Seal the bedroom",
            body=f"Bedroom is {temp_c:.1f}C. Seal it now and keep the pre-bed routine steady.",
            severity="info",
            data={"url": "/", "kind": "thermal", "severity": "info"},
            context={**context, "rule": "seal_22"},
        )

    if time(19, 0) <= current.time() < time(21, 45) and temp_c > 17.5:
        return NotificationPlan(
            analysis_type=ANALYSIS_TYPE_THERMAL_ALERT,
            tag=f"thermal-precool-{subject_date.isoformat()}",
            title="Start room pre-cooling",
            body=(
                f"Bedroom is {temp_c:.1f}C. Start pre-cooling toward 17C so it "
                "is ready before the 22:00 seal."
            ),
            severity="info",
            data={"url": "/", "kind": "thermal", "severity": "info"},
            context={**context, "rule": "pre_cool_17c"},
        )

    return None


def evaluate_stale_sources(snapshot: FreshnessSnapshot) -> list[NotificationPlan]:
    alerts: list[NotificationPlan] = []
    subject_date = snapshot.local_date

    if snapshot.local_now.hour >= GARMIN_FRESHNESS_HOUR and (
        snapshot.last_garmin_recorded_at_utc is None
        or snapshot.last_garmin_recorded_at_utc.date() < subject_date
    ):
        alerts.append(
            NotificationPlan(
                analysis_type=ANALYSIS_TYPE_STALE_SOURCE_ALERT,
                tag=f"stale-garmin-{subject_date.isoformat()}",
                title="Garmin data missing",
                body=(
                    "Today's Garmin recovery data has not landed, so the coach "
                    "may be working from stale inputs."
                ),
                severity="warning",
                data={"url": "/", "kind": "stale_source", "source": "garmin"},
                context={
                    "subjectDate": subject_date.isoformat(),
                    "source": "garmin",
                    "lastRecordedAtUtc": _iso_or_none(snapshot.last_garmin_recorded_at_utc),
                },
            )
        )

    hive_age = (
        None
        if snapshot.last_hive_captured_at_utc is None
        else snapshot.now_utc.replace(tzinfo=UTC) - _as_utc(snapshot.last_hive_captured_at_utc)
    )
    if hive_age is None or hive_age > HIVE_FRESHNESS_LIMIT:
        alerts.append(
            NotificationPlan(
                analysis_type=ANALYSIS_TYPE_STALE_SOURCE_ALERT,
                tag=f"stale-hive-{subject_date.isoformat()}",
                title="Hive temperature stale",
                body=(
                    "Bedroom temperature has not updated recently, so thermal "
                    "alerts may be missing."
                ),
                severity="warning",
                data={"url": "/", "kind": "stale_source", "source": "hive"},
                context={
                    "subjectDate": subject_date.isoformat(),
                    "source": "hive",
                    "lastCapturedAtUtc": _iso_or_none(snapshot.last_hive_captured_at_utc),
                },
            )
        )

    if snapshot.latest_weather_date is None or snapshot.latest_weather_date < subject_date:
        alerts.append(
            NotificationPlan(
                analysis_type=ANALYSIS_TYPE_STALE_SOURCE_ALERT,
                tag=f"stale-weather-{subject_date.isoformat()}",
                title="Weather data missing",
                body=(
                    "Today's weather context is missing, so overnight environment "
                    "guidance may be incomplete."
                ),
                severity="warning",
                data={"url": "/", "kind": "stale_source", "source": "weather"},
                context={
                    "subjectDate": subject_date.isoformat(),
                    "source": "weather",
                    "latestWeatherDate": (
                        snapshot.latest_weather_date.isoformat()
                        if snapshot.latest_weather_date is not None
                        else None
                    ),
                },
            )
        )

    return alerts


class NudgeAlertService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def run_evening_nudge(
        self,
        profile: Profile,
        *,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> bool:
        if not is_evening_nudge_due(timezone_name=profile.timezone, now_utc=now_utc):
            return False
        now = now_utc or datetime.now(UTC)
        subject_date = local_now(profile.timezone, now_utc).date()
        plan = build_evening_nudge_plan(subject_date)
        return await self._send_once(
            profile,
            plan,
            subject_date=subject_date,
            commit=commit,
            now_utc=now,
        )

    async def run_monitoring_alerts(
        self,
        profile: Profile,
        *,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> int:
        now = now_utc or datetime.now(UTC)
        subject_date = local_now(profile.timezone, now).date()
        latest_temperature = await self._latest_temperature(profile.id)
        plans: list[NotificationPlan] = []

        thermal_plan = evaluate_thermal_alert(
            latest_temperature,
            timezone_name=profile.timezone,
            now_utc=now,
        )
        if thermal_plan is not None:
            plans.append(thermal_plan)

        freshness = await self._freshness_snapshot(profile.id, profile.timezone, now)
        plans.extend(evaluate_stale_sources(freshness))

        sent_or_recorded = 0
        for plan in plans:
            if await self._send_once(
                profile,
                plan,
                subject_date=subject_date,
                commit=False,
                now_utc=now,
            ):
                sent_or_recorded += 1

        if commit:
            await self.session.commit()
        return sent_or_recorded

    async def _send_once(
        self,
        profile: Profile,
        plan: NotificationPlan,
        *,
        subject_date: date,
        commit: bool,
        now_utc: datetime,
    ) -> bool:
        if await self._already_recorded(profile.id, plan.analysis_type, plan.tag, subject_date):
            return False

        sent = await send_notification(
            session=self.session,
            user_id=profile.id,
            title=plan.title,
            body=plan.body,
            data=plan.data,
            tag=plan.tag,
            timezone_name=profile.timezone,
            now_utc=now_utc,
        )
        self.session.add(
            Analysis(
                user_id=profile.id,
                activity_id=None,
                analysis_type=plan.analysis_type,
                subject_date=subject_date,
                generated_at_utc=datetime.now(UTC).replace(tzinfo=None),
                prompt_version=PROMPT_VERSION,
                model_name=None,
                verdict=plan.severity,
                context_packet={**plan.context, "tag": plan.tag, "sentCount": sent},
                output_markdown=plan.body,
                raw_response={"notification": {"title": plan.title, "body": plan.body}},
            )
        )
        if commit:
            await self.session.commit()
        return True

    async def _already_recorded(
        self,
        user_id: uuid.UUID,
        analysis_type: str,
        tag: str,
        subject_date: date,
    ) -> bool:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == analysis_type,
                        Analysis.subject_date == subject_date,
                    )
                    .order_by(Analysis.generated_at_utc.desc())
                )
            )
            .scalars()
            .all()
        )
        return any(row.context_packet.get("tag") == tag for row in rows)

    async def _latest_temperature(self, user_id: uuid.UUID) -> TemperatureReading | None:
        return (
            (
                await self.session.execute(
                    select(TemperatureReading)
                    .where(TemperatureReading.user_id == user_id)
                    .order_by(TemperatureReading.captured_at_utc.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def _freshness_snapshot(
        self,
        user_id: uuid.UUID,
        timezone_name: str,
        now_utc: datetime,
    ) -> FreshnessSnapshot:
        local_current = local_now(timezone_name, now_utc)
        latest_metric = (
            (
                await self.session.execute(
                    select(DailyMetric)
                    .where(DailyMetric.user_id == user_id)
                    .order_by(DailyMetric.calendar_date.desc(), DailyMetric.updated_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        latest_temperature = await self._latest_temperature(user_id)
        latest_weather = (
            (
                await self.session.execute(
                    select(WeatherDaily)
                    .where(WeatherDaily.user_id == user_id)
                    .order_by(WeatherDaily.calendar_date.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        metric_recorded_at = None
        if latest_metric is not None:
            metric_recorded_at = latest_metric.recorded_at_utc or latest_metric.updated_at
        return FreshnessSnapshot(
            local_date=local_current.date(),
            local_now=local_current,
            now_utc=now_utc.replace(tzinfo=None),
            last_garmin_recorded_at_utc=metric_recorded_at,
            last_hive_captured_at_utc=(
                latest_temperature.captured_at_utc if latest_temperature is not None else None
            ),
            latest_weather_date=(
                latest_weather.calendar_date if latest_weather is not None else None
            ),
        )


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
