"""Batch 377 — 369's follow-up: the app places the readiness line, and checks the engine words.

369's fourth replay passed 4 of 5 mornings. On 28 Oct the brief put the readiness line
inside the call, against ``READINESS_TREND_RULE``, and on 1 Nov said it again when it was
not due; "autonomic" and "domain" survived v67's two rules against them; asked to trim to
110 words, the fix-up call left 2 of 6 long calls over 120; and 3 of the 4 fix-ups kept
dropped the call's "Because" or "This would change it:" opening.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.services import morning_analysis
from src.services.brief_check import (
    CALL_OPENINGS,
    MISS_CALL_SHAPE,
    MISS_ENGINE_WORDS,
    MISS_READINESS_IN_CALL,
    MISSES,
    check_brief,
)
from src.services.morning_output_contract import place_readiness_line, strip_readiness_line
from src.services.plain_words_repair import (
    BRIEF_REPAIR_SYSTEM_PROMPT,
    CALL_TRIM_WORDS,
    OUTCOME_REJECTED,
    OUTCOME_REPAIRED,
    finish_brief,
    repair_brief,
)
from tests.test_batch_302_stored_morning import (
    DAY,
    _profile,
    _RecordingClient,
    _stored,
    _writing_service,
)
from tests.test_batch_318_brief_leads import GOOD, PACKET
from tests.test_batch_369_plain_words import _call

SENTENCE = (
    "Your readiness has run lower for six weeks: usually 66 lately, against 72 the six weeks "
    "before. It still shows with your days away left out (67 against 72)."
)


def _packet(*, say: bool, triggered: bool = True) -> dict[str, Any]:
    trend = {
        "triggered": triggered,
        "say": say,
        "usualBefore": 72,
        "usualRecent": 66,
        "sentence": SENTENCE if triggered else None,
    }
    return {**PACKET, "verdict": {**PACKET["verdict"], "readinessBaselineTrend": trend}}


def _section(markdown: str, heading: str) -> str:
    start = markdown.index(f"## {heading}")
    end = markdown.find("\n## ", start + 3)
    return markdown[start : end if end != -1 else len(markdown)]


CALL_END = GOOD.index("\n## Sleep")
#: 28 Oct's shape: the brief gave the app's line word for word inside the call.
INSIDE = GOOD[:CALL_END] + f"\n\n{SENTENCE}\n" + GOOD[CALL_END:]


# -- 377.1: the app writes the readiness line itself ----------------------------------------


def test_the_line_moves_out_of_the_call_to_the_first_line_under_the_next_heading() -> None:
    placed = place_readiness_line(_packet(say=True), INSIDE)

    assert SENTENCE not in _section(placed, "Today's call")
    assert _section(placed, "Sleep and recovery").startswith(
        f"## Sleep and recovery\n{SENTENCE}\n\nA sleep score of 82."
    )
    assert placed.count(SENTENCE) == 1
    # The call Mark reads is the call: every word under its heading counts again.
    assert check_brief(_packet(say=True), placed).call_words == check_brief(PACKET, GOOD).call_words
    assert check_brief(_packet(say=True), placed).passed
    # Placing twice is placing once.
    assert place_readiness_line(_packet(say=True), placed) == placed


def test_a_line_that_is_not_due_is_never_shown_and_a_due_one_is_placed_unasked() -> None:
    """1 Nov: the brief said it again when it had not moved."""

    elsewhere = GOOD + f"\n{SENTENCE}\n"
    assert SENTENCE not in place_readiness_line(_packet(say=False), elsewhere)
    assert place_readiness_line(_packet(say=False), GOOD) == GOOD
    # On a due morning the brief need not write it at all.
    assert SENTENCE in _section(place_readiness_line(_packet(say=True), GOOD), "Sleep and recovery")


def test_a_copy_goes_cleanly_with_its_bold_its_bullet_or_from_inside_a_paragraph() -> None:
    bullet = GOOD + f"\n- **{SENTENCE}**\n- A second point.\n"
    stripped = strip_readiness_line(_packet(say=False), bullet)
    assert SENTENCE not in stripped and "- A second point." in stripped
    assert "\n- \n" not in stripped and "****" not in stripped

    inline = GOOD.replace("A sleep score of 82.", f"A sleep score of 82. {SENTENCE} Rest well.")
    stripped = strip_readiness_line(_packet(say=False), inline)
    assert "A sleep score of 82. Rest well." in stripped

    # A copy wrapped across lines is still a copy.
    wrapped = GOOD + "\n" + SENTENCE.replace(" lately, ", " lately,\n") + "\n"
    assert "six weeks" not in strip_readiness_line(_packet(say=False), wrapped)


def test_his_question_keeps_its_place_straight_after_the_call() -> None:
    asked = GOOD.replace(
        "## Sleep and recovery", "## Your question\nYes, ride.\n\n## Sleep and recovery"
    )
    placed = place_readiness_line(_packet(say=True), asked)
    assert _section(placed, "Your question") == "## Your question\nYes, ride.\n"
    assert _section(placed, "Sleep and recovery").startswith(f"## Sleep and recovery\n{SENTENCE}")


def test_with_no_heading_after_the_call_the_line_ends_the_brief() -> None:
    call_only = GOOD[:CALL_END] + "\n"
    assert place_readiness_line(_packet(say=True), call_only).endswith(f"\n\n{SENTENCE}\n")


def test_no_trend_no_line_and_nothing_touched() -> None:
    for packet in (PACKET, _packet(say=True, triggered=False)):
        assert place_readiness_line(packet, INSIDE) == INSIDE
        assert strip_readiness_line(packet, INSIDE) == INSIDE


def test_the_check_finds_the_trend_said_again_inside_the_call() -> None:
    assert MISS_READINESS_IN_CALL in MISSES
    packet = _packet(say=True)
    reworded = GOOD.replace(
        "Because\neverything",
        "Because your readiness has been lower over six weeks and everything",
    )
    assert MISS_READINESS_IN_CALL in check_brief(packet, reworded).misses
    # Both of the trend's figures beside "readiness" is the trend, however it is put.
    figures = GOOD.replace("Tonight:", "Your readiness has slipped, 66 against 72. Tonight:")
    assert MISS_READINESS_IN_CALL in check_brief(packet, figures).misses
    # Today's readiness against his usual is not the trend.
    today = GOOD.replace("Tonight:", "Your readiness is 54 against a usual 68. Tonight:")
    assert MISS_READINESS_IN_CALL not in check_brief(packet, today).misses
    # And with no trend there is nothing to say again.
    assert MISS_READINESS_IN_CALL not in check_brief(PACKET, reworded).misses


def test_the_prompt_tells_the_brief_never_to_write_it() -> None:
    rule = " ".join(morning_analysis.READINESS_TREND_RULE.split())
    assert "The app adds the six-week readiness trend" in rule
    assert "never write it yourself" in rule
    assert "Today's call included" in rule
    assert "word for word" not in rule
    assert morning_analysis.READINESS_TREND_RULE in morning_analysis.SYSTEM_PROMPT
    assert morning_analysis.PROMPT_VERSION == "morning-analysis-v68-2026-11-04"


@pytest.mark.asyncio
async def test_the_stored_brief_carries_the_line_where_the_app_put_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored(context_packet={**_stored().context_packet, **_packet(say=True)})
    service, _session, _claims = _writing_service(monkeypatch, stored)

    await service.write_brief(_profile(), DAY, client=_RecordingClient(markdown=INSIDE))

    assert SENTENCE not in _section(stored.output_markdown, "Today's call")
    assert SENTENCE in _section(stored.output_markdown, "Sleep and recovery")
    assert stored.raw_response[morning_analysis.BRIEF_CHECK_KEY]["passed"] is True


# -- 377.2: "domain" and "autonomic" are the engine's words ---------------------------------


def test_domain_and_autonomic_are_a_miss() -> None:
    assert MISS_ENGINE_WORDS in MISSES
    assert MISS_ENGINE_WORDS not in check_brief(PACKET, GOOD).misses
    leaky = GOOD.replace(
        "Because\neverything", "Because your autonomic, sleep, load and feel domains and everything"
    )
    check = check_brief(PACKET, leaky)
    assert MISS_ENGINE_WORDS in check.misses
    assert check.engine_words == ("autonomic", "domains")
    assert check.to_packet()["engineWords"] == ["autonomic", "domains"]


async def test_the_fix_up_call_rewords_them_in_his_words() -> None:
    leaky = GOOD + "\nEvery domain sits inside your usual range.\n"
    seen, call = _call(GOOD)
    text, record = await repair_brief(PACKET, leaky, call=call)
    assert (text, record["outcome"]) == (GOOD.strip(), OUTCOME_REPAIRED)
    assert "Remove the words: domain." in seen[0]
    prompt = " ".join(BRIEF_REPAIR_SYSTEM_PROMPT.split())
    assert 'for "domain" or "autonomic", say what it measures' in prompt


# -- 377.3: the trim lands under the limit and keeps the call's shape -----------------------


def test_the_call_must_open_its_reason_and_what_would_change_it() -> None:
    assert MISS_CALL_SHAPE in MISSES
    assert CALL_OPENINGS == ("Because", "This would change it:")
    # GOOD says both, one across a line break ("This would change\nit:").
    assert check_brief(PACKET, GOOD).missing_openings == ()
    bare = GOOD.replace("Because\neverything sits", "Everything sits")
    check = check_brief(PACKET, bare)
    assert MISS_CALL_SHAPE in check.misses
    assert check.missing_openings == ("Because",)
    assert check.to_packet()["missingOpenings"] == ["Because"]
    # "because" inside a sentence is not the opening.
    midway = bare.replace("as written.", "as written because it fits.")
    assert MISS_CALL_SHAPE in check_brief(PACKET, midway).misses


async def test_a_trim_that_drops_an_opening_is_not_kept() -> None:
    assert CALL_TRIM_WORDS == 95
    long_brief = GOOD[:CALL_END] + "\n\nAlso " + " ".join(["and"] * 130) + ".\n" + GOOD[CALL_END:]
    dropped = GOOD.replace("Because\neverything sits", "Everything sits")
    seen, call = _call(dropped)
    text, record = await repair_brief(PACKET, long_brief, call=call)
    assert (text, record["outcome"]) == (long_brief, OUTCOME_REJECTED)
    assert record["failed"] == ["missesLeft"]
    assert MISS_CALL_SHAPE in record["missesAfter"]
    prompt = " ".join(BRIEF_REPAIR_SYSTEM_PROMPT.split())
    assert "at most 95 words" in prompt
    assert '"Because", "This would change it:" and "Tonight:" keep those openings' in prompt


async def test_a_missing_opening_is_asked_for_by_name() -> None:
    bare = GOOD.replace("Because\neverything sits", "Everything sits")
    seen, call = _call(GOOD)
    text, record = await repair_brief(PACKET, bare, call=call)
    assert (text, record["outcome"]) == (GOOD.strip(), OUTCOME_REPAIRED)
    assert 'begin the sentence that says why with "Because"' in seen[0]


async def test_the_trend_said_again_in_the_call_is_taken_out() -> None:
    packet = _packet(say=False)
    reworded = GOOD.replace("Tonight:", "Your readiness has been lower for six weeks. Tonight:")
    seen, call = _call(GOOD)
    text, record = await repair_brief(packet, reworded, call=call)
    assert (text, record["outcome"]) == (GOOD.strip(), OUTCOME_REPAIRED)
    assert "Take the six-week readiness trend out" in seen[0]


# -- the finish: what Mark reads, in production and in the eval -----------------------------


async def test_the_finish_takes_the_copy_out_before_the_repair_and_places_it_after() -> None:
    # The copy made the call long; once it is out the call fits, so no call is made.
    padded = GOOD[:CALL_END] + "\n\n" + " ".join(["word"] * 60) + GOOD[CALL_END:]
    inside = padded[: padded.index("\n## Sleep")] + f"\n\n{SENTENCE}\n" + GOOD[CALL_END:]
    packet = _packet(say=True)
    assert check_brief(packet, inside).call_words > 120  # as the brief wrote it
    seen, call = _call("unused")
    text, record = await finish_brief(packet, inside, call=call)
    assert (seen, record) == ([], {"attempted": False})
    assert SENTENCE in _section(text, "Sleep and recovery")
    assert check_brief(packet, text).passed
    # With no repair call (a test client), the line is still placed.
    text, record = await finish_brief(packet, GOOD, call=None)
    assert SENTENCE in _section(text, "Sleep and recovery") and record == {"attempted": False}


# -- the words Craig signs off ----------------------------------------------------------------

DRAFT = Path(__file__).resolve().parents[3] / "docs" / "drafts" / "2026-11-04-batch-377-wording.md"
DOMAIN_WORDS = (
    'for "domain" or "autonomic", say what it measures: your HRV and resting heart rate, your '
    "sleep, your training load, how you feel"
)


def test_the_words_are_the_drafts() -> None:
    from src.services.morning_verdict import _hrv_floor_rule

    text = DRAFT.read_text(encoding="utf-8").replace("\n> ", " ").replace("**", "")
    draft = " ".join(text.split())
    assert " ".join(morning_analysis.READINESS_TREND_RULE.split()) in draft
    assert _hrv_floor_rule() in draft
    assert DOMAIN_WORDS in draft
    assert DOMAIN_WORDS in " ".join(BRIEF_REPAIR_SYSTEM_PROMPT.split())
    assert f"to at most {CALL_TRIM_WORDS}" in draft
