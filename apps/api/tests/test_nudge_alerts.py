from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity, Analysis, FanStateReading, TemperatureReading
from src.models.profile import Profile, UserRole
from src.services.nudge_alerts import (
    ANALYSIS_TYPE_ANALYSIS_PUSH,
    ANALYSIS_TYPE_BRIEF_READY,
    ANALYSIS_TYPE_GOOD_MORNING,
    THERMAL_URL,
    FanReconcileState,
    FreshnessSnapshot,
    NudgeAlertService,
    build_analysis_push_plan,
    build_brief_ready_plan,
    build_evening_nudge_plan,
    build_good_morning_plan,
    build_workout_checkin_plan,
    evaluate_stale_sources,
    evaluate_thermal_alert,
    is_evening_nudge_due,
)


def _analysis(
    *,
    verdict: str | None = "Amber",
    reasons: list[str] | None = None,
    activity_id: uuid.UUID | None = None,
    subject_date: date = date(2026, 7, 3),
) -> SimpleNamespace:
    """A minimal Analysis-like object for the pure push-plan builders."""
    packet: dict[str, object] = {}
    if reasons is not None:
        packet["verdict"] = {"reasons": reasons}
    return SimpleNamespace(
        verdict=verdict,
        context_packet=packet,
        activity_id=activity_id,
        subject_date=subject_date,
    )


def _temperature(value: float, captured_at: datetime) -> MagicMock:
    reading = MagicMock(spec=TemperatureReading)
    reading.id = uuid.uuid4()
    reading.user_id = uuid.uuid4()
    reading.temperature_c = value
    reading.captured_at_utc = captured_at
    return reading


def test_evening_nudge_due_uses_profile_timezone() -> None:
    assert (
        is_evening_nudge_due(
            timezone_name="Europe/London",
            now_utc=datetime(2026, 6, 20, 19, 5, tzinfo=UTC),
        )
        is True
    )
    assert (
        is_evening_nudge_due(
            timezone_name="Europe/London",
            now_utc=datetime(2026, 6, 20, 19, 30, tzinfo=UTC),
        )
        is False
    )


def test_evening_nudge_copy_contains_sleep_protocol_steps() -> None:
    plan = build_evening_nudge_plan(date(2026, 6, 20))
    assert plan.tag == "sleep-protocol-2026-06-20"
    assert "20:00 breathing" in plan.body
    assert "17C" in plan.body
    assert "21:30" in plan.body
    assert "22:00" in plan.body
    assert "23:15" in plan.body


def test_good_morning_nudge_copy_and_tag() -> None:
    """Batch 85: the wake nudge invites a check-in, is one-per-day, and deep-links
    to the check-in page (where the brief is generated)."""
    plan = build_good_morning_plan(date(2026, 7, 11))
    assert plan.analysis_type == ANALYSIS_TYPE_GOOD_MORNING
    assert plan.tag == "good-morning-2026-07-11"
    assert plan.title == "Good morning ☀️"
    assert "say good morning" in plan.body.lower()
    assert plan.data["url"] == "/check-in"


def test_brief_ready_push_plan_targets_brief_and_reuses_the_headline() -> None:
    plan = build_brief_ready_plan(
        _analysis(verdict="Green", reasons=["Training readiness is well recovered."]),
        date(2026, 7, 12),
    )
    assert plan.analysis_type == ANALYSIS_TYPE_BRIEF_READY
    assert plan.tag == "brief-ready-2026-07-12"
    assert plan.title == "Today's brief is ready"
    assert plan.body == "Training readiness is well recovered."
    assert plan.data == {"url": "/brief", "kind": "brief_ready", "status": "Green"}


