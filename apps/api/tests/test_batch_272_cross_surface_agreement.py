"""Batch 272 — the app catches itself contradicting itself, before Mark does.

For two weeks in September 2026 the weekly review said Mark's bedroom peaked about
2 °C warmer every night than the morning brief had said, from the same readings.
The per-night figures below are his, read from production for Batch 268
(``tests.test_night_thermal.PRODUCTION_NIGHTS``): ``old_rule_peak`` is what the review
and Trends computed before 268, ``sleep_window_peak`` is what the brief showed. The
stored review packets agree with the old column to the decimal: 7-13 Sep stated
``avgIndoorPeakC`` 20.9 and 14-20 Sep 20.5.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import (
    KnowledgeBase,
    Sleep,
    TemperatureReading,
)
from src.models.profile import Profile, UserRole
from src.services import cross_surface_agreement, reviews
from src.services.cross_surface_agreement import (
    AGREEMENT_PAIRS,
    CROSS_SURFACE_AGREEMENT_RULE,
    DEFERRED_PAIRS,
    PAIR_BEDROOM_PEAK,
    AgreementCheck,
    AgreementPair,
    Derivation,
    alert_disagreements,
    brief_night_peaks,
    evaluate_agreement,
    morning_bedroom_check,
    period_bedroom_check,
)
from src.services.morning_analysis import PROMPT_VERSION as MORNING_PROMPT_VERSION
from src.services.morning_analysis import SYSTEM_PROMPT as MORNING_SYSTEM_PROMPT
from src.services.morning_analysis import MorningAnalysisService
from src.services.night_thermal import night_indoor_peaks
from src.services.reviews import PERIOD_WEEKLY, ReviewService
from src.services.reviews import PROMPT_VERSION as REVIEW_PROMPT_VERSION
from src.services.reviews import SYSTEM_PROMPT as REVIEW_SYSTEM_PROMPT
from src.services.trends import (
    BUCKET_MONTH,
    PROMPT_VERSION_BY_BUCKET,
    TREND_SYSTEM_PROMPT,
    TrendSample,
    TrendsService,
    bedroom_window_checks,
    compute_trend_windows,
    compute_year_on_year,
)
from tests.test_night_thermal import PRODUCTION_NIGHTS, _production_fixture, _utc
from tests.test_reviews import AS_OF, WEEK_START, FakeReviewClient, _seed_profile, _seed_week

LONDON = "Europe/London"
REVIEW_FIGURES = ("rollup.thermal.avgIndoorPeakC", "rollup.thermal.disruptionNights")


def _nights(start: date, end: date) -> list[Any]:
    return [night for night in PRODUCTION_NIGHTS if start <= night.wake_date <= end]


def _stored_week_check(start: date, end: date, stated: float) -> AgreementCheck | None:
    """The check a pre-268 review packet would have met: its stated figure and
    per-night peaks against the brief's peaks for the same nights."""
    nights = _nights(start, end)
    return period_bedroom_check(
        figures=REVIEW_FIGURES,
        scope=f"{start.isoformat()} to {end.isoformat()}",
        stated=stated,
        shared_nights={night.wake_date: night.old_rule_peak for night in nights},
        brief_nights={night.wake_date: night.sleep_window_peak for night in nights},
    )


def _real_week_check(start: date, end: date) -> AgreementCheck | None:
    """The same week through today's code: both derivations over the same rows."""
    rows, sleeps = _production_fixture(uuid.uuid4(), tuple(_nights(start, end)))
    shared = night_indoor_peaks(rows, sleeps, start=start, end=end, timezone_name=LONDON)
    brief = brief_night_peaks(rows, sleeps, start=start, end=end, timezone_name=LONDON)
    values = [peak.peak_c for peak in shared.values()]
    return period_bedroom_check(
        figures=REVIEW_FIGURES,
        scope=f"{start.isoformat()} to {end.isoformat()}",
        stated=round(sum(values) / len(values), 1),
        shared_nights={day: peak.peak_c for day, peak in shared.items()},
        brief_nights=brief,
    )


