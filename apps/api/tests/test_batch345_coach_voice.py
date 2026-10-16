"""Batch 345: pass-on authority and answer usage stay bounded per turn."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.config import settings
from src.services.anthropic_text import AnthropicApiError, AnthropicTextResult
from src.services.brief_chat import (
    COACH_CHAT_TOOLS,
    AnthropicBriefChatClient,
    CoachChatToolbox,
    _answer_usage,
    _guard_mark_answer,
    _log_answer_shape,
    _pass_on_acknowledged_error,
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
