"""Batch 347: the weekly review and the morning brief give a recorded disruption first.

Mark's strongest complaint of 12–19 Oct 2026 was the app treating the effects of his
27 Sep–6 Oct holiday and a night away as concerns. The chat answers it with v27
(Decision #430); this batch gives the two stored reads the same rule over one shared
record, ``recordedDisruptions``, because the weekly review could not see a holiday at all.

The words quoted below are made up for the tests. Mark's own words never enter this
public repository.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import CheckInReading, KnowledgeBase, ManualEntry, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.coach_policy import (
    KNOWN_DISRUPTION_RULE,
    PACKET_FIELD_NAMES_RULE,
    READ_PROMPT_FLOORS,
    facts_missing_basis,
    missing_floors,
)
from src.services.holiday_pause import HolidayWindow
from src.services.morning_analysis import (
    DISRUPTION_RECORD_NOTE,
    MorningAnalysisService,
)
from src.services.morning_analysis import (
    PROMPT_VERSION as GRADED_PROMPT_VERSION,
)
from src.services.morning_analysis import (
    SYSTEM_PROMPT as GRADED_SYSTEM_PROMPT,
)
from src.services.notes_reader import notes_hash
from src.services.recorded_disruptions import (
    BASIS_HOLIDAY,
    BASIS_NOTE,
    BASIS_SYMPTOM_ANSWER,
    MAX_WORDS_PER_ITEM,
    MORNING_LOOKBACK_DAYS,
    REVIEW_LOOKBACK_DAYS,
    SETTLE_DAYS,
    STAGE_ONGOING,
    STAGE_PAST,
    STAGE_SETTLING,
    CheckInRecord,
    build_recorded_disruptions,
    load_recorded_disruptions,
)
from src.services.reviews import (
    PACKET_VERSION as REVIEW_PACKET_VERSION,
)
from src.services.reviews import (
    PERIOD_WEEKLY,
    REVIEW_MORNINGS_RULE,
    REVIEW_PLAIN_WORDS_RULE,
    ReviewService,
    review_wording_leaks,
)
from src.services.reviews import (
    PROMPT_VERSION as REVIEW_PROMPT_VERSION,
)
from src.services.reviews import (
    SYSTEM_PROMPT as REVIEW_SYSTEM_PROMPT,
)
from src.services.symptom_check import (
    SYMPTOM_LABELS,
    SYMPTOMS_CHEST_HEART,
    SYMPTOMS_FEVER_ACHES,
    SYMPTOMS_HEAD_COLD,
)
from tests.test_batch_296_graded_colour import _seed_one_poor_night

HOLIDAY = HolidayWindow(
    start_date=date(2026, 9, 27),
    end_date=date(2026, 10, 6),
    paused_at_utc=datetime(2026, 9, 27, 10, 6),
)


def _flag(state: str = "present", *, who: str = "him", when: str = "now", words: str = "") -> Any:
    return {"state": state, "who": who, "when": when, "words": words}


def _reading(**flags: dict[str, Any]) -> dict[str, Any]:
    """A notes reading with every flag absent except the ones given."""

    names = (
        "chest_heart",
        "fever_aches",
        "head_cold",
        "unwell",
        "fatigue",
        "alcohol",
        "travel",
        "disturbed_night",
        "training_load",
        "deliberate_rest",
    )
    reading: dict[str, Any] = {
        name: _flag("absent", who="unknown", when="unknown") for name in names
    }
    reading.update(flags)
    return reading


def _build(
    *,
    windows: list[HolidayWindow] | None = None,
    check_ins: list[CheckInRecord] | None = None,
    as_of: date,
    lookback: int = MORNING_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    record = build_recorded_disruptions(
        windows=windows or [],
        check_ins=check_ins or [],
        window_start=as_of - timedelta(days=lookback),
        as_of=as_of,
    )
    return list(record.to_packet()["items"])


# -- a holiday, by the mornings he woke away ---------------------------------------------


def test_a_holiday_covers_the_mornings_he_woke_away_and_settles_a_week_later() -> None:
    [item] = _build(windows=[HOLIDAY], as_of=date(2026, 10, 11))
    # Overnight away is end-exclusive (Decision #213): nights 27 Sep to 5 Oct, waking
    # 28 Sep to 6 Oct; the night he came home was at home.
    assert item == {
        "reason": "holiday",
        "startDate": "2026-09-27",
        "endDate": "2026-10-06",
        "firstMorning": "2026-09-28",
        "lastMorning": "2026-10-06",
        "settleBy": "2026-10-13",
        "stage": STAGE_SETTLING,
        "basis": BASIS_HOLIDAY,
    }
    assert SETTLE_DAYS == 7


@pytest.mark.parametrize(
    ("as_of", "stage"),
    [
        (date(2026, 10, 1), STAGE_ONGOING),
        (date(2026, 10, 6), STAGE_ONGOING),
        (date(2026, 10, 7), STAGE_SETTLING),
        (date(2026, 10, 13), STAGE_SETTLING),
        (date(2026, 10, 14), STAGE_PAST),
        (date(2026, 10, 18), STAGE_PAST),
    ],
)
def test_the_stage_is_read_from_the_reads_own_date(as_of: date, stage: str) -> None:
    [item] = _build(windows=[HOLIDAY], as_of=as_of)
    assert item["stage"] == stage


def test_a_window_with_no_night_away_is_not_a_disruption() -> None:
    day_trip = HolidayWindow(
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 10),
        paused_at_utc=datetime(2026, 10, 9, 18, 0),
    )
    assert _build(windows=[day_trip], as_of=date(2026, 10, 12)) == []


def test_a_resumed_holiday_still_records_where_he_was() -> None:
    resumed = HolidayWindow(
        start_date=date(2026, 7, 12),
        end_date=date(2026, 7, 16),
        paused_at_utc=datetime(2026, 7, 10, 19, 31),
        resumed_at_utc=datetime(2026, 7, 16, 12, 0),
    )
    [item] = _build(windows=[resumed], as_of=date(2026, 7, 20))
    assert (item["firstMorning"], item["lastMorning"]) == ("2026-07-13", "2026-07-16")


def test_only_disruptions_that_touch_the_window_are_carried_with_their_true_dates() -> None:
    july = HolidayWindow(
        start_date=date(2026, 7, 12),
        end_date=date(2026, 7, 16),
        paused_at_utc=datetime(2026, 7, 10, 19, 31),
    )
    planned = HolidayWindow(
        start_date=date(2026, 12, 20),
        end_date=date(2026, 12, 28),
        paused_at_utc=datetime(2026, 10, 1, 9, 0),
    )
    items = _build(windows=[july, HOLIDAY, planned], as_of=date(2026, 10, 21))
    # July ended long before the 28 mornings; December has not started. The holiday's
    # first morning is before the window opens (24 Sep), and its true dates are kept.
    assert [item["startDate"] for item in items] == ["2026-09-27"]
    assert _build(windows=[HOLIDAY], as_of=date(2026, 11, 3)) == []


# -- his check-ins -----------------------------------------------------------------------


def test_a_night_away_he_reports_for_last_night_is_recorded_with_his_words() -> None:
    check_in = CheckInRecord(
        entry_date=date(2026, 10, 19),
        reading=_reading(travel=_flag(when="last_night", words="stayed away overnight")),
    )
    [item] = _build(check_ins=[check_in], as_of=date(2026, 10, 21))
    assert item == {
        "reason": "travel",
        "startDate": "2026-10-19",
        "endDate": "2026-10-19",
        "firstMorning": "2026-10-19",
        "lastMorning": "2026-10-19",
        "settleBy": "2026-10-26",
        "stage": STAGE_SETTLING,
        "basis": BASIS_NOTE,
        "words": ["stayed away overnight"],
    }


def test_a_note_that_places_a_cause_earlier_records_nothing() -> None:
    check_in = CheckInRecord(
        entry_date=date(2026, 10, 9),
        reading=_reading(
            travel=_flag(when="earlier", words="after the trip"),
            alcohol=_flag(when="earlier", words="a few drinks while away"),
        ),
    )
    assert _build(check_ins=[check_in], as_of=date(2026, 10, 10)) == []


def test_alcohol_last_night_is_recorded() -> None:
    check_in = CheckInRecord(
        entry_date=date(2026, 10, 15),
        reading=_reading(alcohol=_flag(when="last_night", words="two glasses of wine")),
    )
    [item] = _build(check_ins=[check_in], as_of=date(2026, 10, 15))
    assert (item["reason"], item["stage"], item["words"]) == (
        "alcohol",
        STAGE_ONGOING,
        ["two glasses of wine"],
    )


def test_illness_is_a_cold_fever_or_aches_and_never_chest_or_heart() -> None:
    """Craig, 22 Oct: never frame a chest or heart report as a dip to wait out."""

    day = date(2026, 10, 15)
    written = CheckInRecord(
        entry_date=day,
        reading=_reading(head_cold=_flag(words="streaming cold")),
    )
    feverish = CheckInRecord(
        entry_date=day + timedelta(days=3),
        reading=_reading(fever_aches=_flag(when="last_night", words="shivery and achy")),
    )
    chest = CheckInRecord(
        entry_date=day + timedelta(days=5),
        symptoms=SYMPTOMS_CHEST_HEART,
        reading=_reading(chest_heart=_flag(words="tight chest")),
    )
    unwell = CheckInRecord(
        entry_date=day + timedelta(days=7),
        reading=_reading(unwell=_flag(words="feeling off")),
    )
    someone_else = CheckInRecord(
        entry_date=day + timedelta(days=9),
        reading=_reading(head_cold=_flag(who="someone_else", words="she has a cold")),
    )
    items = _build(
        check_ins=[written, feverish, chest, unwell, someone_else],
        as_of=day + timedelta(days=10),
    )
    assert [(item["reason"], item["words"]) for item in items] == [
        ("illness", ["streaming cold"]),
        ("illness", ["shivery and achy"]),
    ]


def test_an_illness_answer_is_recorded_once_across_the_days_he_gave_it() -> None:
    days = [date(2026, 10, 14) + timedelta(days=offset) for offset in range(3)]
    check_ins = [CheckInRecord(entry_date=day, symptoms=SYMPTOMS_HEAD_COLD) for day in days]
    check_ins.append(CheckInRecord(entry_date=days[-1], symptoms=SYMPTOMS_HEAD_COLD))
    [item] = _build(check_ins=check_ins, as_of=date(2026, 10, 17))
    assert (item["firstMorning"], item["lastMorning"]) == ("2026-10-14", "2026-10-16")
    assert item["basis"] == BASIS_SYMPTOM_ANSWER
    assert item["words"] == [SYMPTOM_LABELS[SYMPTOMS_HEAD_COLD]]


def test_a_tapped_and_a_written_illness_keep_their_own_basis() -> None:
    day = date(2026, 10, 14)
    check_ins = [
        CheckInRecord(entry_date=day, symptoms=SYMPTOMS_FEVER_ACHES),
        CheckInRecord(
            entry_date=day + timedelta(days=1),
            reading=_reading(fever_aches=_flag(words="aching all over")),
        ),
    ]
    items = _build(check_ins=check_ins, as_of=day + timedelta(days=2))
    assert [(item["reason"], item["basis"]) for item in items] == [
        ("illness", BASIS_SYMPTOM_ANSWER),
        ("illness", BASIS_NOTE),
    ]


def test_consecutive_nights_away_merge_and_a_gap_starts_a_new_one() -> None:
    def away(day: date) -> CheckInRecord:
        return CheckInRecord(
            entry_date=day,
            reading=_reading(travel=_flag(when="last_night", words="hotel")),
        )

    items = _build(
        check_ins=[away(date(2026, 10, 12)), away(date(2026, 10, 13)), away(date(2026, 10, 16))],
        as_of=date(2026, 10, 18),
    )
    assert [(item["firstMorning"], item["lastMorning"]) for item in items] == [
        ("2026-10-12", "2026-10-13"),
        ("2026-10-16", "2026-10-16"),
    ]
    assert items[0]["words"] == ["hotel"]


def test_a_night_away_inside_a_holiday_adds_nothing_and_one_after_it_stays() -> None:
    inside = CheckInRecord(
        entry_date=date(2026, 10, 1),
        reading=_reading(travel=_flag(words="still away")),
    )
    after = CheckInRecord(
        entry_date=date(2026, 10, 19),
        reading=_reading(travel=_flag(when="last_night", words="away overnight")),
    )
    items = _build(windows=[HOLIDAY], check_ins=[inside, after], as_of=date(2026, 10, 21))
    assert [(item["reason"], item["firstMorning"]) for item in items] == [
        ("holiday", "2026-09-28"),
        ("travel", "2026-10-19"),
    ]


def test_training_load_and_deliberate_rest_are_not_disruptions() -> None:
    check_in = CheckInRecord(
        entry_date=date(2026, 10, 14),
        reading=_reading(
            training_load=_flag(words="big week"),
            deliberate_rest=_flag(words="planned easy day"),
        ),
    )
    assert _build(check_ins=[check_in], as_of=date(2026, 10, 14)) == []


def test_his_words_are_distinct_and_bounded() -> None:
    days = [date(2026, 10, 10) + timedelta(days=offset) for offset in range(5)]
    check_ins = [
        CheckInRecord(
            entry_date=day,
            reading=_reading(travel=_flag(when="last_night", words=f"stop {index % 4}")),
        )
        for index, day in enumerate(days)
    ]
    [item] = _build(check_ins=check_ins, as_of=days[-1])
    assert len(item["words"]) == MAX_WORDS_PER_ITEM
    assert item["words"] == ["stop 0", "stop 1", "stop 2"]


def test_the_record_says_what_it_holds_and_items_have_a_readable_basis() -> None:
    record = build_recorded_disruptions(
        windows=[HOLIDAY],
        check_ins=[],
        window_start=date(2026, 9, 21),
        as_of=date(2026, 10, 18),
    ).to_packet()
    assert (record["from"], record["asOf"]) == ("2026-09-21", "2026-10-18")
    assert "never chest or heart" in record["meaning"]
    assert "not on record" in record["meaning"]
    assert facts_missing_basis({"recordedDisruptions": record}) == ()


def test_the_record_on_22_oct_is_the_holiday_and_one_night_away() -> None:
    """Production's shape, read-only on 22 Oct: notes from 1 Oct, the holiday, 19 Oct."""

    check_ins = [
        CheckInRecord(entry_date=date(2026, 10, 1), reading=_reading(travel=_flag())),
        CheckInRecord(
            entry_date=date(2026, 10, 5),
            reading=_reading(travel=_flag(when="earlier"), alcohol=_flag(when="earlier")),
        ),
        *(
            CheckInRecord(entry_date=day, reading=_reading(travel=_flag(when="earlier")))
            for day in (date(2026, 10, 7), date(2026, 10, 9), date(2026, 10, 12))
        ),
        CheckInRecord(
            entry_date=date(2026, 10, 19),
            reading=_reading(travel=_flag(when="last_night", words="away overnight")),
        ),
    ]
    on_18 = _build(windows=[HOLIDAY], check_ins=check_ins, as_of=date(2026, 10, 18))
    on_21 = _build(windows=[HOLIDAY], check_ins=check_ins, as_of=date(2026, 10, 21))
    assert [(item["reason"], item["stage"]) for item in on_18] == [("holiday", STAGE_PAST)]
    assert [(item["reason"], item["stage"]) for item in on_21] == [
        ("holiday", STAGE_PAST),
        ("travel", STAGE_SETTLING),
    ]
    # The 12–18 Oct review looks back to 21 Sep and sees the holiday; so does 5–11 Oct's,
    # where it is still settling when the week ends.
    review_11 = _build(
        windows=[HOLIDAY],
        check_ins=check_ins,
        as_of=date(2026, 10, 11),
        lookback=6 + REVIEW_LOOKBACK_DAYS,
    )
    assert [(item["reason"], item["stage"]) for item in review_11] == [("holiday", STAGE_SETTLING)]


