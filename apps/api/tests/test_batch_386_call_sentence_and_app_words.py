"""Batch 386 — the brief's call finishes its sentence and keeps the app's words out.

Mark's first v70 brief (11 Nov) passed every check after one repair, yet its "Because…"
sentence stopped after saying why ("Because … sit inside your usual ranges, with nothing
marked off."), and it carried the app's own phrases for what it was given and did. These tests
use invented text only (the repository is public): the shapes are the stored ones, the words
and figures are not Mark's.
"""

from __future__ import annotations

import pytest

from src.services.brief_check import (
    MISS_CALL_SENTENCE,
    MISS_ENGINE_WORDS,
    MISSES,
    because_without_main_clause,
    check_brief,
)
from src.services.coach_sections import thermal_review
from src.services.plain_words_repair import OUTCOME_REJECTED, OUTCOME_REPAIRED, repair_brief
from tests.test_batch_318_brief_leads import GOOD, PACKET
from tests.test_batch_369_plain_words import _call

# -- 386.2: a "Because…" sentence with no main clause ----------------------------------------

WHOLE = [
    # The common shapes among the stored whole sentences, invented.
    "Because your numbers are all within your usual range, the ride stands as planned.",
    "Because your HRV, heart rate and sleep all sit inside your usual ranges, the ride goes ahead.",
    "Because it's your rest day and those numbers held steady, today really is a day off.",
    "Because your heart readings dipped and the night graded only fair, today counts two things "
    "as a little off.",
    "Because sleep was the one thing clearly off, confirmed by your check-in as leaving you less "
    "rested, the hard efforts are off today.",
    "Because your recovery week already has the session light, nothing further needs changing.",
    "Because your numbers are all within your usual range, today's easy ride stands as planned, "
    "nothing held back.",
    "Because your numbers sit inside your usual range - the ride stands as planned.",
    "Because your numbers sit inside your usual range—the ride stands as planned.",
    "Because your numbers sit inside your usual range; the ride stands as planned.",
]
HALF = [
    # 1 Nov and 11 Nov: why, then a tail with no verb of its own.
    "Because your numbers are all sitting inside your usual range, with nothing flagged in "
    "your recovery, sleep or load.",
    "Because your HRV, heart rate and sleep all sit inside your own usual ranges this morning, "
    "with nothing flagged.",
    "Because your numbers are all within your usual range.",
    "Because your numbers are within your usual range, and nothing else.",
]


def _call_text(sentence: str) -> str:
    return f"Green light · Recovered\n\nYour HRV came in at 49. {sentence} This would change it: x."


@pytest.mark.parametrize("sentence", WHOLE)
async def test_a_whole_because_sentence_is_not_flagged(sentence: str) -> None:
    assert because_without_main_clause(_call_text(sentence)) is None


@pytest.mark.parametrize("sentence", HALF)
async def test_a_because_sentence_with_no_main_clause_is_flagged(sentence: str) -> None:
    assert because_without_main_clause(_call_text(sentence)) == sentence


async def test_a_call_with_no_because_sentence_is_the_call_shape_checks_to_judge() -> None:
    assert (
        because_without_main_clause("Green light\n\nThis would change it: a rough night.") is None
    )


async def test_the_sentence_ends_at_the_next_sentence_not_at_a_figure() -> None:
    text = _call_text("Because the room peaked at 19.7°C and your HRV held, the ride stands.")
    assert because_without_main_clause(text) is None
    half = _call_text("Because the room peaked at 19.7°C, with Zone 2 ahead.")
    assert (
        because_without_main_clause(half) == "Because the room peaked at 19.7°C, with Zone 2 ahead."
    )


async def test_a_bulleted_or_bold_because_is_found() -> None:
    assert because_without_main_clause("**Because** your numbers hold, the ride stands.") is None
    assert (
        because_without_main_clause("- Because your numbers hold, with nothing flagged.")
        == "Because your numbers hold, with nothing flagged."
    )


async def test_the_check_names_an_unfinished_call_sentence() -> None:
    half = GOOD.replace(
        "Because\neverything sits inside your usual range, the session is on as written.",
        "Because everything sits inside your usual range, with nothing flagged.",
    )
    assert half != GOOD
    result = check_brief(PACKET, half)
    assert result.misses == (MISS_CALL_SENTENCE,)
    assert result.incomplete_call_sentence == (
        "Because everything sits inside your usual range, with nothing flagged."
    )
    assert result.to_packet()["incompleteCallSentence"] == result.incomplete_call_sentence
    assert MISS_CALL_SENTENCE in MISSES


async def test_a_whole_brief_still_passes() -> None:
    result = check_brief(PACKET, GOOD)
    assert result.passed
    assert result.incomplete_call_sentence is None


