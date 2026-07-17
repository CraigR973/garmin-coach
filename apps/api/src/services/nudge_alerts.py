"""Evening nudges, thermal monitoring, and source freshness alerts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    FanStateReading,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.environment_freshness import HIVE_FRESHNESS_LIMIT, is_hive_temperature_fresh
from src.services.fan_control import MAX_SPEED, ON_THRESHOLD_C
from src.services.push_notification_service import send_notification

ANALYSIS_TYPE_EVENING_NUDGE = "evening_nudge"
ANALYSIS_TYPE_THERMAL_ALERT = "thermal_alert"
ANALYSIS_TYPE_STALE_SOURCE_ALERT = "stale_source_alert"
ANALYSIS_TYPE_BRIEF_READY = "brief_ready_push"
ANALYSIS_TYPE_ANALYSIS_PUSH = "analysis_push"
ANALYSIS_TYPE_GOOD_MORNING = "good_morning_nudge"
ANALYSIS_TYPE_WORKOUT_CHECKIN = "workout_checkin_nudge"
PROMPT_VERSION = "notification-rules:v1"

EVENING_NUDGE_TIME = time(20, 0)
EVENING_NUDGE_WINDOW_MIN = 20
GARMIN_FRESHNESS_HOUR = 8

# Bedroom disruption ceiling (Batch 9 / Batch 27; matches the fan speed ladder's
# 20.0 C step). Above this the fan runs at max, so "still warm here" is the signal
# that airflow alone cannot cope.
THERMAL_CRITICAL_C = 20.0

# Batch 112: the one deep-link every thermal severity points at (the `/bedroom`
# route is redirect-only — see App.tsx — so alerts must target its destination
# directly rather than bouncing through it).
THERMAL_URL = "/environment"

# Batch 45 — reconcile the evening thermal nudges with the Batch 27 fan autopilot.
# When the loop's latest tick is one of these, the fan is managing the room, so the
# manual "you pre-cool / seal it" nudges are suppressed.
FAN_HANDLING_ACTIONS = frozenset({"apply", "hold", "winddown"})
# When the latest tick is one of these, the autopilot could not act (cloud down /
# no fresh temperature), so a manual "check the fan" ask is warranted.
FAN_CANT_COPE_ACTIONS = frozenset({"unreachable", "no_data"})

# Post-workout push titles by activity kind (breathwork has no per-session
# analysis — DECISIONS #112 — so it is deliberately absent).
ANALYSIS_PUSH_TITLES: dict[str, str] = {
    "ride": "Ride analysis ready",
    "strength": "Strength read ready",
    "flexibility": "Mobility read ready",
    "walk": "Walk read ready",
}


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


@dataclass(frozen=True)
class FanReconcileState:
    """The Batch 27 fan autopilot's state, as seen by the evening thermal nudge.

    ``auto_enabled`` is ``Profile.fan_auto_enabled``; ``latest_action`` is the most
    recent ``fan_state_readings.action`` (``None`` when the loop has not written a
    tick yet); ``fan_at_max`` is ``True`` only when that tick has the fan on at
    :data:`~src.services.fan_control.MAX_SPEED`. The default is "autopilot off",
    which preserves the pre-Batch-45 manual-nudge behaviour.
    """

    auto_enabled: bool = False
    latest_action: str | None = None
    fan_at_max: bool = False


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


def _verdict_headline(analysis: Analysis) -> str | None:
    """The verdict's first reason, used as the push's one-line headline."""
    packet = analysis.context_packet
    verdict = packet.get("verdict") if isinstance(packet, dict) else None
    if not isinstance(verdict, dict):
        return None
    reasons = verdict.get("reasons")
    if isinstance(reasons, list) and reasons and isinstance(reasons[0], str):
        return reasons[0]
    return None


def build_good_morning_plan(subject_date: date) -> NotificationPlan:
    """The wake "good morning" nudge (Batch 85).

    Fired once per day after the overnight sync completes, inviting Mark to open
    the app and check in to generate today's brief. On the primary path it
    *replaces* the auto brief-ready push — generation now happens on his check-in,
    so tap-time is always post-sync and fast. The brief-ready push survives only
    as the 11:00 backstop for a morning he never engages with (Decision #158/#217),
    and Batch 112 converged the backstop onto the same `/brief` notification so
    there is exactly one "your brief is ready" push regardless of which path
    generated it.
    """
    return NotificationPlan(
        analysis_type=ANALYSIS_TYPE_GOOD_MORNING,
        tag=f"good-morning-{subject_date.isoformat()}",
        title="Good morning ☀️",
        body="Your overnight data's in — say good morning and I'll read your day.",
        severity="info",
        data={"url": "/check-in", "kind": "good_morning"},
        context={"subjectDate": subject_date.isoformat(), "rule": "good_morning"},
    )


def build_brief_ready_plan(analysis: Analysis, subject_date: date) -> NotificationPlan:
    """A one-per-day push announcing that today's brief is ready (Batch 97)."""
    status = (analysis.verdict or "").strip()
    body = _verdict_headline(analysis) or "Your morning brief is ready — tap to read it."
    return NotificationPlan(
        analysis_type=ANALYSIS_TYPE_BRIEF_READY,
        tag=f"brief-ready-{subject_date.isoformat()}",
        title="Today's brief is ready",
        body=body,
        severity=status.lower() if status else "info",
        data={"url": "/brief", "kind": "brief_ready", "status": status},
        context={
            "subjectDate": subject_date.isoformat(),
            "status": status,
            "rule": "brief_ready",
        },
    )


def build_analysis_push_plan(analysis: Analysis, *, kind: str) -> NotificationPlan | None:
    """A one-per-activity push announcing a fresh post-workout read (Batch 45).

    Returns ``None`` for an unknown kind or an analysis with no ``activity_id`` (so
    breathwork, which has no per-session analysis, can never produce one).
    """
    title = ANALYSIS_PUSH_TITLES.get(kind)
    if title is None or analysis.activity_id is None:
        return None
    return NotificationPlan(
        analysis_type=ANALYSIS_TYPE_ANALYSIS_PUSH,
        tag=f"analysis-{analysis.activity_id}",
        title=title,
        body="Your post-workout analysis is ready — tap to read it.",
        severity="info",
        data={"url": "/", "kind": "analysis_push", "activityKind": kind},
        context={
            "subjectDate": analysis.subject_date.isoformat(),
            "activityId": str(analysis.activity_id),
            "activityKind": kind,
            "rule": "analysis_push",
        },
    )


def build_workout_checkin_plan(activity: Activity, *, kind: str) -> NotificationPlan | None:
    """Invite the activity-linked check-in before generating its read (Batch 87)."""

    label = {
        "ride": "ride",
        "strength": "strength session",
        "flexibility": "mobility session",
        "walk": "walk",
    }.get(kind)
    if label is None:
        return None
    return NotificationPlan(
        analysis_type=ANALYSIS_TYPE_WORKOUT_CHECKIN,
        tag=f"workout-check-in-{activity.id}",
        title="How did it feel?",
        body=f"Your {label} is synced — check in and I'll read it.",
        severity="info",
        data={
            "url": f"/#post-workout-{activity.id}",
            "kind": "workout_checkin",
            "activityKind": kind,
        },
        context={
            "activityId": str(activity.id),
            "activityKind": kind,
            "rule": "workout_checkin",
        },
    )


def evaluate_thermal_alert(
    reading: TemperatureReading | None,
    *,
    timezone_name: str,
    now_utc: datetime | None = None,
    fan: FanReconcileState | None = None,
) -> NotificationPlan | None:
    if reading is None:
        return None

    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    captured = reading.captured_at_utc
    captured_aware = captured.replace(tzinfo=UTC) if captured.tzinfo is None else captured
    if not is_hive_temperature_fresh(captured_aware, now_utc=now):
        return None

    current = local_now(timezone_name, now)
    temp_c = round(float(reading.temperature_c), 1)
    subject_date = current.date()
    context = {
        "subjectDate": subject_date.isoformat(),
        "temperatureC": temp_c,
        "capturedAtUtc": captured_aware.replace(tzinfo=None).isoformat(),
    }

    # Batch 45: when the fan autopilot is armed it manages the room overnight, so
    # the manual pre-cool/seal nudges below are redundant — defer to the fan and
    # only escalate a "check the fan" ask when it demonstrably cannot cope.
    if fan is not None and fan.auto_enabled:
        return _fan_reconciled_thermal_alert(temp_c, subject_date, context, fan)

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
            data={"url": THERMAL_URL, "kind": "thermal", "severity": "critical"},
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
            data={"url": THERMAL_URL, "kind": "thermal", "severity": "warning"},
            context={**context, "rule": "peak_19_5c"},
        )

    if time(21, 45) <= current.time() <= time(22, 15) and 17.0 <= temp_c <= 19.4:
        return NotificationPlan(
            analysis_type=ANALYSIS_TYPE_THERMAL_ALERT,
            tag=f"thermal-seal-{subject_date.isoformat()}",
            title="Seal the bedroom",
            body=f"Bedroom is {temp_c:.1f}C. Seal it now and keep the pre-bed routine steady.",
            severity="info",
            data={"url": THERMAL_URL, "kind": "thermal", "severity": "info"},
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
            data={"url": THERMAL_URL, "kind": "thermal", "severity": "info"},
            context={**context, "rule": "pre_cool_17c"},
        )

    return None


