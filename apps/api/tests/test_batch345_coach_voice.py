"""Batch 345: pass-on authority and answer usage stay bounded per turn."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import settings
from src.services.anthropic_text import AnthropicTextResult
from src.services.brief_chat import (
    COACH_CHAT_TOOLS,
    CoachChatToolbox,
    _answer_usage,
    _log_answer_shape,
)


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
