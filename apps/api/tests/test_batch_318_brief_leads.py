"""Batch 318: the brief leads with the call, and is checked.

318.2 the call section first, under 120 words, with a "because", a "this would change it"
and a "tonight"; 318.3 a deterministic check of every written brief that reaches Craig on a
miss and never blocks; 318.4 an eval of stored mornings scored by that check, pinned to the
prompt, whose paid run is Craig's go. Each test failed on ``main`` first.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.services import brief_eval, morning_analysis
from src.services.admin_alerts import KIND_BRIEF_CHECK
from src.services.brief_check import (
    MISS_CALL_NOT_FIRST,
    MISS_CALL_OPENING,
    MISS_CALL_TOO_LONG,
    MISS_COLOUR_WORDS,
    MISS_UNKNOWN_FIGURES,
    check_brief,
)
from src.services.morning_output_contract import (
    CALL_SECTION_MAX_WORDS,
    CALL_SECTION_TARGET_WORDS,
    TODAYS_CALL_INSTRUCTION,
    morning_output_contract_packet,
    morning_output_contract_prompt,
)
from tests.test_batch_302_stored_morning import (
    DAY,
    _profile,
    _RecordingClient,
    _stored,
    _writing_service,
)

PACKET: dict[str, Any] = {
    "todaysCall": {"headline": "Green light", "readingWords": "Recovered", "key": "green_light"},
    "verdict": {"status": "Green"},
    "dailyMetrics": {"hrvLastNightAvgMs": 49, "restingHeartRateBpm": 45},
    "sleep": {"score": 82},
    "acutePhysiology": {"overnightHrv": {"usualMs": 46.5}},
}

GOOD = """## Today's call
Green light · Recovered

Your HRV was 49 ms against a usual 47 ms, and your resting heart rate 45 bpm. Because
everything sits inside your usual range, the session is on as written. This would change
it: a short night or a heart rate up two mornings. Tonight: lights out by 22:30.