# -- the rule, shared verbatim ---------------------------------------------------------


def test_both_stored_reads_carry_the_rule_verbatim() -> None:
    assert REVIEW_SYSTEM_PROMPT.count(KNOWN_DISRUPTION_RULE) == 1
    assert GRADED_SYSTEM_PROMPT.count(KNOWN_DISRUPTION_RULE) == 1
    assert GRADED_SYSTEM_PROMPT.count(DISRUPTION_RECORD_NOTE) == 1
    assert GRADED_PROMPT_VERSION == "morning-analysis-v65-2026-10-29"
    assert REVIEW_PROMPT_VERSION == "reviews-v14-2026-10-29"
    assert REVIEW_PACKET_VERSION == 4


def test_the_rule_names_the_fields_the_record_writes() -> None:
    record = build_recorded_disruptions(
        windows=[HOLIDAY], check_ins=[], window_start=date(2026, 9, 21), as_of=date(2026, 10, 9)
    ).to_packet()
    [item] = record["items"]
    for field in ("firstMorning", "lastMorning", "settleBy"):
        assert field in item
        assert field in KNOWN_DISRUPTION_RULE
    assert "recordedDisruptions" in KNOWN_DISRUPTION_RULE


def test_the_rule_gives_the_disruption_first_and_keeps_the_call() -> None:
    rule = " ".join(KNOWN_DISRUPTION_RULE.split())
    assert "a holiday, travel or another night away" in rule
    assert "illness (a cold, fever or aches, never chest or heart symptoms)" in rule
    assert "between a disruption's firstMorning and its settleBy" in rule
    assert "say first and plainly that it is the most likely cause" in rule
    assert "Do not argue it down from when the dip began" in rule
    assert "or hedge it with causes no record points to" in rule
    # v27's replay: Mark got draft 1's phrase back almost word for word (PR #387, draft 2).
    assert "one possibility among several" not in rule
    assert "Say what would confirm it, giving the date" in rule
    assert "back in his usual range by settleBy" in rule
    # The 12 Oct brief recited "the app's rule"; the 11 Oct review "the app's settle window".
    assert "Say it as a coach would, never as a rule or a window the app applies" in rule
    assert "do not stretch it to the rest" in rule
    assert "Raise a dip as a concern only when it is still there after settleBy" in rule
    assert "never name a disruption the record does not hold" in rule
    assert "never changes the computed call, a floor or a warning" in rule


