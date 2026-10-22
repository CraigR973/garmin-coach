"""Decision #431: the three other bedroom readers leave the home out of a night away.

The driver correlation stopped pairing the empty bedroom at home with sleep measured
somewhere else in Decision #429. The 04:00-waking evaluation, its nightly observation
and the monthly longitudinal packet read the same ``bedroom_driver_values_by_date``
and the same forecast for home, and now take the same nights away from
``services.away_nights``. Everything here is synthetic: the repo is public.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    KnowledgeBase,
    ManualEntry,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.away_nights import HOLIDAY_WINDOWS_SECTION
from src.services.experiment_evaluation import ExperimentEvaluationService
from src.services.experiment_loop import ExperimentLoopService
from src.services.longitudinal_analysis import (
    LongitudinalAnalysisService,
    build_longitudinal_packet,
)
from src.services.notes_reader import notes_hash
from tests.test_bulk_history_reads import RecordingSession, _profile

#: Twelve wake dates in British Summer Time, 25 Sep to 6 Oct 2026.
FIRST_WAKE = date(2026, 9, 25)
WAKE_DATES = [FIRST_WAKE + timedelta(days=offset) for offset in range(12)]
#: A holiday of 3–6 Oct is three nights away, waking 4, 5 and 6 Oct (Decision #213).
HOLIDAY = {"startDate": "2026-10-03", "endDate": "2026-10-06", "resumedAtUtc": None}
HOLIDAY_NIGHTS = {date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6)}
#: A check-in read as travel last night puts one more night away.
TRAVEL_NIGHT = date(2026, 9, 29)
HOME_NIGHTS = [day for day in WAKE_DATES if day not in HOLIDAY_NIGHTS | {TRAVEL_NIGHT}]

HOME_DRIVERS = (
    "overnight_low_c",
    "bedroom_mean_temp_c",
    "bedroom_min_temp_c",
    "bedroom_max_temp_c",
    "bedroom_warning_minutes",
    "bedroom_critical_minutes",
)


def _holiday_content() -> dict[str, Any]:
    return {"windows": [HOLIDAY]}


def _sleep(user_id: uuid.UUID, wake_date: date, index: int) -> Sleep:
    return Sleep(
        user_id=user_id,
        calendar_date=wake_date,
        score=70 + index,
        duration_sec=7 * 3600,
        rem_sleep_sec=(40 + index) * 60,
        awake_sleep_sec=(20 + 3 * (index % 4)) * 60,
        avg_sleep_stress=12.0 + index % 5,
        factors_json={},
        raw_payload={},
    )


def _weather(user_id: uuid.UUID, wake_date: date, index: int) -> WeatherDaily:
    return WeatherDaily(
        user_id=user_id,
        calendar_date=wake_date,
        source="open_meteo",
        latitude=55.6045,
        longitude=-4.5249,
        overnight_low_c=8.0 + index % 3,
        overnight_wind_max_mph=10.0,
        overnight_relative_humidity_mean_pct=80.0,
        raw_payload={},
    )


def _room(user_id: uuid.UUID, wake_date: date, temperature_c: float) -> TemperatureReading:
    # 23:00 BST on the evening before the wake date: inside that night's window.
    return TemperatureReading(
        user_id=user_id,
        source="hive",
        captured_at_utc=datetime.combine(wake_date - timedelta(days=1), datetime.min.time())
        + timedelta(hours=22),
        temperature_c=temperature_c,
        raw_payload={},
    )


def _room_temperature(wake_date: date, index: int) -> float:
    # The shut, empty house runs warm through a holiday. At home the room moves across
    # the 19.5C and 20C lines, so every bedroom candidate has something to correlate.
    return 24.5 if wake_date in HOLIDAY_NIGHTS else 18.5 + 0.75 * (index % 3)


def _canned_rows(user_id: uuid.UUID) -> dict[type, list[Any]]:
    return {
        KnowledgeBase: [_holiday_content()],
        Sleep: [_sleep(user_id, day, index) for index, day in enumerate(WAKE_DATES)],
        WeatherDaily: [_weather(user_id, day, index) for index, day in enumerate(WAKE_DATES)],
        TemperatureReading: [
            _room(user_id, day, _room_temperature(day, index))
            for index, day in enumerate(WAKE_DATES)
        ],
    }


def _travel_reading_row() -> tuple[date, str, str | None, dict[str, Any]]:
    """The joined (entry date, note, its hash, reading) row the loader reads."""

    note = "Synthetic: slept at a friend's last night."
    return (
        TRAVEL_NIGHT,
        note,
        notes_hash(note),
        {"travel": {"state": "present", "when": "last_night"}},
    )


# ---------------------------------------------------------------------------
# The 04:00-waking evaluation
# ---------------------------------------------------------------------------


async def test_early_waking_evaluation_leaves_the_home_out_of_nights_away() -> None:
    profile = _profile()
    rows = _canned_rows(profile.id)
    # The evaluation reads check-ins only through the stored readings, so the joined
    # row is the one ManualEntry statement it issues.
    rows[ManualEntry] = [_travel_reading_row()]
    service = ExperimentEvaluationService(RecordingSession(rows))  # type: ignore[arg-type]

    result = await service._evaluate_early_waking(profile, end=WAKE_DATES[-1])

    samples = {row["driver"]: row["sampleCount"] for row in result.evidence["correlations"]}
    # Measured on him wherever he slept: every night stays.
    assert samples["sleep_stress_avg"] == len(WAKE_DATES)
    # The room and the forecast at home: only the eight nights he slept there.
    for driver in HOME_DRIVERS:
        assert samples.get(driver) == len(HOME_NIGHTS), driver
    assert len(HOME_NIGHTS) == 8


async def test_without_a_recorded_night_away_the_evaluation_keeps_every_night() -> None:
    profile = _profile()
    rows = _canned_rows(profile.id)
    rows[KnowledgeBase] = []
    service = ExperimentEvaluationService(RecordingSession(rows))  # type: ignore[arg-type]

    result = await service._evaluate_early_waking(profile, end=WAKE_DATES[-1])

    samples = {row["driver"]: row["sampleCount"] for row in result.evidence["correlations"]}
    assert samples["sleep_stress_avg"] == len(WAKE_DATES)
    assert samples["bedroom_mean_temp_c"] == len(WAKE_DATES)
    assert samples["overnight_low_c"] == len(WAKE_DATES)


# ---------------------------------------------------------------------------
# The nightly 04:00-waking observation
# ---------------------------------------------------------------------------


async def test_nightly_observation_records_no_home_room_or_weather_on_a_night_away() -> None:
    profile = _profile()
    home, away = date(2026, 10, 3), date(2026, 10, 4)
    session = RecordingSession(_canned_rows(profile.id))
    loop = ExperimentLoopService(session)  # type: ignore[arg-type]

    contexts = await loop._night_contexts(profile, [home, away])

    assert contexts[away]["bedroom"] is None
    assert contexts[away]["weather"] is None
    assert contexts[home]["bedroom"] is not None
    assert contexts[home]["weather"] is not None

    _, away_metrics = loop._observation("early_waking_0400", day=away, context=contexts[away])
    _, home_metrics = loop._observation("early_waking_0400", day=home, context=contexts[home])
    for field in ("bedroomMeanTempC", "bedroomMinTempC", "bedroomMaxTempC", "overnightLowC"):
        assert away_metrics[field] is None, field
        assert home_metrics[field] is not None, field
    # The night itself, measured on him, is still recorded.
    assert away_metrics["awakeMin"] is not None
    assert away_metrics["sleepStressAvg"] is not None


# ---------------------------------------------------------------------------
# The monthly longitudinal packet
# ---------------------------------------------------------------------------


async def test_longitudinal_packet_carries_no_home_room_or_weather_on_a_night_away() -> None:
    profile = _profile()
    session = RecordingSession(_canned_rows(profile.id))
    service = LongitudinalAnalysisService(session)  # type: ignore[arg-type]

    nights = await service.assemble_nights(profile, as_of_date=WAKE_DATES[-1])

    by_date = {night.calendar_date: night for night in nights}
    away = by_date[date(2026, 10, 4)]
    home = by_date[date(2026, 10, 3)]
    for field in (
        "bedroom_mean_temp_c",
        "bedroom_min_temp_c",
        "bedroom_max_temp_c",
        "bedroom_warning_min",
        "bedroom_critical_min",
        "outdoor_overnight_low_c",
        "overnight_wind_max_mph",
        "overnight_humidity_mean_pct",
    ):
        assert getattr(away, field) is None, field
        assert getattr(home, field) is not None, field
    assert away.rem_sleep_min is not None
    assert away.awake_sleep_min is not None
    assert away.sleep_score is not None

    packet = build_longitudinal_packet(nights, as_of_date=WAKE_DATES[-1])
    coverage = packet["coverage"]
    assert coverage["sleepNights"] == len(WAKE_DATES)
    # The travel night is not in this loader's canned readings, so only the holiday
    # nights leave: nine of the twelve keep their bedroom and weather.
    assert coverage["bedroomTemperatureNights"] == len(WAKE_DATES) - len(HOLIDAY_NIGHTS)
    assert coverage["weatherNights"] == len(WAKE_DATES) - len(HOLIDAY_NIGHTS)
    # None of the empty room's 24.5C nights is left in the bands.
    assert {band["lowerC"] for band in packet["temperatureBands"]} == {18.0, 19.0, 20.0}


# ---------------------------------------------------------------------------
# On PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_postgres_the_three_readers_leave_the_home_out_of_a_holiday(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name=f"Away readers {user_id.hex[:8]}",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section=HOLIDAY_WINDOWS_SECTION,
                version=1,
                is_active=True,
                content=_holiday_content(),
            )
        )
        for index, day in enumerate(WAKE_DATES):
            session.add(_sleep(user_id, day, index))
            session.add(_weather(user_id, day, index))
            session.add(_room(user_id, day, _room_temperature(day, index)))
        await session.commit()

    home, away = date(2026, 10, 3), date(2026, 10, 4)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await session.get(Profile, user_id)
        assert player is not None

        evaluation = await ExperimentEvaluationService(session)._evaluate_early_waking(
            player, end=WAKE_DATES[-1]
        )
        samples = {row["driver"]: row["sampleCount"] for row in evaluation.evidence["correlations"]}
        assert samples["sleep_stress_avg"] == len(WAKE_DATES)
        assert samples["bedroom_mean_temp_c"] == len(WAKE_DATES) - len(HOLIDAY_NIGHTS)
        assert samples["overnight_low_c"] == len(WAKE_DATES) - len(HOLIDAY_NIGHTS)

        contexts = await ExperimentLoopService(session)._night_contexts(player, [home, away])
        assert contexts[home]["bedroom"] is not None
        assert contexts[home]["weather"] is not None
        assert contexts[away]["bedroom"] is None
        assert contexts[away]["weather"] is None

        nights = await LongitudinalAnalysisService(session).assemble_nights(
            player, as_of_date=WAKE_DATES[-1]
        )
        by_date = {night.calendar_date: night for night in nights}
        assert by_date[home].bedroom_mean_temp_c == 20.0
        assert by_date[home].outdoor_overnight_low_c is not None
        assert by_date[away].bedroom_mean_temp_c is None
        assert by_date[away].outdoor_overnight_low_c is None
        assert by_date[away].awake_sleep_min is not None