## Sleep and recovery
A sleep score of 82.
"""


# -- 318.2: the call leads, and is short -----------------------------------------------------


def test_the_call_section_is_first_and_asks_for_the_short_shape() -> None:
    contract = morning_output_contract_packet({"verdict": {"status": "Green"}, "sleep": {"x": 1}})
    assert [section["id"] for section in contract] == ["todays_call", "sleep_and_recovery"]
    for words in (
        f"about {CALL_SECTION_TARGET_WORDS} words",
        f"never more than {CALL_SECTION_MAX_WORDS}",
        '"Because"',
        '"This would change it:"',
        '"Tonight:"',
        "Never write Green, Amber, Red or verdict.",
        "todaysCall.headline and todaysCall.readingWords exactly as they are stored",
    ):
        assert words in TODAYS_CALL_INSTRUCTION, words
    prompt = morning_output_contract_prompt({"verdict": {"status": "Green"}})
    assert prompt.index("## Today's call") < len(prompt)
    assert morning_analysis.PROMPT_VERSION == "morning-analysis-v64-2026-10-29"


# -- 318.3: the check ------------------------------------------------------------------------


def test_a_brief_in_the_new_shape_passes() -> None:
    check = check_brief(PACKET, GOOD)
    assert check.passed, check
    assert check.call_words is not None and check.call_words <= CALL_SECTION_MAX_WORDS


def test_the_old_shape_misses_first_place_and_length() -> None:
    old = "## Sleep and recovery\nFine.\n\n## Today's call\nGreen light · Recovered\n" + (
        "word " * 130
    )
    assert check_brief(PACKET, old).misses == (MISS_CALL_NOT_FIRST, MISS_CALL_TOO_LONG)


def test_a_call_that_drifts_from_the_stored_one_is_a_miss() -> None:
    drifted = GOOD.replace("Green light · Recovered", "Take the edge off · Some fatigue")
    assert MISS_CALL_OPENING in check_brief(PACKET, drifted).misses


def test_easy_riding_only_needs_no_reading_word() -> None:
    """Batch 339 hides the chip under this call, so the brief need not quote it."""
    packet = {
        **PACKET,
        "todaysCall": {
            "headline": "Easy riding only",
            "readingWords": "Recovered",
            "key": "easy_riding_only",
        },
    }
    brief = GOOD.replace("Green light · Recovered", "Easy riding only")
    assert MISS_CALL_OPENING not in check_brief(packet, brief).misses
    assert '"Easy riding only", the headline alone' in TODAYS_CALL_INSTRUCTION


def test_colour_words_are_a_miss_but_the_stored_headline_is_not() -> None:
    assert MISS_COLOUR_WORDS not in check_brief(PACKET, GOOD).misses  # "Green light"
    coloured = GOOD.replace("the session is on", "the verdict is Amber and the session is on")
    check = check_brief(PACKET, coloured)
    assert MISS_COLOUR_WORDS in check.misses
    assert check.colour_words == ("Amber", "verdict")


def test_a_figure_the_morning_never_held_is_a_miss_and_rounding_is_not() -> None:
    # 47 ms rounds the packet's 46.5 up; 45 bpm and score 82 are held.
    assert MISS_UNKNOWN_FIGURES not in check_brief(PACKET, GOOD).misses
    invented = GOOD.replace("49 ms", "53 ms").replace("score of 82", "score of 88")
    check = check_brief(PACKET, invented)
    assert MISS_UNKNOWN_FIGURES in check.misses
    assert check.unknown_figures == ("53 ms", "score 88")


@pytest.mark.asyncio
async def test_a_miss_reaches_craig_is_stored_and_never_blocks_the_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts: list[dict[str, Any]] = []

    def _alert(_logger: Any, event: str, *, kind: str, **fields: Any) -> None:
        alerts.append({"event": event, "kind": kind, **fields})

    monkeypatch.setattr(morning_analysis, "admin_alert", _alert)
    stored = _stored()
    service, _session, _claims = _writing_service(monkeypatch, stored)

    result = await service.write_brief(_profile(), DAY, client=_RecordingClient())

    assert result.generated is True  # written, whatever the check found
    assert stored.output_markdown == "**Verdict:** Red."
    check = stored.raw_response[morning_analysis.BRIEF_CHECK_KEY]
    assert check["passed"] is False
    assert MISS_CALL_NOT_FIRST in check["misses"]
    [alert] = alerts
    assert (alert["event"], alert["kind"]) == ("morning_brief_check_missed", KIND_BRIEF_CHECK)
    assert alert["subject_date"] == DAY.isoformat()


@pytest.mark.asyncio
async def test_a_brief_that_passes_raises_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(
        morning_analysis, "admin_alert", lambda *_args, **_kwargs: alerts.append("x")
    )
    stored = _stored(context_packet={**_stored().context_packet, **PACKET})
    service, _session, _claims = _writing_service(monkeypatch, stored)

    await service.write_brief(_profile(), DAY, client=_RecordingClient(markdown=GOOD))

    assert stored.raw_response[morning_analysis.BRIEF_CHECK_KEY]["passed"] is True
    assert alerts == []


# -- 318.4: the eval -------------------------------------------------------------------------


def test_the_eval_answers_todays_prompt_or_awaits_craigs_go() -> None:
    """The gate itself: no recording until Craig's go; once there is one, it must answer
    today's prompt and hold the gate."""
    recording = brief_eval.load_recording()
    if recording is None:
        assert "Craig's go" in brief_eval.RUN_THE_EVAL
        return
    reason = brief_eval.stale_recording_reason(recording)
    assert reason is None, f"{reason} {brief_eval.RUN_THE_EVAL}"
    assert brief_eval.gate_failures(recording) == []


def _recording(**cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "promptVersion": morning_analysis.PROMPT_VERSION,
        "promptFingerprint": brief_eval.prompt_fingerprint(),
        "cases": cases,
    }


def test_the_recording_is_pinned_to_the_prompts_words() -> None:
    recording = _recording(a=[{"misses": []}])
    assert brief_eval.stale_recording_reason(recording) is None
    assert "now sends" in str(
        brief_eval.stale_recording_reason({**recording, "promptVersion": "morning-analysis-v62"})
    )
    assert "changed" in str(
        brief_eval.stale_recording_reason({**recording, "promptFingerprint": "0" * 64})
    )


def test_the_gate_fails_a_colour_or_an_invented_figure_and_too_few_clean_cases() -> None:
    clean = {f"c{i}": [{"misses": []}] for i in range(9)}
    assert brief_eval.gate_failures(_recording(**clean, z=[{"misses": ["call_too_long"]}])) == []
    hard = brief_eval.gate_failures(_recording(**clean, z=[{"misses": [MISS_COLOUR_WORDS]}]))
    assert hard == ["z: colour_words."]
    long = {f"l{i}": [{"misses": ["call_too_long"]}] for i in range(3)}
    assert brief_eval.gate_failures(_recording(**clean, **long))[-1].startswith("9 of 12")


def test_the_cases_cover_every_call_first() -> None:
    mornings = [{"todaysCall": {"key": key}, "id": i} for i, key in enumerate("aabbbc")]
    chosen = brief_eval.select_cases(mornings, count=4)
    assert [item["todaysCall"]["key"] for item in chosen] == ["a", "b", "c", "a"]


def test_the_eval_costs_what_it_counts() -> None:
    assert brief_eval.estimated_cost_usd(409_391, 48_360, (2.0, 10.0)) == pytest.approx(1.30, 0.01)