# -- the two contested weeks ------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "stated", "expected_gap"),
    [
        (date(2026, 9, 7), date(2026, 9, 13), 20.9, 2.15),
        (date(2026, 9, 14), date(2026, 9, 20), 20.5, 1.66),
    ],
)
def test_the_contested_weeks_fail_naming_the_figure_and_both_sources(
    start: date, end: date, stated: float, expected_gap: float
) -> None:
    check = _stored_week_check(start, end, stated)
    assert check is not None
    section = evaluate_agreement([check])

    [finding] = section["findings"]
    assert finding["label"] == "bedroom peak overnight"
    assert finding["stated"]["value"] == stated
    assert finding["stated"]["by"] == "the weekly review and Trends"
    assert finding["reference"]["by"] == "the morning brief"
    assert finding["reference"]["source"] == "coach_sections.thermal_review"
    assert finding["difference"] == pytest.approx(expected_gap, abs=0.01)
    # Every night of the fortnight was out, not just the average.
    assert len(finding["disagreeingNights"]) == 7
    assert section["unreliableFigures"] == sorted(REVIEW_FIGURES)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 9, 7), date(2026, 9, 13)),
        (date(2026, 9, 14), date(2026, 9, 20)),
    ],
)
def test_the_same_weeks_after_268_pass(start: date, end: date) -> None:
    check = _real_week_check(start, end)
    assert check is not None
    section = evaluate_agreement([check])

    assert section["findings"] == []
    assert section["unreliableFigures"] == []
    [entry] = section["checked"]
    assert entry["status"] == "agrees"
    assert entry["nightsCompared"] == 7
    assert entry["stated"]["value"] == 18.8


def test_a_clean_week_produces_no_findings() -> None:
    """15-21 Sep, the week with the one genuinely warm night (21 Sep, 20.25 °C)."""
    check = _real_week_check(date(2026, 9, 15), date(2026, 9, 21))
    assert check is not None
    assert evaluate_agreement([check])["findings"] == []


def test_the_brief_derivation_reproduces_what_the_brief_showed() -> None:
    nights = _nights(date(2026, 9, 7), date(2026, 9, 22))
    rows, sleeps = _production_fixture(uuid.uuid4(), tuple(nights))
    brief = brief_night_peaks(
        rows,
        sleeps,
        start=nights[0].wake_date,
        end=nights[-1].wake_date,
        timezone_name=LONDON,
    )
    assert brief == {night.wake_date: night.sleep_window_peak for night in nights}


# -- the registry, not the bedroom ---------------------------------------------------


def test_a_newly_registered_pair_is_caught_by_the_same_code_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        AGREEMENT_PAIRS,
        "readiness_week_mean",
        AgreementPair(
            key="readiness_week_mean",
            label="average readiness",
            units="points",
            tolerance=0.5,
            derivations=(
                Derivation(surfaces="a new screen", source="new_screen.readiness"),
                Derivation(surfaces="the weekly review", source="reviews.readiness"),
            ),
        ),
    )
    section = evaluate_agreement(
        [
            AgreementCheck(
                pair="readiness_week_mean",
                figures=("newScreen.readiness",),
                scope="a week",
                stated=72.0,
                reference=68.4,
                stated_by=0,
            )
        ]
    )
    [finding] = section["findings"]
    assert finding["label"] == "average readiness"
    assert finding["stated"]["by"] == "a new screen"
    assert finding["reference"]["by"] == "the weekly review"
    assert section["unreliableFigures"] == ["newScreen.readiness"]


def test_a_figure_the_other_side_cannot_measure_is_not_a_finding() -> None:
    section = evaluate_agreement(
        [
            AgreementCheck(
                pair=PAIR_BEDROOM_PEAK,
                figures=("environment.thermalReview.indoorPeakC",),
                scope="a night",
                stated=19.2,
                reference=None,
                stated_by=0,
            )
        ]
    )
    assert section["checked"][0]["status"] == "not_comparable"
    assert section["findings"] == []


def test_each_deferred_pair_says_why() -> None:
    assert set(DEFERRED_PAIRS) == {
        "age-adjusted sleep score",
        "overnight HRV, resting heart rate, readiness and the raw sleep score",
        "REM share of sleep",
    }
    for reason in DEFERRED_PAIRS.values():
        assert len(reason) > 40