async def test_an_unfinished_sentence_is_repaired_with_one_call_that_asks_for_the_clause() -> None:
    half = GOOD.replace(
        "Because\neverything sits inside your usual range, the session is on as written.",
        "Because everything sits inside your usual range, with nothing flagged.",
    )
    seen, call = _call(GOOD)
    text, record = await repair_brief(PACKET, half, call=call)
    assert (text, record["outcome"]) == (GOOD.strip(), OUTCOME_REPAIRED)
    assert record["misses"] == [MISS_CALL_SENTENCE]
    ask = " ".join(seen[0].split())
    assert 'the sentence that begins "Because" has no main clause' in ask
    assert "what it means for today's session" in ask


async def test_a_repair_that_leaves_the_sentence_unfinished_is_not_kept() -> None:
    half = GOOD.replace(
        "Because\neverything sits inside your usual range, the session is on as written.",
        "Because everything sits inside your usual range, with nothing flagged.",
    )
    _seen, call = _call(half)
    text, record = await repair_brief(PACKET, half, call=call)
    assert (text, record["outcome"]) == (half, OUTCOME_REJECTED)
    assert "missesLeft" in record["failed"]


# -- 386.4: the app's phrases, as phrases ---------------------------------------------------

PHRASES = [
    "Your pre-bed cool-down is credited: the room reached 19.1°C before sleep.",
    "The pre-cool is credited rather than called a miss.",
    "The app has credited that cooling, even though it stopped above target.",
    "That cooling is recorded as credited.",
    "The credited pre-cool counts toward the night.",
    "That counts as cooling done, not a miss.",
    "It is a pre-cool miss only on paper.",
    "Today's easy ride stands as planned, targets held.",
    "With nothing marked off in your recovery, sleep or load.",
    "Collagen reintroduction: still gated, on hold.",
    "You need three more clean nights to clear the gate.",
    "The retry gate hasn't been met.",
    "Your gate needs 7 straight nights.",
    "There is no rearrange proposal in this read.",
    "That is the targets-held reading.",
]
ORDINARY = [
    "REM has repeatedly missed its age norm across your last 28 nights.",
    "Power target held at normal level; the fade was small.",  # a ride, not the app's phrase
    "The pre-cool target was missed, and the room stayed warm.",
    "Age credit lifts your sleep score a few points.",
    "Credit goes to a good night's sleep.",
    "A clear miss of the pre-cool target, with the room at 20.4°C.",
    "Your recovery week is marked in the plan.",
    "A miss of two nights is nothing to worry about.",
]


@pytest.mark.parametrize("text", PHRASES)
async def test_the_apps_phrase_is_an_engine_word_miss(text: str) -> None:
    brief = GOOD.replace("## Sleep and recovery\n", f"## Sleep and recovery\n{text}\n")
    result = check_brief(PACKET, brief)
    assert MISS_ENGINE_WORDS in result.misses, text
    assert result.engine_words


@pytest.mark.parametrize("text", ORDINARY)
async def test_ordinary_english_is_not_an_app_phrase(text: str) -> None:
    brief = GOOD.replace("## Sleep and recovery\n", f"## Sleep and recovery\n{text}\n")
    result = check_brief(PACKET, brief)
    assert MISS_ENGINE_WORDS not in result.misses, (text, result.engine_words)


async def test_the_phrase_is_named_to_the_repair_as_written() -> None:
    brief = GOOD.replace(
        "## Sleep and recovery\n", "## Sleep and recovery\nYour pre-cool is credited: it worked.\n"
    )
    seen, call = _call(GOOD)
    text, record = await repair_brief(PACKET, brief, call=call)
    assert record["misses"] == [MISS_ENGINE_WORDS]
    assert "Remove the words: pre-cool is credited." in seen[0]
    assert (text, record["outcome"]) == (GOOD.strip(), OUTCOME_REPAIRED)


async def test_the_phrase_is_looked_for_in_the_text_as_mark_reads_it() -> None:
    brief = GOOD.replace(
        "## Sleep and recovery\n", "## Sleep and recovery\nThe pre-cool is **credited** here.\n"
    )
    # Bold markers sit between the words; the check reads the markdown as written, so this
    # shape is a known gap that the measurement over stored briefs did not need (the stored
    # hits all had the phrase unbroken, bar "pre-cool is **credited" which still matches).
    assert MISS_ENGINE_WORDS in check_brief(PACKET, brief).misses


# -- 386.5: room temperatures to one decimal ------------------------------------------------


class _Reading:
    def __init__(self, day: int, at_hour: int, temperature_c: float) -> None:
        from datetime import datetime

        self.captured_at_utc = datetime(2026, 11, day, at_hour, 0)
        self.temperature_c = temperature_c