def test_the_brief_reads_a_chronic_count_as_a_dip_and_keeps_the_calls_reason() -> None:
    """The 18 Oct replay: HRV back that morning, so the card's 18 of 28 got no holiday."""

    note = " ".join(DISRUPTION_RECORD_NOTE.split())
    assert "count of missed nights is a dip on those nights, even when today's numbers" in note
    assert "say first that the disruption is the most likely cause of that part" in note
    assert "such as training load for readiness, keep that reason for that number" in note


def test_the_weekly_review_speaks_in_plain_words() -> None:
    prompt = " ".join(REVIEW_SYSTEM_PROMPT.split())
    assert "**Trends**, **Wins**, **Worth watching**, and **Recommendations**" in prompt
    assert "**Concerns**" not in prompt
    # The 11 Oct replay put a settling holiday dip under Worth watching: it is a trend.
    assert "never a dip a recorded disruption explains" in prompt
    assert "that belongs under Trends, with its cause" in prompt
    assert "sample counts" not in prompt
    assert "say in words how many mornings or nights they rest on" in prompt
    assert REVIEW_PLAIN_WORDS_RULE in REVIEW_SYSTEM_PROMPT
    assert PACKET_FIELD_NAMES_RULE in REVIEW_SYSTEM_PROMPT
    assert REVIEW_MORNINGS_RULE in REVIEW_SYSTEM_PROMPT
    plain = " ".join(REVIEW_PLAIN_WORDS_RULE.split())
    for banned in ('"n="', '"samples"', "quartiles", "heldDays", "deterministic", "UTC"):
        assert banned in plain, banned
    # The floors the review states survive the rewrite.
    assert missing_floors(REVIEW_SYSTEM_PROMPT, READ_PROMPT_FLOORS["reviews"]) == ()
    assert missing_floors(GRADED_SYSTEM_PROMPT, READ_PROMPT_FLOORS["morning_analysis"]) == ()