def test_thermal_precool_alert_before_seal_window() -> None:
    plan = evaluate_thermal_alert(
        _temperature(18.2, datetime(2026, 6, 20, 18, 10)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 18, 15, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "pre_cool_17c"
    assert "pre-cooling" in plan.body
    assert plan.data["url"] == THERMAL_URL


def test_thermal_seal_alert_near_2200() -> None:
    plan = evaluate_thermal_alert(
        _temperature(18.1, datetime(2026, 6, 20, 20, 55)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 20, 58, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "seal_22"
    assert "Seal" in plan.title
    assert plan.data["url"] == THERMAL_URL


def test_thermal_peak_alert_uses_disruption_threshold() -> None:
    plan = evaluate_thermal_alert(
        _temperature(19.7, datetime(2026, 6, 20, 20, 0)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 20, 5, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "peak_19_5c"
    assert plan.severity == "warning"
    assert "19.5C" in plan.body
    assert plan.data["url"] == THERMAL_URL


def test_thermal_critical_alert_over_20c() -> None:
    plan = evaluate_thermal_alert(
        _temperature(20.2, datetime(2026, 6, 20, 20, 0)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 20, 5, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "peak_20c"
    assert plan.severity == "critical"
    assert plan.data["url"] == THERMAL_URL


def test_stale_source_alerts_distinguish_sources() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 19, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 18, 0),
        latest_weather_date=date(2026, 6, 19),
    )

    alerts = evaluate_stale_sources(snapshot)

    assert {alert.context["source"] for alert in alerts} == {"garmin", "hive", "weather"}
    assert {alert.title for alert in alerts} == {
        "Garmin data missing",
        "Hive temperature stale",
        "Weather data missing",
    }


def test_fresh_sources_do_not_alert() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 20, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 18, 30),
        latest_weather_date=date(2026, 6, 20),
    )

    assert evaluate_stale_sources(snapshot) == []


def test_stale_hive_threshold_is_45_minutes() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 20, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 18, 14, 59),
        latest_weather_date=date(2026, 6, 20),
    )

    alerts = evaluate_stale_sources(snapshot)

    assert [alert.context["source"] for alert in alerts] == ["hive"]


def test_recent_hive_threshold_boundary_is_fresh() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 20, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 19, 0) - timedelta(minutes=45),
        latest_weather_date=date(2026, 6, 20),
    )

    assert evaluate_stale_sources(snapshot) == []


# ---------------------------------------------------------------------------
# Batch 45 — proactive push plans
# ---------------------------------------------------------------------------


def test_analysis_push_plan_titles_per_kind() -> None:
    activity_id = uuid.uuid4()
    titles = {
        "ride": "Ride analysis ready",
        "strength": "Strength read ready",
        "flexibility": "Mobility read ready",
        "walk": "Walk read ready",
    }
    for kind, title in titles.items():
        plan = build_analysis_push_plan(_analysis(activity_id=activity_id), kind=kind)
        assert plan is not None
        assert plan.analysis_type == "analysis_push"
        assert plan.tag == f"analysis-{activity_id}"
        assert plan.title == title
        assert plan.context["activityKind"] == kind


def test_analysis_push_plan_none_for_breathwork_and_missing_activity() -> None:
    # Breathwork has no per-session analysis (#112) → no push kind registered.
    assert build_analysis_push_plan(_analysis(activity_id=uuid.uuid4()), kind="breathwork") is None
    # A date-level analysis with no activity_id can never push.
    assert build_analysis_push_plan(_analysis(activity_id=None), kind="ride") is None


def test_workout_checkin_plan_invites_input_before_the_read() -> None:
    activity = MagicMock(spec=Activity)
    activity.id = uuid.uuid4()

    plan = build_workout_checkin_plan(activity, kind="strength")

    assert plan is not None
    assert plan.title == "How did it feel?"
    assert plan.tag == f"workout-check-in-{activity.id}"
    assert plan.data["url"] == f"/#post-workout-{activity.id}"
    assert plan.context["activityKind"] == "strength"


# ---------------------------------------------------------------------------
# Batch 45 — fan-reconciled thermal nudges
# ---------------------------------------------------------------------------


def test_thermal_suppressed_when_autopilot_is_handling_the_room() -> None:
    # Warm room, but the fan applied/holds → the manual nudge is redundant.
    for action in ("apply", "hold", "winddown"):
        plan = evaluate_thermal_alert(
            _temperature(19.8, datetime(2026, 6, 20, 22, 30)),
            timezone_name="Europe/London",
            now_utc=datetime(2026, 6, 20, 22, 35, tzinfo=UTC),
            fan=FanReconcileState(auto_enabled=True, latest_action=action),
        )
        assert plan is None, action


def test_thermal_escalates_when_fan_unreachable_or_no_data() -> None:
    for action, reason in (("unreachable", "not responding"), ("no_data", "no room reading")):
        plan = evaluate_thermal_alert(
            _temperature(19.8, datetime(2026, 6, 20, 22, 30)),
            timezone_name="Europe/London",
            now_utc=datetime(2026, 6, 20, 22, 35, tzinfo=UTC),
            fan=FanReconcileState(auto_enabled=True, latest_action=action),
        )
        assert plan is not None, action
        assert plan.context["rule"] == "fan_cant_cope"
        assert plan.context["fanAction"] == action
        assert plan.severity == "critical"
        assert plan.data["url"] == THERMAL_URL
        assert reason in plan.body