def test_the_gate_says_it_is_not_the_knowledge_bases_prose_rules() -> None:
    """272.4: data_quality_rules steer what a narrative says; this checks what a
    rollup computed."""
    assert cross_surface_agreement.__doc__ is not None
    assert "data_quality_rules" in cross_surface_agreement.__doc__


# -- the morning brief -------------------------------------------------------------


def _night_rows(wake: date) -> tuple[list[TemperatureReading], Sleep]:
    user_id = uuid.uuid4()
    night = wake - timedelta(days=1)
    rows = [
        TemperatureReading(
            user_id=user_id,
            captured_at_utc=_utc(datetime.combine(night, time(21, 45))),
            temperature_c=20.6,
        ),
        TemperatureReading(
            user_id=user_id,
            captured_at_utc=_utc(datetime.combine(wake, time(1, 30))),
            temperature_c=18.9,
        ),
        TemperatureReading(
            user_id=user_id,
            captured_at_utc=_utc(datetime.combine(wake, time(4, 0))),
            temperature_c=18.4,
        ),
    ]
    sleep = Sleep(
        user_id=user_id,
        calendar_date=wake,
        sleep_start_utc=_utc(datetime.combine(night, time(22, 30))),
        sleep_end_utc=_utc(datetime.combine(wake, time(6, 15))),
    )
    return rows, sleep


def test_the_brief_checks_its_own_night_against_the_shared_calculation() -> None:
    wake = date(2026, 9, 23)
    rows, sleep = _night_rows(wake)
    # The 21:45 reading is before he fell asleep: both derivations leave it out.
    section = evaluate_agreement(
        morning_bedroom_check(
            {"indoorPeakC": 18.9}, rows, sleep, subject_date=wake, timezone_name=LONDON
        )
    )
    [entry] = section["checked"]
    assert entry["status"] == "agrees"
    assert entry["figures"] == ["environment.thermalReview.indoorPeakC"]
    assert entry["reference"]["value"] == 18.9


def test_a_brief_that_disagrees_marks_its_peak_unreliable() -> None:
    wake = date(2026, 9, 23)
    rows, sleep = _night_rows(wake)
    section = evaluate_agreement(
        morning_bedroom_check(
            {"indoorPeakC": 20.6}, rows, sleep, subject_date=wake, timezone_name=LONDON
        )
    )
    [finding] = section["findings"]
    assert finding["stated"]["by"] == "the morning brief"
    assert finding["reference"]["by"] == "the weekly review and Trends"
    assert finding["disagreeingNights"] == [
        {"night": "2026-09-23", "stated": 20.6, "reference": 18.9}
    ]
    assert section["unreliableFigures"] == ["environment.thermalReview.indoorPeakC"]


def test_a_holiday_brief_states_no_peak_and_checks_nothing() -> None:
    wake = date(2026, 9, 28)
    rows, sleep = _night_rows(wake)
    assert morning_bedroom_check(None, rows, sleep, subject_date=wake, timezone_name=LONDON) == []


# -- Trends --------------------------------------------------------------------------


def _samples(month: int, shared: float, brief: float) -> list[TrendSample]:
    return [
        TrendSample(
            day=date(2026, month, day),
            indoor_peak_c=shared,
            indoor_peak_brief_c=brief,
        )
        for day in range(1, 8)
    ]


def test_trends_checks_each_shown_window_and_names_the_year_on_year_mean() -> None:
    samples = _samples(8, 19.6, 19.6) + _samples(9, 20.9, 18.8)
    windows = compute_trend_windows(samples, bucket=BUCKET_MONTH)
    comparison = compute_year_on_year(windows, bucket=BUCKET_MONTH, target_key="2026-09")
    section = evaluate_agreement(bedroom_window_checks(samples, windows, comparison))

    assert [entry["status"] for entry in section["checked"]] == ["agrees", "disagrees"]
    [finding] = section["findings"]
    assert finding["scope"] == windows[-1].label
    assert "recentWindows[2026-09].indoor_peak_c.mean" in section["unreliableFigures"]