# -- the logged wording check ----------------------------------------------------------


def test_the_wording_check_finds_what_the_18_oct_review_showed() -> None:
    leaky = (
        "**Bottom line:** A steady week.\n\n"
        "**Trends**\n- Readiness rose from 50.3 (n=3) to 64.8 (n=4).\n"
        "- Sleep sat inside your quartiles.\n"
        "- FTP drifted down 3.45% over 23 samples.\n\n"
        "**Concerns**\n- One morning was held (heldDays = 1).\n"
    )
    assert review_wording_leaks(leaky) == (
        "concerns_heading",
        "quartile_or_percentile",
        "sample_count",
        "field_name",
    )
    assert review_wording_leaks("Mornings: 2 green, 1 Amber; the deterministic verdict, UTC") == (
        "colour",
        "internal_call_term",
        "utc",
    )


def test_the_wording_check_passes_plain_words() -> None:
    clean = (
        "**Bottom line:** Your HRV dip this week follows your holiday and is settling.\n\n"
        "**Trends**\n- HRV averaged 42 ms over seven mornings, below your usual range.\n"
        "- Blood pressure 118/76 mmHg; no red flags.\n\n"
        "**Worth watching**\n- Nothing beyond the holiday's settling week.\n\n"
        "**Recommendations**\n- Keep Tuesday's VO2 session as planned.\n"
    )
    assert review_wording_leaks(clean) == ()