def test_thermal_escalates_when_room_critical_and_fan_maxed() -> None:
    plan = evaluate_thermal_alert(
        _temperature(20.4, datetime(2026, 6, 20, 23, 0)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 23, 5, tzinfo=UTC),
        fan=FanReconcileState(auto_enabled=True, latest_action="hold", fan_at_max=True),
    )
    assert plan is not None
    assert plan.context["rule"] == "fan_cant_cope"
    assert "full speed" in plan.body


def test_thermal_silent_when_room_comfortable_under_autopilot() -> None:
    plan = evaluate_thermal_alert(
        _temperature(18.9, datetime(2026, 6, 20, 22, 30)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 22, 35, tzinfo=UTC),
        fan=FanReconcileState(auto_enabled=True, latest_action="unreachable"),
    )
    assert plan is None


def test_thermal_manual_nudge_unchanged_when_autopilot_off() -> None:
    # A disabled autopilot keeps the pre-Batch-45 manual protocol nudge.
    plan = evaluate_thermal_alert(
        _temperature(19.7, datetime(2026, 6, 20, 20, 0)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 20, 5, tzinfo=UTC),
        fan=FanReconcileState(auto_enabled=False),
    )
    assert plan is not None
    assert plan.context["rule"] == "peak_19_5c"


@pytest.mark.asyncio
async def test_monitoring_can_skip_thermal_while_still_checking_source_freshness() -> None:
    session = AsyncMock()
    profile = MagicMock(spec=Profile)
    profile.id = uuid.uuid4()
    profile.timezone = "Europe/London"
    now = datetime(2026, 7, 12, 19, 45, tzinfo=UTC)
    service = NudgeAlertService(session)
    service._latest_temperature = AsyncMock()  # type: ignore[method-assign]
    service._fan_reconcile_state = AsyncMock()  # type: ignore[method-assign]
    service._freshness_snapshot = AsyncMock(  # type: ignore[method-assign]
        return_value=FreshnessSnapshot(
            local_date=date(2026, 7, 12),
            local_now=datetime(2026, 7, 12, 20, 45),
            now_utc=now,
            last_garmin_recorded_at_utc=now,
            last_hive_captured_at_utc=now,
            latest_weather_date=date(2026, 7, 12),
        )
    )

    recorded = await service.run_monitoring_alerts(
        profile,
        now_utc=now,
        commit=False,
        include_thermal=False,
    )

    assert recorded == 0
    service._latest_temperature.assert_not_awaited()
    service._fan_reconcile_state.assert_not_awaited()
    service._freshness_snapshot.assert_awaited_once_with(profile.id, profile.timezone, now)


# ---------------------------------------------------------------------------
# Batch 45 — push idempotency + quiet-hours audit (DB-backed; CI Postgres)
# ---------------------------------------------------------------------------


async def _seed_profile(session: object, *, fan_auto_enabled: bool = False) -> Profile:
    user_id = uuid.uuid4()
    profile = Profile(
        id=user_id,
        display_name=f"Push Test {user_id.hex[:6]}",
        pin_hash="x" * 60,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
        fan_auto_enabled=fan_auto_enabled,
    )
    session.add(profile)  # type: ignore[attr-defined]
    await session.flush()  # type: ignore[attr-defined]
    return profile