# -- the alert -------------------------------------------------------------------------


def test_each_finding_is_alerted_at_error_level_before_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = Mock()
    monkeypatch.setattr(cross_surface_agreement, "log", log)
    check = _stored_week_check(date(2026, 9, 7), date(2026, 9, 13), 20.9)
    assert check is not None
    sent = alert_disagreements(
        evaluate_agreement([check]),
        surface="weekly_review",
        user_id=uuid.uuid4(),
        subject="2026-09-07",
    )
    assert sent == 1
    log.error.assert_called_once()
    event, fields = log.error.call_args.args[0], log.error.call_args.kwargs
    assert event == "cross_surface_disagreement"
    assert fields["pair"] == PAIR_BEDROOM_PEAK
    assert fields["stated"] == 20.9
    assert fields["reference_by"] == "coach_sections.thermal_review"


def test_a_clean_section_alerts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Mock()
    monkeypatch.setattr(cross_surface_agreement, "log", log)
    sent = alert_disagreements(
        evaluate_agreement([]), surface="morning_brief", user_id=uuid.uuid4(), subject="x"
    )
    assert sent == 0
    log.error.assert_not_called()


# -- the three prompts -----------------------------------------------------------------


def test_every_paid_read_is_told_what_an_unreliable_figure_means() -> None:
    for prompt in (MORNING_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, TREND_SYSTEM_PROMPT):
        assert CROSS_SURFACE_AGREEMENT_RULE in prompt
    # A changed instruction moves each version. The brief self-heals and reviews are
    # read unfiltered; Trends filters, so the close-out regenerates its narratives.
    # (Batch 294 moved the brief on again, to v50; Batch 296 to v51 and reviews to v10.)
    assert MORNING_PROMPT_VERSION == "morning-analysis-v56-2026-10-03"
    assert REVIEW_PROMPT_VERSION == "reviews-v10-2026-09-29"
    assert PROMPT_VERSION_BY_BUCKET[BUCKET_MONTH] == "trends-month-v12-2026-09-27"
    assert PROMPT_VERSION_BY_BUCKET["season"] == "trends-season-v12-2026-09-27"


# -- through the real services (PostgreSQL) ----------------------------------------------


async def _add_week_of_nights(db_conn: AsyncConnection, user_id: uuid.UUID, start: date) -> None:
    """Sleep windows and bedroom readings for seven nights, the 268 shape."""
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for offset in range(7):
            wake = start + timedelta(days=offset)
            night = wake - timedelta(days=1)
            session.add_all(
                [
                    TemperatureReading(
                        user_id=user_id,
                        source="hive",
                        product_id="thermostat",
                        captured_at_utc=_utc(datetime.combine(wake, time(2, 30))),
                        temperature_c=18.5 + offset / 10,
                        raw_payload={},
                    ),
                    TemperatureReading(
                        user_id=user_id,
                        source="hive",
                        product_id="thermostat",
                        captured_at_utc=_utc(datetime.combine(wake, time(14, 7))),
                        temperature_c=21.4,
                        raw_payload={},
                    ),
                    TemperatureReading(
                        user_id=user_id,
                        source="hive",
                        product_id="thermostat",
                        captured_at_utc=_utc(datetime.combine(night, time(23, 0))),
                        temperature_c=18.2,
                        raw_payload={},
                    ),
                ]
            )
        await session.commit()


