"""Batch 345: pass-on authority and answer usage stay bounded per turn."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.config import settings
from src.services.anthropic_text import AnthropicApiError, AnthropicTextResult
from src.services.brief_chat import (
    COACH_CHAT_TOOLS,
    FINAL_REPLY_RULE,
    PASS_TO_CRAIG_SUMMARY_MAX,
    PASS_TO_CRAIG_TOOL,
    AnthropicBriefChatClient,
    CoachChatToolbox,
    _answer_usage,
    _build_cached_system_prompt,
    _guard_mark_answer,
    _log_answer_shape,
    _pass_on_acknowledged_error,
    internal_vocabulary_hits,
)
from src.services.chat_context import CoachOrigin
from src.services.coach_policy import PROPOSE_CONFIRM_RULE, floors_sentence
from src.services.plan_conversation import plan_capability_instruction
from src.services.symptom_check import (
    ILLNESS_SYMPTOM_ANSWERS,
    SYMPTOMS_CHEST_HEART,
    SYMPTOMS_FEVER_ACHES,
    SYMPTOMS_HEAD_COLD,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_toolbox", [False, True])
async def test_chat_wall_limit_cancels_a_stalled_answer_and_classifies_it(
    monkeypatch: pytest.MonkeyPatch, with_toolbox: bool
) -> None:
    """A resetting provider read timer cannot leave Mark waiting indefinitely."""
    monkeypatch.setattr(settings, "anthropic_chat_wall_timeout_seconds", 0.01)
    calls = 0
    cancelled = False

    async def stalled_answer(**kwargs: object) -> None:
        nonlocal calls, cancelled
        calls += 1
        try:
            await asyncio.sleep(10)
        finally:
            cancelled = True

    target = (
        "src.services.brief_chat.generate_anthropic_text_with_tools"
        if with_toolbox
        else "src.services.brief_chat.generate_anthropic_text"
    )
    monkeypatch.setattr(target, stalled_answer)
    toolbox = SimpleNamespace(execute=Mock()) if with_toolbox else None
    client = AnthropicBriefChatClient(api_key="test-key")

    with pytest.raises(AnthropicApiError) as caught:
        await client.generate(
            system_prompt="system",
            user_prompt="Why is today easier?",
            prior_messages=[],
            toolbox=toolbox,  # type: ignore[arg-type]
        )

    assert caught.value.reason == "timeout"
    assert caught.value.status_code == 0
    assert calls == 1
    assert cancelled
    assert client.last_usage is None


@pytest.mark.asyncio
async def test_pass_to_craig_uses_server_held_words_and_sends_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alert = Mock()
    monkeypatch.setattr("src.services.brief_chat.admin_alert", alert)
    monkeypatch.setattr(settings, "sentry_dsn_backend", "https://public@o1.ingest.sentry.io/1")
    player = SimpleNamespace(id=uuid.uuid4())
    toolbox = CoachChatToolbox(None, player, "Why does one HRV night count so much?")  # type: ignore[arg-type]

    first = await toolbox.execute(
        tool_use_id="one",
        name="pass_to_craig",
        payload={"summary": "Mark questions the weight of one HRV night."},
    )
    again = await toolbox.execute(
        tool_use_id="two",
        name="pass_to_craig",
        payload={"summary": "Send it twice please."},
    )

    assert first.is_error is False
    assert first.content.startswith("Alert succeeded.")
    assert "first sentence must judge his actual question" in first.content
    assert "judge the size of the cut before correcting" in first.content
    assert "overnight reading at the floor is not below it" in first.content
    assert again.content == "Already passed to Craig this turn."
    alert.assert_called_once()
    assert alert.call_args.kwargs["mark_words"] == "Why does one HRV night count so much?"
    assert alert.call_args.kwargs["coach_summary"] == "Mark questions the weight of one HRV night."
    assert alert.call_args.kwargs["kind"] == "coach_feedback"


@pytest.mark.asyncio
async def test_pass_to_craig_does_not_claim_success_after_alert_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.brief_chat.admin_alert", Mock(side_effect=RuntimeError))
    monkeypatch.setattr(settings, "sentry_dsn_backend", "https://public@o1.ingest.sentry.io/1")
    toolbox = CoachChatToolbox(  # type: ignore[arg-type]
        None, SimpleNamespace(id=uuid.uuid4()), "This looks wrong."
    )
    result = await toolbox.execute(
        tool_use_id="one", name="pass_to_craig", payload={"summary": "Mark reports a wrong call."}
    )
    assert result.is_error
    assert "Do not claim it was sent" in result.content
    assert not toolbox.passed_to_craig


@pytest.mark.asyncio
async def test_pass_to_craig_requires_an_alert_route(monkeypatch: pytest.MonkeyPatch) -> None:
    alert = Mock()
    monkeypatch.setattr(settings, "sentry_dsn_backend", "")
    monkeypatch.setattr("src.services.brief_chat.admin_alert", alert)
    toolbox = CoachChatToolbox(  # type: ignore[arg-type]
        None, SimpleNamespace(id=uuid.uuid4()), "The number is wrong."
    )
    result = await toolbox.execute(
        tool_use_id="one", name="pass_to_craig", payload={"summary": "Mark reports a wrong number."}
    )
    assert result.is_error
    alert.assert_not_called()


def test_pass_to_craig_states_the_summary_limit_it_enforces() -> None:
    """v26: the tool enforced 240 characters without ever saying so.

    In the 21 Oct no-cost replay four of five first pass-on calls were rejected
    for length, and each retry spends one of the answer's three model rounds.
    The description, the field and the executor now read one constant, and the
    schema keeps its shape: no ``maxLength`` was added to the strict tool.
    """
    description = PASS_TO_CRAIG_TOOL["description"]
    schema = PASS_TO_CRAIG_TOOL["input_schema"]
    field = schema["properties"]["summary"]

    assert PASS_TO_CRAIG_SUMMARY_MAX == 240
    assert f"at most {PASS_TO_CRAIG_SUMMARY_MAX} characters" in description
    assert "a longer summary is rejected" in description
    assert f"at most {PASS_TO_CRAIG_SUMMARY_MAX} characters" in field["description"]
    assert "attached by the app, not supplied by you" in description
    assert PASS_TO_CRAIG_TOOL["strict"] is True
    assert schema["required"] == ["summary"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"summary"}
    assert set(field) == {"type", "description"}


@pytest.mark.asyncio
async def test_pass_to_craig_accepts_the_stated_limit_and_rejects_one_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alert = Mock()
    monkeypatch.setattr("src.services.brief_chat.admin_alert", alert)
    monkeypatch.setattr(settings, "sentry_dsn_backend", "https://public@o1.ingest.sentry.io/1")
    words = "Isn't this another over-reaction?"
    over = CoachChatToolbox(None, SimpleNamespace(id=uuid.uuid4()), words)  # type: ignore[arg-type]
    at_limit = CoachChatToolbox(None, SimpleNamespace(id=uuid.uuid4()), words)  # type: ignore[arg-type]

    rejected = await over.execute(
        tool_use_id="one",
        name="pass_to_craig",
        payload={"summary": "a" * PASS_TO_CRAIG_SUMMARY_MAX + "."},
    )
    accepted = await at_limit.execute(
        tool_use_id="two",
        name="pass_to_craig",
        payload={"summary": "a" * (PASS_TO_CRAIG_SUMMARY_MAX - 1) + "."},
    )

    assert rejected.is_error
    assert rejected.content == "Keep the summary to one line (10–240 characters)."
    assert not over.passed_to_craig
    assert accepted.is_error is False
    assert at_limit.passed_to_craig
    alert.assert_called_once()


def test_v26_reply_rule_repairs_the_patterns_the_v25_replay_found() -> None:
    """Decision #424's no-cost replay: one compact edit to the shared final rule.

    Case 5 inferred that Craig's change was not live from what one read left
    out; case 3 explained an unclear line as if its meaning were known and said
    an early night cuts the night short; case 2 argued a cause from when lows
    fell and misdated them; case 7 called an unconfirmed cause benign, kept a
    quartile and left Mark's over-reaction complaint unpassed. A first draft
    stated a REM mechanism and a "missing" test that later answers repeated as
    fact, so the rule now names actions rather than new claims. The private
    answers stay in the ignored scratchpad, so this pins the rules, not words.
    """
    final = " ".join(FINAL_REPLY_RULE.split())

    assert "describe what the visible read does show" in final
    assert "say you cannot tell from it whether a code change produced it" in final
    assert "what a read leaves unsaid is not evidence about the code" in final
    assert "ask him to chase Craig" in final
    assert "contrast the visible read" not in final

    assert "When he asks what a line means or questions your account of one" in final
    assert "give only what its words plainly state" in final
    assert "pass that wording problem to Craig; do not turn the open part into advice" in final
    assert "names neither an earlier bedtime nor a nap, so advise against neither" in final
    assert "same wake time lengthens time in bed" in final
    assert "a wrist estimate" in final
    assert "'catching up early' is unclear" not in final

    assert "Readings show when and how much, not why" in final
    # v27 keeps this for timing alone; a recorded disruption is its exception.
    assert "never treat the timing of low readings alone as proof for or against a cause" in final
    assert "Prefer one current comparison to a dated range" in final
    assert "first and last dates and values from the records" in final

    assert "never call one benign or harmless" in final
    # v29 (Batch 355) restates the statistics words as the brief's plain-words rule does.
    assert "quartile, percentile and standard deviation are words for your reasoning" in final
    assert "app over-reacted" in final
    assert "pass it to Craig even when today's call stands" in final
    assert "if over 100, remove secondary detail" in final

    # Case 6 twice opened by saying his note was there once the code-change rule
    # led with what a read shows; the brief-missed rule now comes first. Asked
    # "whether it did", two of three final-draft runs still answered that the
    # note was not left out and explained how notes are weighed, so the rule
    # opens with the unmet part, as v25's did.
    assert final.index("If he says a brief missed his request") < final.index(
        "If he asks whether Craig's code change has landed"
    )
    assert "open with the part it did not act on, then what it used" in final
    assert "crediting his note is not acting on it" in final
    assert "how the app weighs notes does not answer him" in final
    assert "If it acted on all of it, say where" in final
    assert "whether it did" not in final
    # Three guard rejections in 38 v26 runs: "verdict" twice, a colour once.
    assert "'verdict' or 'verdicts' in any sense (say 'call' or 'diagnosis')" in final
    assert "colour words in any form" in final

    # The draft-1 phrases the replay saw repeated to Mark as if they were facts.
    assert "only waking earlier" not in final
    assert "change is missing" not in final
    assert "first say what the visible read" not in final
    assert internal_vocabulary_hits(final) == ()


def test_v27_reply_rule_leads_with_a_recorded_disruption_and_allows_asked_for_lists() -> None:
    """Mark's 12–19 Oct chats: he had to argue the coach into his obvious holiday.

    v26's "never treat the timing of low readings as proof" gave the very sentence
    he objected to (the holiday's timing "doesn't establish it as the cause"). v27
    keeps that rule for timing alone and makes a recorded disruption its exception,
    without easing the call, its warnings or symptom advice. The plan builder shares
    this rule, and on 13 Oct he asked it to list the plan's VO2 workouts, so a list
    he asks for is allowed while an unrequested one stays out.
    """
    final = " ".join(FINAL_REPLY_RULE.split())

    exception = final.index("A known disruption is the exception")
    assert final.index("Offer causes only as possibilities") < exception
    for disruption in ("a holiday, travel or a night away", "illness", "alcohol", "a late meal"):
        assert disruption in final[exception:]
    assert "in his check-ins, holiday dates or own words" in final
    # Craig, 22 Oct: illness is the app's own illness answers, so a chest or heart
    # report is never offered as the likely, passing cause of a dip.
    assert "illness (a cold, fever or aches, never chest or heart symptoms)" in final
    assert ILLNESS_SYMPTOM_ANSWERS == {SYMPTOMS_HEAD_COLD, SYMPTOMS_FEVER_ACHES}
    assert SYMPTOMS_CHEST_HEART not in ILLNESS_SYMPTOM_ANSWERS
    assert "falls in or just before the days of a dip" in final
    assert "a dip in HRV, resting heart rate, sleep or readiness" in final
    assert "say first and plainly that it is the most likely cause" in final
    assert "Do not argue it down from when the dip began" in final
    assert "or hedge it with causes no record points to" in final
    # Draft 1's "not one possibility among several" came back to Mark almost word for
    # word in 5 of 9 replayed answers, and case 7 argued that his rise began before
    # the flight in 2 of 3; the repair names travel and the days just before.
    assert "one possibility among several" not in final
    assert "fails to prove it" not in final
    assert "back in his usual range within about a week of it ending" in final
    assert "call the dip a concern only if that does not happen" in final
    assert "Today's call, its warnings and any symptom advice still stand" in final
    # What the exception must leave as it was.
    assert "never call one benign or harmless" in final
    assert "two rides at similar power show a heart-rate difference, not its cause" in final
    assert "Keep today's computed training call and safety boundaries intact" in final
    assert "pass it to Craig even when today's call stands" in final
    assert "Do not call the cut excessive" in final

    assert "If he asks for a list or table, give a short one with one line per item" in final
    assert "no headings, lists he did not ask for, colour words" in final
    assert "Count the words before sending, leaving out a list he asked for" in final
    assert "A numbered challenge is not a request for a point-by-point report" in final
    assert internal_vocabulary_hits(final) == ()


def test_the_plan_builder_ends_on_the_shared_final_reply_rule() -> None:
    today = date(2026, 10, 13)
    prompt = _build_cached_system_prompt(
        analysis=None,
        origin=CoachOrigin(kind="next_plan"),
        local_today=today,
        app_state={},
        adjustable_set=None,
        plan_capability=plan_capability_instruction({"planName": "Plan No. 3"}, today=today),
    )

    assert "the plan builder" in prompt[0]["text"]
    assert "Capability for his proposed plan" in prompt[0]["text"]
    assert prompt[-1]["text"] == FINAL_REPLY_RULE


@pytest.mark.asyncio
async def test_explicit_earlier_error_gets_one_server_pass_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 4's failure is repaired without changing the paid prompt candidate."""
    alert = Mock()
    monkeypatch.setattr("src.services.brief_chat.admin_alert", alert)
    monkeypatch.setattr(settings, "sentry_dsn_backend", "https://public@o1.ingest.sentry.io/1")
    toolbox = CoachChatToolbox(  # type: ignore[arg-type]
        None, SimpleNamespace(id=uuid.uuid4()), "Surely that lengthens the night?"
    )
    answer = "You're right: the same wake time makes the night longer. I had that backwards."

    delivered, sent = await _pass_on_acknowledged_error(answer, toolbox)
    again, sent_again = await _pass_on_acknowledged_error(delivered, toolbox)

    assert sent and not sent_again
    assert delivered.startswith(answer)
    assert delivered.endswith("I've passed that correction to Craig.")
    assert again == delivered
    alert.assert_called_once()
    assert alert.call_args.kwargs["mark_words"] == "Surely that lengthens the night?"


@pytest.mark.asyncio
async def test_server_pass_on_does_not_claim_failed_or_unacknowledged_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alert = Mock()
    monkeypatch.setattr("src.services.brief_chat.admin_alert", alert)
    monkeypatch.setattr(settings, "sentry_dsn_backend", "")
    toolbox = CoachChatToolbox(  # type: ignore[arg-type]
        None, SimpleNamespace(id=uuid.uuid4()), "That earlier explanation was wrong."
    )
    answer = "You're right. I had that backwards."

    unchanged, sent = await _pass_on_acknowledged_error(answer, toolbox)
    ordinary, ordinary_sent = await _pass_on_acknowledged_error(
        "You're right about the date.", toolbox
    )

    assert unchanged == answer and not sent
    assert ordinary == "You're right about the date." and not ordinary_sent
    alert.assert_not_called()


def test_chat_tool_and_usage_are_separate_from_read_tools() -> None:
    assert [tool["name"] for tool in COACH_CHAT_TOOLS] == sorted(
        tool["name"] for tool in COACH_CHAT_TOOLS
    )
    assert COACH_CHAT_TOOLS[-1]["name"] == "pass_to_craig"
    result = AnthropicTextResult(
        output_markdown="Yes.",
        raw_response={},
        model_name="claude-sonnet-5",
        api_calls=2,
        tool_uses=1,
        usage={"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 500},
    )
    packet = _answer_usage(result, "high")
    assert packet["estimatedCostUsd"] == 0.0041
    assert (packet["apiCalls"], packet["toolUses"], packet["effort"]) == (2, 1, "high")
    no_usage = AnthropicTextResult("Yes.", {}, "claude-sonnet-5")
    assert "estimatedCostUsd" not in _answer_usage(no_usage, "high")


def test_answer_shape_logs_flags_without_changing_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    info = Mock()
    monkeypatch.setattr("src.services.brief_chat.log.info", info)
    answer = "The verdict is Red. Your trainingLoadCap stays in force at 09:00 UTC."
    _log_answer_shape(answer, uuid.uuid4())
    assert answer == "The verdict is Red. Your trainingLoadCap stays in force at 09:00 UTC."
    assert info.call_args.kwargs["banned_terms"] == [
        "internal_call_term",
        "colour",
        "utc",
        "field_name",
    ]
    _log_answer_shape("Future verdicts stay as recorded.", uuid.uuid4())
    assert info.call_args.kwargs["banned_terms"] == ["internal_call_term"]


def test_final_answer_guard_translates_only_recognised_training_grades() -> None:
    profile_id = uuid.uuid4()
    answer = (
        "That morning's readiness call (Amber, from HRV) was cautious. "
        "The Red day became a Green call. A red flag still deserves attention."
    )
    guarded = _guard_mark_answer(answer, profile_id)
    assert guarded == (
        "That morning's readiness call (cautious, from HRV) was cautious. "
        "The recovery day became a clear call. A red flag still deserves attention."
    )


@pytest.mark.parametrize(
    "answer",
    [
        "Amber was the answer.",
        "The verdict was cautious.",
        "The internal trainingLoadCap was active.",
        "The call happened at 09:00 UTC.",
    ],
)
def test_final_answer_guard_rejects_untranslated_terms(answer: str) -> None:
    with pytest.raises(HTTPException) as caught:
        _guard_mark_answer(answer, uuid.uuid4())
    assert caught.value.status_code == 503
    assert "try again" in caught.value.detail


def test_shared_voice_evidence_contract_keeps_training_boundaries() -> None:
    prompt = _build_cached_system_prompt(
        analysis=None,
        origin=CoachOrigin(),
        local_today=date(2026, 9, 23),
        app_state={},
        adjustable_set=None,
    )
    brief = prompt[0]["text"]
    final = prompt[-1]["text"]

    assert floors_sentence() in brief
    assert PROPOSE_CONFIRM_RULE in brief
    assert "Before replying, check privately" in brief
    assert "start with Yes, No or Partly" not in brief + final
    assert final == FINAL_REPLY_RULE
    assert "does not establish recovery" in final
    assert "not an automatic workout change" in final
    assert "plan swap" in final and "fallback recovery spin" in final
    assert "computed training call and safety boundaries intact" in final