@pytest.mark.asyncio
async def test_brief_ready_pushes_exactly_once(db_conn: AsyncConnection) -> None:
    """The brief-ready push fires once; the backstop/regeneration re-run never re-pushes.

    Batch 112 converged the 09:30 backstop onto this same method, so this also
    covers the backstop-after-check-in case: whichever call lands first wins and
    the other is a no-op, giving Mark exactly one "brief ready" notification.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        profile = await _seed_profile(session)
        subject_date = date(2026, 7, 3)
        analysis = Analysis(
            user_id=profile.id,
            activity_id=None,
            analysis_type="morning_analysis",
            subject_date=subject_date,
            generated_at_utc=datetime(2026, 7, 3, 7, 0),
            prompt_version="test",
            verdict="Amber",
            context_packet={"verdict": {"reasons": ["Age-adjusted sleep is below 74."]}},
            output_markdown="**Verdict:** Amber",
            raw_response={},
        )
        session.add(analysis)
        await session.flush()

        service = NudgeAlertService(session)
        first = await service.push_brief_ready(
            profile, analysis, subject_date=subject_date, commit=False
        )
        second = await service.push_brief_ready(
            profile, analysis, subject_date=subject_date, commit=False
        )
        assert first is True
        assert second is False

        count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(
                Analysis.user_id == profile.id,
                Analysis.analysis_type == ANALYSIS_TYPE_BRIEF_READY,
            )
        )
        assert count == 1


@pytest.mark.asyncio
async def test_workout_analysis_pushes_once_per_activity(db_conn: AsyncConnection) -> None:
    """A post-workout push is idempotent per activity_id across regeneration."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        profile = await _seed_profile(session)
        activity = Activity(
            user_id=profile.id,
            garmin_activity_id=987654,
            activity_name="East Ayrshire ride",
            activity_type="road_biking",
            start_utc=datetime(2026, 7, 3, 7, 30),
            duration_sec=3600,
            exclude_from_recovery=False,
            raw_summary={"activityType": {"typeKey": "road_biking"}},
        )
        session.add(activity)
        await session.flush()
        activity_id = activity.id
        analysis = Analysis(
            user_id=profile.id,
            activity_id=activity_id,
            analysis_type="post_workout",
            subject_date=date(2026, 7, 3),
            generated_at_utc=datetime(2026, 7, 3, 12, 0),
            prompt_version="test",
            verdict="advisory",
            context_packet={},
            output_markdown="**Ride analysis:** ok",
            raw_response={},
        )
        session.add(analysis)
        await session.flush()

        service = NudgeAlertService(session)
        first = await service.push_workout_analysis(profile, analysis, kind="ride", commit=False)
        # Simulate a regeneration on a newer check-in: a fresh analysis row, same activity.
        regenerated = Analysis(
            user_id=profile.id,
            activity_id=activity_id,
            analysis_type="post_workout",
            subject_date=date(2026, 7, 3),
            generated_at_utc=datetime(2026, 7, 3, 13, 0),
            prompt_version="test",
            verdict="advisory",
            context_packet={},
            output_markdown="**Ride analysis:** updated",
            raw_response={},
        )
        session.add(regenerated)
        await session.flush()
        second = await service.push_workout_analysis(
            profile, regenerated, kind="ride", commit=False
        )
        assert first is True
        assert second is False

        count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(
                Analysis.user_id == profile.id,
                Analysis.analysis_type == ANALYSIS_TYPE_ANALYSIS_PUSH,
            )
        )
        assert count == 1

        # Breathwork has no per-session analysis → nothing pushed, no audit row.
        assert (
            await service.push_workout_analysis(profile, analysis, kind="breathwork", commit=False)
            is False
        )


@pytest.mark.asyncio
async def test_fan_reconcile_state_reads_latest_tick(db_conn: AsyncConnection) -> None:
    """The reconcile state reflects fan_auto_enabled + the latest fan tick."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        profile = await _seed_profile(session, fan_auto_enabled=True)
        session.add_all(
            [
                FanStateReading(
                    user_id=profile.id,
                    captured_at_utc=datetime(2026, 7, 3, 22, 0),
                    phase="control",
                    auto_enabled=True,
                    observed_temp_c=None,
                    fan_on=None,
                    fan_speed=None,
                    action="no_data",
                    reason="no fresh temp",
                ),
                FanStateReading(
                    user_id=profile.id,
                    captured_at_utc=datetime(2026, 7, 3, 22, 15),
                    phase="control",
                    auto_enabled=True,
                    observed_temp_c=20.5,
                    fan_on=True,
                    fan_speed=7,
                    action="hold",
                    reason="at target",
                ),
            ]
        )
        await session.flush()

        service = NudgeAlertService(session)
        state = await service._fan_reconcile_state(profile)
        assert state == FanReconcileState(auto_enabled=True, latest_action="hold", fan_at_max=True)

        # A profile with the autopilot off never reads the fan series.
        off_profile = await _seed_profile(session, fan_auto_enabled=False)
        off_state = await service._fan_reconcile_state(off_profile)
        assert off_state == FanReconcileState(auto_enabled=False)