@pytest.mark.asyncio
async def test_the_review_packet_carries_the_check(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_week(db_conn, user_id)
    await _add_week_of_nights(db_conn, user_id, WEEK_START)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        preview = await ReviewService(session).preview(user, PERIOD_WEEKLY, as_of=AS_OF)

    section = preview.packet["crossSurfaceAgreement"]
    [entry] = section["checked"]
    assert entry["status"] == "agrees"
    assert entry["nightsCompared"] == 7
    assert section["findings"] == []


@pytest.mark.asyncio
async def test_a_disagreeing_review_is_marked_alerted_and_still_written(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mark and alert, never block (272.3)."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_week(db_conn, user_id)
    await _add_week_of_nights(db_conn, user_id, WEEK_START)

    real = reviews.brief_night_peaks

    def drifted(*args: Any, **kwargs: Any) -> dict[date, float]:
        return {night: peak - 2.0 for night, peak in real(*args, **kwargs).items()}

    monkeypatch.setattr(reviews, "brief_night_peaks", drifted)
    log = Mock()
    monkeypatch.setattr(cross_surface_agreement, "log", log)
    client = FakeReviewClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        result = await ReviewService(session).run(user, PERIOD_WEEKLY, as_of=AS_OF, client=client)

    assert result.generated is True
    [call] = client.calls
    section = call["packet"]["crossSurfaceAgreement"]
    assert section["unreliableFigures"] == sorted(REVIEW_FIGURES)
    log.error.assert_called_once()
    assert log.error.call_args.args[0] == "cross_surface_disagreement"


@pytest.mark.asyncio
async def test_the_trends_packet_carries_the_check(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Agreement Test",
                role=UserRole.admin,
                timezone=LONDON,
                is_active=True,
            )
        )
        await session.commit()
        session.add(
            KnowledgeBase(
                user_id=user_id, section="profile", version=1, is_active=True, content={"age": 57}
            )
        )
        for offset in range(7):
            wake = date(2026, 9, 1) + timedelta(days=offset)
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=wake,
                    score=78,
                    sleep_start_utc=_utc(datetime.combine(wake - timedelta(days=1), time(22, 30))),
                    sleep_end_utc=_utc(datetime.combine(wake, time(6, 15))),
                    raw_payload={},
                )
            )
        await session.commit()
    await _add_week_of_nights(db_conn, user_id, date(2026, 9, 1))

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        preview = await TrendsService(session).narrative_preview(
            user, bucket=BUCKET_MONTH, as_of=date(2026, 9, 27)
        )

    section = preview.packet["crossSurfaceAgreement"]
    [entry] = [item for item in section["checked"] if item["scope"] == "September 2026"]
    assert entry["status"] == "agrees"
    assert entry["nightsCompared"] == 7
    assert section["findings"] == []


@pytest.mark.asyncio
async def test_the_morning_packet_carries_the_check(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    wake = date(2026, 9, 23)
    rows, sleep = _night_rows(wake)
    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Agreement Morning",
            role=UserRole.admin,
            timezone=LONDON,
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            Sleep(
                user_id=user_id,
                calendar_date=wake,
                sleep_start_utc=sleep.sleep_start_utc,
                sleep_end_utc=sleep.sleep_end_utc,
                score=80,
                raw_payload={},
                factors_json={},
            )
        )
        for row in rows:
            session.add(
                TemperatureReading(
                    user_id=user_id,
                    source="hive",
                    product_id="thermostat",
                    captured_at_utc=row.captured_at_utc,
                    temperature_c=row.temperature_c,
                    raw_payload={},
                )
            )
        await session.commit()
        packet = await MorningAnalysisService(session).assemble_context_packet(player, wake)

    [entry] = packet["crossSurfaceAgreement"]["checked"]
    assert entry["status"] == "agrees"
    assert entry["stated"]["value"] == 18.9
    assert packet["environment"]["thermalReview"]["indoorPeakC"] == 18.9


def test_the_shared_night_calculation_does_not_depend_on_row_order() -> None:
    """Batch 272 sorts the readings once and slices each night by binary search, so
    the 800-day window Trends and every coach turn load costs milliseconds, not
    seconds. The answer must not depend on the order the rows arrive in."""
    nights = _nights(date(2026, 9, 7), date(2026, 9, 22))
    rows, sleeps = _production_fixture(uuid.uuid4(), tuple(nights))
    start, end = nights[0].wake_date, nights[-1].wake_date
    forwards = night_indoor_peaks(rows, sleeps, start=start, end=end, timezone_name=LONDON)
    backwards = night_indoor_peaks(
        list(reversed(rows)), sleeps, start=start, end=end, timezone_name=LONDON
    )
    assert forwards == backwards
    assert {day: peak.peak_c for day, peak in forwards.items()} == {
        night.wake_date: night.sleep_window_peak for night in nights
    }