async def test_the_rooms_temperatures_are_carried_to_one_decimal() -> None:
    from datetime import datetime

    rows = [
        _Reading(10, 20, 20.46),
        _Reading(10, 21, 19.0),
        _Reading(10, 22, 18.94),
        _Reading(10, 23, 18.82),
        _Reading(11, 2, 19.15),
        _Reading(11, 4, 16.15),
        _Reading(11, 6, 16.15),
    ]
    # Asleep from 00:30 to 07:00; the evening readings before it are the pre-cool.
    sleep = type(
        "S",
        (),
        {
            "sleep_start_utc": datetime(2026, 11, 11, 0, 30),
            "sleep_end_utc": datetime(2026, 11, 11, 7, 0),
        },
    )()
    review = thermal_review(rows, None, {}, sleep=sleep)  # type: ignore[arg-type]
    for key in (
        "indoorPeakC",
        "indoorLowC",
        "indoorLastC",
        "preCoolLowC",
        "sleepOnsetC",
        "preCoolDropC",
    ):
        value = review[key]
        assert value is None or value == round(value, 1), (key, value)
    assert review["preCoolDropC"] is not None
    assert review["preCoolDropC"] < 3  # no float noise such as 0.4599999999999973


async def test_rounding_moves_no_flag() -> None:
    from datetime import datetime

    # A pre-cool low of 19.46 is under the 19.5 floor, so it is credited; rounded to 19.5 it
    # would not be. The flag is set from the readings, before the figures are rounded.
    rows = [_Reading(11, 22, 19.46)]
    sleep = type(
        "S",
        (),
        {
            "sleep_start_utc": datetime(2026, 11, 11, 23, 0),
            "sleep_end_utc": datetime(2026, 11, 12, 7, 0),
        },
    )()
    review = thermal_review(rows, None, {}, sleep=sleep)  # type: ignore[arg-type]
    assert "precool_credited" in review["flags"]
    assert review["preCoolLowC"] == 19.5


# -- 386.3 / 386.6: the reworded rules, the version and the experiment lines ----------------


def test_the_calls_instruction_asks_for_what_the_sentence_means_for_today() -> None:
    from src.services.morning_output_contract import TODAYS_CALL_INSTRUCTION

    text = " ".join(TODAYS_CALL_INSTRUCTION.split())
    assert 'begins "Because", says why in his words, and ends with what that means' in text
    assert "today's session" in text
    assert "the ride stands as planned" in text


def test_the_morning_prompt_no_longer_hands_the_brief_the_apps_words() -> None:
    from src.services import morning_analysis

    prompt = " ".join(morning_analysis.SYSTEM_PROMPT.split())
    assert morning_analysis.PROMPT_VERSION == "morning-analysis-v71-2026-11-11"
    # Phrases the check looks for must not be the prompt's own instruction to the brief.
    for phrase in ("targets held", "explicitly credit", "human-gated", "state the first supplied"):
        assert phrase not in prompt, phrase
    # The words that stay are the ones the check names as never to be said.
    assert 'Never say "credited", "credit" or "a miss"' in prompt
    assert 'never "marked off"' in prompt
    assert 'Never say "gate" or "gated" about an experiment' in prompt
    assert "at its planned power and length" in prompt


def test_the_experiment_section_asks_for_the_plain_sentence() -> None:
    from src.services.morning_output_contract import required_morning_output_sections

    packet = {"experimentLoop": {"experiments": [{"id": "x"}]}}
    section = next(
        s for s in required_morning_output_sections(packet) if s.section_id == "experiment_update"
    )
    assert "plain.summary" in section.instruction
    assert "reason" not in section.instruction


def _row(kind: str, status: str, recommendation: str | None, evidence: dict[str, object]):  # type: ignore[no-untyped-def]
    return {
        "id": "e1",
        "title": "Collagen",
        "evaluation": {
            "slug": "collagen",
            "kind": kind,
            "status": status,
            "recommendation": recommendation,
            "sampleCount": 9,
            "evidence": evidence,
            "reasons": ["collagen: gate not yet met (r=0.2, interval [-0.1, 0.5])"],
        },
    }


def test_the_brief_sees_the_plain_sentence_and_not_the_reasons_or_ranges() -> None:
    from src.services.experiment_loop import brief_experiment

    row = _row(
        "gate",
        "ok",
        "inconclusive",
        {"currentStreak": 3, "gateNights": 7, "floor": 74, "interval": [-0.1, 0.5]},
    )
    shown = brief_experiment(row)
    assert "reasons" not in shown["evaluation"] and "evidence" not in shown["evaluation"]
    assert shown["evaluation"]["slug"] == "collagen"
    assert shown["evaluation"]["recommendation"] == "inconclusive"
    assert shown["title"] == "Collagen"
    plain = shown["plain"]
    assert set(plain) == {"outcomeLabel", "summary"}
    assert plain["summary"] == (
        "Your age-adjusted sleep score has stayed at or above 74 for 3 nights in a row so far; "
        "the target is 7 nights in a row."
    )
    assert "gate" not in str(plain).lower()
    assert "reasons" in row["evaluation"]  # the input is not changed


def test_a_plain_sentence_the_page_cannot_build_is_null_not_the_technical_line() -> None:
    from src.services.experiment_loop import brief_experiment

    assert brief_experiment(_row("gate", "ok", "inconclusive", {}))["plain"]["summary"] is None