def _fan_reconciled_thermal_alert(
    temp_c: float,
    subject_date: date,
    context: dict[str, object],
    fan: FanReconcileState,
) -> NotificationPlan | None:
    """Thermal alert when the fan autopilot is armed (Batch 45).

    The Batch 27 loop drives airflow overnight, so the manual pre-cool/seal nudges
    are suppressed. A single "check the fan" push is escalated only while the room
    is warm enough to matter *and* the fan cannot cope — the cloud is down, it has
    no fresh reading, or it is already at max and the room is still critical.
    """
    if temp_c < ON_THRESHOLD_C:
        # Comfortable room — nothing for Mark to act on, fan or not.
        return None

    if fan.latest_action in FAN_CANT_COPE_ACTIONS:
        reason = (
            "the fan is not responding"
            if fan.latest_action == "unreachable"
            else "the fan has no room reading"
        )
    elif temp_c >= THERMAL_CRITICAL_C and fan.fan_at_max:
        reason = "the fan is at full speed but the room is still warm"
    else:
        # The fan is handling the warm room — stay quiet.
        return None

    return NotificationPlan(
        analysis_type=ANALYSIS_TYPE_THERMAL_ALERT,
        tag=f"thermal-fan-check-{subject_date.isoformat()}",
        title="Check the bedroom fan",
        body=f"Bedroom is {temp_c:.1f}C and {reason}. Go check the bedroom fan.",
        severity="critical",
        data={"url": THERMAL_URL, "kind": "thermal", "severity": "critical"},
        context={**context, "rule": "fan_cant_cope", "fanAction": fan.latest_action},
    )


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

    async def push_good_morning(
        self,
        profile: Profile,
        *,
        subject_date: date,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> bool:
        """Push the wake "good morning" nudge once (Batch 85).

        Idempotent per (profile, subject_date) via the ``good-morning-{date}`` tag,
        so re-firing on a later wake poll (or the backstop) never double-nudges.
        """
        plan = build_good_morning_plan(subject_date)
        return await self._send_once(
            profile,
            plan,
            subject_date=subject_date,
            commit=commit,
            now_utc=now_utc or datetime.now(UTC),
        )

    async def push_brief_ready(
        self,
        profile: Profile,
        analysis: Analysis,
        *,
        subject_date: date,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> bool:
        """Push today's ready brief once (Batch 97).

        Idempotent per (profile, subject_date) via the ``brief-ready-{date}``
        tag, so a regeneration or retry can never double-notify — including the
        11:00 backstop (Batch 112), which now calls this same method instead of
        a separate verdict push, so whichever path (check-in or backstop)
        generates the brief first is the one that sends the notification.
        """
        plan = build_brief_ready_plan(analysis, subject_date)
        return await self._send_once(
            profile,
            plan,
            subject_date=subject_date,
            commit=commit,
            now_utc=now_utc or datetime.now(UTC),
        )

    async def push_workout_analysis(
        self,
        profile: Profile,
        analysis: Analysis,
        *,
        kind: str,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> bool:
        """Push a fresh post-workout read once per activity (Batch 45).

        Idempotent per ``activity_id`` via the ``analysis-{id}`` tag, so a
        regeneration on a newer check-in or a ``PROMPT_VERSION`` bump does not
        re-push. Returns ``False`` for a kind with no push (e.g. breathwork).
        """
        plan = build_analysis_push_plan(analysis, kind=kind)
        if plan is None:
            return False
        return await self._send_once(
            profile,
            plan,
            subject_date=analysis.subject_date,
            commit=commit,
            now_utc=now_utc or datetime.now(UTC),
        )

    async def push_workout_checkin(
        self,
        profile: Profile,
        activity: Activity,
        *,
        kind: str,
        subject_date: date,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> bool:
        """Push one check-in invitation per synced activity (Batch 87)."""

        plan = build_workout_checkin_plan(activity, kind=kind)
        if plan is None:
            return False
        return await self._send_once(
            profile,
            plan,
            subject_date=subject_date,
            commit=commit,
            now_utc=now_utc or datetime.now(UTC),
        )

    async def run_monitoring_alerts(
        self,
        profile: Profile,
        *,
        now_utc: datetime | None = None,
        commit: bool = True,
        include_thermal: bool = True,
    ) -> int:
        now = now_utc or datetime.now(UTC)
        subject_date = local_now(profile.timezone, now).date()
        plans: list[NotificationPlan] = []

        if include_thermal:
            latest_temperature = await self._latest_temperature(profile.id)
            fan = await self._fan_reconcile_state(profile)
            thermal_plan = evaluate_thermal_alert(
                latest_temperature,
                timezone_name=profile.timezone,
                now_utc=now,
                fan=fan,
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

    async def _fan_reconcile_state(self, profile: Profile) -> FanReconcileState:
        """Read the Batch 27 autopilot's state for the thermal-nudge reconciliation."""
        if not getattr(profile, "fan_auto_enabled", False):
            return FanReconcileState(auto_enabled=False)
        latest = await self._latest_fan_state(profile.id)
        if latest is None:
            return FanReconcileState(auto_enabled=True)
        fan_at_max = (
            bool(latest.fan_on) and latest.fan_speed is not None and latest.fan_speed >= MAX_SPEED
        )
        return FanReconcileState(
            auto_enabled=True,
            latest_action=latest.action,
            fan_at_max=fan_at_max,
        )

    async def _latest_fan_state(self, user_id: uuid.UUID) -> FanStateReading | None:
        return (
            (
                await self.session.execute(
                    select(FanStateReading)
                    .where(FanStateReading.user_id == user_id)
                    .order_by(FanStateReading.captured_at_utc.desc())
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
