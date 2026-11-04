"""Batch 370 — health rules completed.

370.1 (HS361-04, answering AI358-04): the memory filter passed 18 of 18 crafted
health-dismissing statements, so a brush-off ("chest tightness is always his asthma")
could become a standing belief of the coach's. A coaching memory is never the place for a
health attribution, and one held back goes nowhere else (Craig, 4 Nov: "Nowhere").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from src.services.conversation_learning import (
    KIND_FACT,
    LEARNED_CONTEXT_SECTION,
    ExtractionEnvelope,
    LearningSource,
    filter_candidates,
    names_a_health_matter,
    statement_is_durable,
)

# -- 370.1: the memory filter never stores a health attribution --------------------------

#: R6's 18 health-dismissing "facts", crafted as a reader might extract them; none is his.
HEALTH_DISMISSALS = (
    "His chest tightness on climbs is always his asthma.",
    "The fluttering he feels on climbs is normal for him.",
    "Skipped beats after hard efforts are harmless for him.",
    "His left-arm ache on hard efforts is from an old shoulder injury.",
    "The jaw ache on intervals is just him clenching his teeth.",
    "Feeling light-headed after rides is fine for him.",
    "His blackout after the long ride was down to dehydration.",
    "Getting breathless on the stairs is just his fitness dropping.",
    "His heart rate jumping to 190 on easy rides is a strap glitch.",
    "His AF is managed and doesn't affect his riding.",
    "Blood pressure readings over 160 at the GP are white-coat.",
    "He takes a beta-blocker for his blood pressure.",
    "Low overnight oxygen readings are just the watch.",
    "A raised resting heart rate can be ignored when he is busy.",
    "The wheeze he gets on cold mornings is nothing.",
    "Stomach pain on hard rides is from his gels.",
    "His colds never go to his chest.",
    "A pounding heart after intervals is normal for him.",
)
#: Ways of saying the chest symptom itself that the first replay of the patterns missed.
CHEST_SAID_PLAINLY = (
    "His chest gets tight on long climbs.",
    "A tight chest on cold mornings is normal for him.",
)
#: R6's 7 ordinary statements: "heart" and "chest" are everyday training words.
TRAINING_FACTS = (
    "He trains with a chest-strap heart-rate monitor.",
    "His heart rate drifts up a few beats in a warm room.",
    "His Zone 2 sits at about 120 bpm.",
    "He gets breathless on VO2 intervals, which he expects.",
    "He prefers heart-rate targets to power on easy rides.",
    "His resting heart rate is usually in the mid-40s.",
    "He likes the coach to explain his heart-rate zones.",
)


@pytest.mark.parametrize("statement", HEALTH_DISMISSALS)
def test_a_health_attribution_is_never_a_memory(statement: str) -> None:
    assert names_a_health_matter(statement)
    assert not statement_is_durable(statement, kind=KIND_FACT)


@pytest.mark.parametrize("statement", CHEST_SAID_PLAINLY)
def test_the_chest_symptom_said_plainly_is_caught(statement: str) -> None:
    assert names_a_health_matter(statement)


@pytest.mark.parametrize("statement", TRAINING_FACTS)
def test_his_training_facts_still_pass(statement: str) -> None:
    assert not names_a_health_matter(statement)
    assert statement_is_durable(statement, kind=KIND_FACT)


@pytest.mark.parametrize(
    "statement",
    (
        "He races best in April.",
        "He sleeps with blackout blinds.",
        "He uses a medicine ball for core work.",
        "His power collapses after two hours without food.",
        "He calls threshold work the hurt locker.",
    ),
)
def test_words_that_only_look_medical_pass(statement: str) -> None:
    assert not names_a_health_matter(statement)


def _source(text: str) -> LearningSource:
    return LearningSource(
        source_id="chat:1",
        source_type="chat",
        source_date=date(2026, 11, 4),
        text=text,
        occurred_at_utc=datetime(2026, 11, 4, 9, 0),
    )


def _kept(statement: str, quotes: list[str], said: str) -> list[Any]:
    candidate = {
        "kind": KIND_FACT,
        "statement": statement,
        "destination": LEARNED_CONTEXT_SECTION,
        "experiment": None,
        "evidence": [{"source_id": "chat:1", "quote": quote} for quote in quotes],
    }
    return filter_candidates(
        ExtractionEnvelope.model_validate({"candidates": [candidate]}),
        sources=[_source(said)],
        existing_statements=[],
    )


def test_nor_a_memory_whose_evidence_is_his_words_about_his_health() -> None:
    """A tidy statement drawn partly from a health quote would still store the quote."""

    said = "Long climbs feel hard lately, and my chest gets tight on the long climbs."
    statement = "Long climbs feel hard to him lately."
    assert _kept(statement, ["Long climbs feel hard lately"], said)
    assert not _kept(
        statement, ["Long climbs feel hard lately", "my chest gets tight on the long climbs"], said
    )


# -- 370.2: a heart-rate jump on the bike asks one neutral question -------------------------


def _ride(*segments: tuple[int, float, float]) -> list[tuple[float, float, float]]:
    """``(seconds, heart rate, power)`` segments, sampled every 2 seconds as his rides are."""

    samples: list[tuple[float, float, float]] = []
    t = 0.0
    for seconds, hr, power in segments:
        for _ in range(int(seconds // 2)):
            samples.append((t, hr, power))
            t += 2.0
    return samples


#: 24 Sep's shape: steady at 136 bpm and 250 W, then 186, 197, 191, 181 with no change in
#: power, back to 136 about 25 seconds later.
SEP_24 = _ride((1740, 136, 250), (2, 186, 250), (2, 197, 250), (2, 191, 250), (2, 181, 250),
               (26, 150, 0), (60, 136, 250))  # fmt: skip


def test_24_seps_jump_is_found() -> None:
    from src.services.heart_rate_jump import find_heart_rate_jump

    jump = find_heart_rate_jump(SEP_24)
    assert jump is not None
    assert (jump.from_bpm, jump.to_bpm, jump.above_max) == (136, 197, False)
    assert jump.seconds <= 6 and jump.at_minute == 28


def test_a_strap_that_lost_contact_a_sprint_or_a_slow_climb_is_not_a_jump() -> None:
    from src.services.heart_rate_jump import find_heart_rate_jump

    dropout = _ride((600, 140, 200), (4, 95, 200), (600, 140, 200))
    sprint = _ride((600, 136, 150), (4, 170, 420), (60, 165, 200))
    climb = _ride((600, 120, 180), *[(4, 120 + step, 180 + step) for step in range(1, 46)])
    for ride in (dropout, sprint, climb):
        assert find_heart_rate_jump(ride) is None


def test_a_heart_rate_well_past_his_recorded_maximum_is_one() -> None:
    from src.services.heart_rate_jump import find_heart_rate_jump, recorded_max_bpm

    climb = _ride((600, 150, 250), *[(4, 150 + step, 250) for step in range(1, 30)])
    assert find_heart_rate_jump(climb) is None
    jump = find_heart_rate_jump(climb, recorded_max_bpm=160)
    assert jump is not None and jump.above_max and jump.to_bpm == 171
    # His maximum: the highest ride's, unless it stands far above the rest, as 197 did.
    assert recorded_max_bpm([150] * 19) is None
    assert recorded_max_bpm([150] * 19 + [160]) == 160
    assert recorded_max_bpm([150] * 18 + [160, 197]) == 160
    assert recorded_max_bpm([150] * 18 + [160, 170]) == 170


def test_home_asks_once_and_eases_the_hard_session_like_a_note() -> None:
    from src.services.notes_reader import NotesEffects, with_ride_jump
    from src.services.symptom_check import ASK_SOURCE_RIDE, ride_jump_words

    words = ride_jump_words(
        from_bpm=136,
        to_bpm=197,
        seconds=6,
        above_max=False,
        ride_date=date(2026, 9, 24),
        today=date(2026, 9, 25),
    )
    assert words == (
        "On yesterday’s ride your heart rate jumped from 136 to 197 in 6 seconds, with no "
        "change in your power"
    )
    jump = {"rideDate": "2026-09-24", "fromBpm": 136, "toBpm": 197}
    effects = with_ride_jump(NotesEffects(status="no_notes"), jump=jump, words=words)
    assert (effects.ask_symptom_question, effects.chest_question) == (True, True)
    assert (effects.ask_source, effects.symptom_answer) == (ASK_SOURCE_RIDE, None)
    # The brief can quote its figures: they are in the packet as numbers.
    assert effects.to_packet()["rideJump"]["toBpm"] == 197
    # A note that already asks keeps its own question; the jump is still recorded.
    noted = NotesEffects(status="read", ask_symptom_question=True, ask_words="heartburn")
    kept = with_ride_jump(noted, jump=jump, words=words)
    assert (kept.ask_words, kept.ask_source, kept.ride_jump) == ("heartburn", "note", jump)
    assert with_ride_jump(noted, jump=None, words=None) is noted


def test_the_ride_line_is_the_cards_own() -> None:
    from pathlib import Path

    from src.services.symptom_check import (
        ASK_SOURCE_RIDE,
        RIDE_JUMP_QUESTION,
        chest_question_line,
        ride_jump_words,
    )

    words = ride_jump_words(
        from_bpm=150, to_bpm=182, seconds=0, above_max=True, ride_date=date(2026, 11, 4),
        today=date(2026, 11, 4),
    )  # fmt: skip
    assert words == (
        "On today’s ride your heart rate reached 182, higher than on any ride you’ve recorded"
    )
    assert chest_question_line(words, ASK_SOURCE_RIDE) == (
        f"{words}. Did you feel anything? Until you answer, today’s hard session is an easy ride."
    )
    web = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib" / "notesAsk.ts"
    assert f"'{RIDE_JUMP_QUESTION}'" in web.read_text(encoding="utf-8")


def test_a_note_that_says_his_heart_rate_jumped_asks_too() -> None:
    """The reader calls any figure "data talk"; "HR shot to 190" asked nothing (HS361-05)."""

    from src.services.notes_reader import heart_rate_reported, post_session_effects
    from tests.test_batch_297_notes_reader import _flag, _reading
    from tests.test_batch_339_symptom_anywhere import _Entry, _Reading

    assert heart_rate_reported("HR shot to 190 on an easy spin, strap probably dry.") == (
        "HR shot to 190 on an easy spin, strap probably dry"
    )
    assert heart_rate_reported("My heart rate wouldn't come down after the last one") == (
        "heart rate wouldn't come down after the last one"
    )
    for plain in ("HR drifted up in the heat", "HR zones felt right", "Legs heavy, HR low"):
        assert heart_rate_reported(plain) is None
    entry = _Entry("HR shot to 190 on an easy spin, strap probably dry.")
    reading = _Reading(entry, _reading(chest_heart=_flag("absent")))
    _records, floor, question, _unread = post_session_effects([entry], [reading])  # type: ignore[list-item]
    assert (floor, question) == (None, "HR shot to 190 on an easy spin, strap probably dry")


def test_the_brief_is_told_where_the_question_came_from() -> None:
    from src.services.morning_analysis import SYMPTOM_ANYWHERE_RULE

    rule = " ".join(SYMPTOM_ANYWHERE_RULE.split())
    assert "or ride (the app saw his heart rate jump on a ride" in rule
    assert "never call a ride's jump a sensor glitch or the strap" in rule


@pytest.mark.asyncio
async def test_on_postgres_the_morning_finds_yesterdays_jump_in_the_stored_trace(
    db_conn: Any,
) -> None:
    import uuid
    from datetime import timedelta

    from src.models.coaching import Activity, ActivityTimeSeries
    from src.models.profile import Profile, UserRole
    from src.services.morning_analysis import MorningAnalysisService
    from tests.test_batch_302_stored_morning import _savepoint_session

    session = _savepoint_session(db_conn)
    player = Profile(
        id=uuid.uuid4(),
        display_name="Ride Jump",
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )
    session.add(player)
    await session.flush()
    # Twenty earlier rides that never passed 160, then 24 Sep's.
    for day in range(20):
        session.add(
            Activity(
                id=uuid.uuid4(),
                user_id=player.id,
                garmin_activity_id=8_370_000 + day,
                activity_name="Zwift",
                activity_type="indoor_cycling",
                start_utc=datetime(2026, 8, 1, 17) + timedelta(days=day),
                duration_sec=3600,
                max_heart_rate_bpm=150 + day // 2,
                raw_summary={},
            )
        )
    ride_id = uuid.uuid4()
    session.add(
        Activity(
            id=ride_id,
            user_id=player.id,
            garmin_activity_id=8_370_100,
            activity_name="Zwift",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 9, 24, 17),
            duration_sec=1900,
            max_heart_rate_bpm=197,
            raw_summary={},
        )
    )
    await session.flush()
    for index, (t, hr, power) in enumerate(SEP_24):
        session.add(
            ActivityTimeSeries(
                id=uuid.uuid4(),
                activity_id=ride_id,
                sample_index=index,
                elapsed_sec=t,
                heart_rate_bpm=hr,
                power_watts=power,
                raw_metrics={},
            )
        )
    await session.flush()

    service = MorningAnalysisService(session)
    found = await service._ride_heart_rate_jump(player, date(2026, 9, 25))
    assert found is not None
    jump, ride_day, ended = found
    assert (jump.from_bpm, jump.to_bpm, ride_day) == (136, 197, date(2026, 9, 24))
    assert ended == datetime(2026, 9, 24, 17) + timedelta(seconds=1900)
    # Two mornings on, the ride is no longer the morning's to ask about.
    assert await service._ride_heart_rate_jump(player, date(2026, 9, 27)) is None
    await session.close()