# -- on Postgres: the loader and both packets --------------------------------------------


async def _player(session: Any, name: str) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name=name,
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )
    session.add(player)
    await session.flush()
    return player


def _holiday_row(user_id: uuid.UUID) -> KnowledgeBase:
    return KnowledgeBase(
        user_id=user_id,
        section="holiday_windows",
        version=1,
        is_active=True,
        source="holiday_manager",
        content={"windows": [HOLIDAY.to_dict()]},
    )


def _check_in(user_id: uuid.UUID, day: date, *, notes: str | None, **fields: Any) -> ManualEntry:
    return ManualEntry(
        user_id=user_id,
        entry_date=day,
        entry_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
        notes=notes,
        supplements_json={},
        food_json={},
        sleep_setup_json={},
        **fields,
    )


def _reading_row(entry: ManualEntry, notes: str, reading: dict[str, Any]) -> CheckInReading:
    digest = notes_hash(notes)
    assert digest is not None
    return CheckInReading(
        user_id=entry.user_id,
        manual_entry_id=entry.id,
        notes_sha256=digest,
        status="read",
        reading=reading,
        model_name="fake",
        prompt_version="notes-reader-test",
    )


@pytest.mark.asyncio
async def test_the_loader_reads_current_readings_and_answers_only(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player = await _player(session, "Disruption Loader")
        session.add(_holiday_row(player.id))
        away = _check_in(player.id, date(2026, 10, 19), notes="Away overnight for a wedding")
        edited = _check_in(player.id, date(2026, 10, 16), notes="Edited: all fine")
        tapped = _check_in(player.id, date(2026, 10, 14), notes=None, symptoms="head_cold")
        workout = PlannedWorkout(
            user_id=player.id,
            workout_date=date(2026, 10, 18),
            version=1,
            title="Z2",
            workout_type="bike_z2",
            status="planned",
            is_active=True,
            planned_duration_min=60,
            intensity_target="Zone 2",
            source="test",
        )
        session.add_all([away, edited, tapped, workout])
        await session.flush()
        ride_note = _check_in(
            player.id,
            date(2026, 10, 18),
            notes="Rode after a late night out",
            planned_workout_id=workout.id,
        )
        session.add(ride_note)
        await session.flush()
        session.add_all(
            [
                _reading_row(
                    away,
                    "Away overnight for a wedding",
                    _reading(travel=_flag(when="last_night", words="away overnight")),
                ),
                # Read before he edited the note: it no longer speaks for it.
                _reading_row(
                    edited,
                    "Had a heavy night of drinking",
                    _reading(alcohol=_flag(when="last_night", words="heavy night")),
                ),
                _reading_row(
                    ride_note,
                    "Rode after a late night out",
                    _reading(alcohol=_flag(when="last_night", words="late night out")),
                ),
            ]
        )
        await session.commit()

        record = await load_recorded_disruptions(
            session,
            player.id,
            windows=[HOLIDAY],
            window_start=date(2026, 9, 24),
            as_of=date(2026, 10, 21),
        )

    items = record.to_packet()["items"]
    assert [(item["reason"], item["firstMorning"], item["basis"]) for item in items] == [
        ("holiday", "2026-09-28", BASIS_HOLIDAY),
        ("illness", "2026-10-14", BASIS_SYMPTOM_ANSWER),
        ("travel", "2026-10-19", BASIS_NOTE),
    ]


@pytest.mark.asyncio
async def test_the_weekly_review_packet_carries_the_record(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player = await _player(session, "Disruption Review")
        session.add(_holiday_row(player.id))
        await session.commit()
        preview = await ReviewService(session).preview(
            player, PERIOD_WEEKLY, as_of=date(2026, 10, 11)
        )

    record = preview.packet["recordedDisruptions"]
    assert (record["from"], record["asOf"]) == ("2026-09-14", "2026-10-11")
    [item] = record["items"]
    assert (item["reason"], item["settleBy"], item["stage"]) == (
        "holiday",
        "2026-10-13",
        STAGE_SETTLING,
    )
    assert preview.packet["packetVersion"] == 4
    assert (
        "give_recorded_disruption_first_as_likely_cause"
        in (preview.packet["prompt"]["outputRules"])
    )


@pytest.mark.asyncio
async def test_a_mid_week_review_speaks_from_today_not_sunday(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player = await _player(session, "Disruption Midweek")
        session.add(_holiday_row(player.id))
        await session.commit()
        preview = await ReviewService(session).preview(
            player, PERIOD_WEEKLY, as_of=date(2026, 10, 7)
        )

    record = preview.packet["recordedDisruptions"]
    assert record["asOf"] == "2026-10-07"
    assert record["items"][0]["stage"] == STAGE_SETTLING


@pytest.mark.asyncio
async def test_the_morning_packet_carries_the_record(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    day = date(2026, 10, 9)
    async with session_factory() as session:
        player = await _player(session, "Disruption Morning")
        await _seed_one_poor_night(session, player.id, day)
        session.add(_holiday_row(player.id))
        await session.commit()
        packet = await MorningAnalysisService(session).assemble_context_packet(player, day)

    record = packet["recordedDisruptions"]
    assert (record["from"], record["asOf"]) == ("2026-09-12", "2026-10-09")
    [item] = record["items"]
    assert (item["reason"], item["stage"]) == ("holiday", STAGE_SETTLING)
    # The seeded session's source ("test") has no readable basis of its own; only the
    # record's basis is this batch's to prove.
    assert "recorded_disruption" not in facts_missing_basis(packet)
    assert "give_recorded_disruption_first_as_likely_cause" in packet["prompt"]["outputRules"]
    assert packet["prompt"]["version"] == GRADED_PROMPT_VERSION
