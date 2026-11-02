"""Batch 366 — one honest bedroom push.

7–31 Oct 2026: 42 bedroom pushes in 25 days, graded `critical` on 13 evenings, 11 of them
from the 19:00–19:30 reading; while he slept the room averaged 20 °C or more on 1 of those
nights (HS361-01). "Start pre-cooling toward 17C" went out 8 times, below WHO's 18 °C
minimum. Settings offered only all or nothing (UX362-02), and the bedroom link shown to
him was the best of about 40 uncorrected scans, with no link in the season the alerts
fire (ST363-01).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, Analysis, TemperatureReading
from src.models.notification import NotificationPreferences
from src.models.profile import Profile, UserRole
from src.services.driver_levers import select_levers
from src.services.insights import (
    CALENDAR_DAY_KEY,
    LEVER_SCANS,
    OUTCOME_SLEEP_SCORE,
    compute_drivers,
    interval_z,
)
from src.services.nudge_alerts import (
    ANALYSIS_TYPE_THERMAL_ALERT,
    ANALYSIS_TYPE_WORKOUT_CHECKIN,
    PUSH_KIND_BY_TYPE,
    THERMAL_COLD_BODY,
    THERMAL_COLD_TITLE,
    THERMAL_WARM_BODY,
    THERMAL_WARM_TITLE,
    FreshnessSnapshot,
    NudgeAlertService,
    evaluate_thermal_alert,
)
from src.services.push_notification_service import (
    PUSH_KIND_BEDROOM,
    PUSH_KIND_READS,
    PUSH_KIND_REVIEWS,
    PUSH_KINDS,
    kind_enabled,
)

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-11-02-batch-366-wording.md"


def _reading(value: float, captured: datetime) -> TemperatureReading:
    reading = MagicMock(spec=TemperatureReading)
    reading.temperature_c = value
    reading.captured_at_utc = captured
    return reading


# -- 366.1: one evening's bedroom, judged from 21:30 ------------------------------------------

#: An October evening as it was: 20.5 °C at 19:00, falling through the night window.
OCT_EVENING = [(19, 0, 20.5), (19, 30, 20.3), (20, 0, 20.1), (21, 30, 19.6), (21, 45, 19.4),
               (22, 0, 19.2), (22, 30, 19.0), (22, 45, 18.9)]  # fmt: skip


def test_a_warm_october_evening_sends_nothing() -> None:
    # London is on GMT after 25 Oct, so local and UTC agree.
    plans = [
        evaluate_thermal_alert(
            _reading(temp, datetime(2026, 10, 31, hour, minute)),
            timezone_name="Europe/London",
            now_utc=datetime(2026, 10, 31, hour, minute, 2, tzinfo=UTC),
        )
        for hour, minute, temp in OCT_EVENING
    ]
    assert plans == [None] * len(OCT_EVENING)


@pytest.mark.asyncio
async def test_one_bedroom_push_an_evening_whatever_its_kind() -> None:
    profile = MagicMock(spec=Profile)
    profile.id = uuid.uuid4()
    profile.timezone = "Europe/London"
    now = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)
    service = NudgeAlertService(AsyncMock())
    service._latest_temperature = AsyncMock(  # type: ignore[method-assign]
        return_value=_reading(17.2, datetime(2026, 11, 2, 21, 58))
    )
    service._fan_reconcile_state = AsyncMock()  # type: ignore[method-assign]
    service._freshness_snapshot = AsyncMock(  # type: ignore[method-assign]
        return_value=FreshnessSnapshot(
            local_date=date(2026, 11, 2),
            local_now=datetime(2026, 11, 2, 22, 0),
            now_utc=now,
            last_garmin_recorded_at_utc=now,
            last_hive_captured_at_utc=now,
            latest_weather_date=date(2026, 11, 2),
        )
    )
    sent: list[str] = []

    async def _send_once(_profile: Profile, plan: object, **_: object) -> bool:
        sent.append(plan.analysis_type)  # type: ignore[attr-defined]
        return True

    service._send_once = _send_once  # type: ignore[method-assign]
    service._any_recorded = AsyncMock(return_value=True)  # type: ignore[method-assign]
    await service.run_monitoring_alerts(profile, now_utc=now, commit=False)
    assert sent == []
    service._any_recorded = AsyncMock(return_value=False)  # type: ignore[method-assign]
    await service.run_monitoring_alerts(profile, now_utc=now, commit=False)
    assert sent == [ANALYSIS_TYPE_THERMAL_ALERT]


@pytest.mark.asyncio
async def test_any_recorded_reads_the_day_not_the_tag(db_conn: AsyncConnection) -> None:
    session = AsyncSession(bind=db_conn, join_transaction_mode="create_savepoint")
    profile = Profile(display_name=f"b366-{uuid.uuid4()}", role=UserRole.admin)
    session.add(profile)
    await session.flush()
    session.add(
        Analysis(
            user_id=profile.id,
            analysis_type=ANALYSIS_TYPE_THERMAL_ALERT,
            subject_date=date(2026, 11, 2),
            generated_at_utc=datetime(2026, 11, 2, 21, 30),
            prompt_version="notification-rules:v4",
            verdict="info",
            context_packet={"tag": "thermal-cold-2026-11-02"},
            output_markdown="",
            raw_response={},
        )
    )
    await session.flush()
    service = NudgeAlertService(session)
    assert await service._any_recorded(profile.id, ANALYSIS_TYPE_THERMAL_ALERT, date(2026, 11, 2))
    assert not await service._any_recorded(
        profile.id, ANALYSIS_TYPE_THERMAL_ALERT, date(2026, 11, 3)
    )


# -- 366.3: one ride check-in a day; a switch per kind ----------------------------------------


def _activity(minutes: float) -> Activity:
    activity = MagicMock(spec=Activity)
    activity.id = uuid.uuid4()
    activity.duration_sec = minutes * 60
    return activity


@pytest.mark.asyncio
async def test_one_check_in_push_a_day_and_none_for_a_short_session() -> None:
    profile = MagicMock(spec=Profile)
    profile.id = uuid.uuid4()
    service = NudgeAlertService(AsyncMock())
    service._send_once = AsyncMock(return_value=True)  # type: ignore[method-assign]
    service._any_recorded = AsyncMock(return_value=False)  # type: ignore[method-assign]
    day = date(2026, 11, 1)
    # 1 Nov: a 12-minute circuit and a 17-minute walk synced before the ride.
    assert not await service.push_workout_checkin(
        profile, _activity(12), kind="strength", subject_date=day
    )
    assert not await service.push_workout_checkin(
        profile, _activity(17), kind="walk", subject_date=day
    )
    assert await service.push_workout_checkin(profile, _activity(15), kind="ride", subject_date=day)
    service._any_recorded = AsyncMock(return_value=True)  # type: ignore[method-assign]
    assert not await service.push_workout_checkin(
        profile, _activity(45), kind="strength", subject_date=day
    )
    service._any_recorded.assert_awaited_with(profile.id, ANALYSIS_TYPE_WORKOUT_CHECKIN, day)


def test_each_switch_silences_only_its_own_kind() -> None:
    prefs = NotificationPreferences(push_reads=True, push_bedroom=False, push_reviews=True)
    assert not kind_enabled(prefs, PUSH_KIND_BEDROOM)
    assert kind_enabled(prefs, PUSH_KIND_READS)
    assert kind_enabled(prefs, PUSH_KIND_REVIEWS)
    # Missing-data alerts answer to no switch.
    assert kind_enabled(prefs, None)
    assert set(PUSH_KIND_BY_TYPE.values()) == set(PUSH_KINDS)
    assert "stale_source_alert" not in PUSH_KIND_BY_TYPE


# -- 366.4: the lever after a multiplicity allowance and within a season ----------------------


def _records(summer_r: float, autumn_r: float, *, seed: int = 7) -> list[dict[str, float | None]]:
    """112 home nights: 52 summer nights with one link, then 60 autumn nights with another."""

    rng = random.Random(seed)
    start = date(2026, 6, 25)
    rows: list[dict[str, float | None]] = []
    for night in range(112):
        r = summer_r if night < 52 else autumn_r
        temp = rng.gauss(0, 1)
        score = r * temp + (1 - r * r) ** 0.5 * rng.gauss(0, 1)
        rows.append(
            {
                "bedroom_mean_temp_c": 19 + temp,
                OUTCOME_SLEEP_SCORE: 75 + 8 * score,
                CALENDAR_DAY_KEY: float((start + timedelta(days=night)).toordinal()),
            }
        )
    return rows


def _levers(records: list[dict[str, float | None]]) -> list[object]:
    outcomes = {
        OUTCOME_SLEEP_SCORE: compute_drivers(
            records,
            outcome_key=OUTCOME_SLEEP_SCORE,
            driver_keys=("bedroom_mean_temp_c",),
            scans=LEVER_SCANS,
        )
    }
    return list(select_levers("sleep_score", outcomes))


def test_the_allowance_widens_the_interval() -> None:
    assert interval_z(1) == 1.96
    assert interval_z(LEVER_SCANS) > 3.0


def test_a_summer_only_link_is_silent_in_the_autumn() -> None:
    # Strong in the summer, nothing in the latest 60 nights: ST363-01's shape.
    assert _levers(_records(-0.6, 0.0)) == []


def test_a_link_that_holds_all_year_is_still_named() -> None:
    levers = _levers(_records(-0.6, -0.6))
    assert [lever.correlation.driver for lever in levers] == ["bedroom_mean_temp_c"]  # type: ignore[attr-defined]


# -- 366.5: the words ---------------------------------------------------------------------------


def test_every_new_line_is_in_the_draft() -> None:
    draft = " ".join(DRAFT.read_text(encoding="utf-8").replace("\n> ", " ").split())
    for words in (
        THERMAL_WARM_TITLE,
        THERMAL_WARM_BODY.format(temp=24.6),
        THERMAL_COLD_TITLE,
        THERMAL_COLD_BODY.format(temp=17.2),
        "Keep the bedroom between 18 and 24 °C.",
    ):
        assert " ".join(words.split()) in draft, words
