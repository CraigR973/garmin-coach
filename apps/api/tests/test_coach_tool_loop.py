"""The agentic loop the coach answers through (Batch 257.3/257.6).

These are pure boundary tests — no database, no provider — so they run locally
rather than only in CI, which matters for a loop whose failure modes are all
shape errors the provider rejects on the *next* turn rather than this one.
"""

from __future__ import annotations

from typing import Any

import pytest
from anthropic.types import Message

from src.services.anthropic_text import (
    MAX_TOOL_ROUNDS,
    ToolResult,
    generate_anthropic_text_with_tools,
)
from src.services.morning_analysis import MorningAnalysisError

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_sleep_nights",
        "description": "Look up nights.",
        "input_schema": {
            "type": "object",
            "properties": {"startDate": {"type": "string"}, "endDate": {"type": "string"}},
            "required": ["startDate", "endDate"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]


def _message(payload: dict[str, Any]) -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            **payload,
        }
    )


def _tool_use(block_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": block_id, "name": name, "input": payload}


class _Messages:
    async def create(self, **kwargs: Any) -> Message:
        index = _Scripted.calls
        _Scripted.calls += 1
        _Scripted.payloads.append(kwargs)
        return _message(_Scripted.script[index])


class _Scripted:
    script: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    calls: int = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.messages = _Messages()

    async def __aenter__(self) -> _Scripted:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    @classmethod
    def load(cls, *responses: dict[str, Any]) -> None:
        cls.script = list(responses)
        cls.payloads = []
        cls.calls = 0


class _Recorder:
    """A tool executor that records what it was asked and answers as told."""

    def __init__(self, *, fail: bool = False) -> None:
        self.seen: list[tuple[str, str, Any]] = []
        self.fail = fail

    async def __call__(self, *, tool_use_id: str, name: str, payload: Any) -> ToolResult:
        self.seen.append((tool_use_id, name, payload))
        if self.fail:
            return ToolResult(tool_use_id=tool_use_id, content="no such night", is_error=True)
        return ToolResult(tool_use_id=tool_use_id, content='{"rows": []}')


async def _run(executor: _Recorder, **overrides: Any) -> Any:
    return await generate_anthropic_text_with_tools(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="How did I sleep on 12 August?",
        error_cls=MorningAnalysisError,
        tools=TOOLS,
        execute_tool=executor,
        **overrides,
    )


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _Scripted)


@pytest.mark.asyncio
async def test_a_single_lookup_is_executed_and_answered() -> None:
    _Scripted.load(
        {
            "stop_reason": "tool_use",
            "content": [
                _tool_use(
                    "tu_1", "get_sleep_nights", {"startDate": "2026-08-12", "endDate": "2026-08-12"}
                )
            ],
        },
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "You slept 6h20."}]},
    )
    executor = _Recorder()

    result = await _run(executor)

    assert result.output_markdown == "You slept 6h20."
    assert result.tool_uses == 1
    assert result.api_calls == 2
    # The input arrives already parsed. Never string-matched: the 4.6+ models
    # vary their JSON escaping inside tool inputs, so matching on the serialized
    # form is a bug that only shows up on some inputs.
    assert executor.seen == [
        ("tu_1", "get_sleep_nights", {"startDate": "2026-08-12", "endDate": "2026-08-12"})
    ]


@pytest.mark.asyncio
async def test_parallel_calls_come_back_in_one_user_message() -> None:
    """Splitting them across messages trains the model out of parallel calls.

    That is the whole reason a two-lookup answer costs one round trip instead of
    two, so it is asserted on the *message array* rather than on the count of
    results — a loop that returned them correctly but in two messages would pass
    a naive count and still teach the model to stop asking.
    """
    _Scripted.load(
        {
            "stop_reason": "tool_use",
            "content": [
                _tool_use(
                    "tu_1", "get_sleep_nights", {"startDate": "2026-08-12", "endDate": "2026-08-12"}
                ),
                _tool_use(
                    "tu_2", "get_sleep_nights", {"startDate": "2026-08-13", "endDate": "2026-08-13"}
                ),
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Both nights were short."}],
        },
    )
    executor = _Recorder()

    result = await _run(executor)

    assert result.tool_uses == 2
    assert result.api_calls == 2
    sent = _Scripted.payloads[-1]["messages"]
    tool_result_messages = [
        message
        for message in sent
        if message["role"] == "user"
        and isinstance(message["content"], list)
        and any(block.get("type") == "tool_result" for block in message["content"])
    ]
    assert len(tool_result_messages) == 1
    assert [block["tool_use_id"] for block in tool_result_messages[0]["content"]] == [
        "tu_1",
        "tu_2",
    ]


@pytest.mark.asyncio
async def test_the_assistant_turn_is_echoed_back_unedited() -> None:
    """Thinking blocks included.

    Re-serialising only the parts that look useful is how a harness silently
    invalidates its own history — and on this path thinking is on, so the
    assistant turn routinely carries a block nothing downstream reads.
    """
    assistant_content = [
        {"type": "thinking", "thinking": "he means the 12th", "signature": "sig"},
        _tool_use("tu_1", "get_sleep_nights", {"startDate": "2026-08-12", "endDate": "2026-08-12"}),
    ]
    _Scripted.load(
        {"stop_reason": "tool_use", "content": assistant_content},
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Short night."}]},
    )

    await _run(_Recorder())

    sent = _Scripted.payloads[-1]["messages"]
    echoed = [message for message in sent if message["role"] == "assistant"]
    assert len(echoed) == 1
    assert [block["type"] for block in echoed[0]["content"]] == ["thinking", "tool_use"]


@pytest.mark.asyncio
async def test_a_failing_tool_degrades_to_an_honest_answer() -> None:
    """`is_error`, not a dropped block and not a 502.

    A dropped result leaves a ``tool_use`` with no answer, which the provider
    rejects on the next turn — turning a failed lookup into a failed answer. The
    lookup was only ever supplementary; Mark still gets a reply.
    """
    _Scripted.load(
        {
            "stop_reason": "tool_use",
            "content": [_tool_use("tu_1", "get_sleep_nights", {"startDate": "x", "endDate": "y"})],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "I couldn't find that night."}],
        },
    )

    result = await _run(_Recorder(fail=True))

    assert result.output_markdown == "I couldn't find that night."
    block = _Scripted.payloads[-1]["messages"][-1]["content"][0]
    assert block == {
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": "no such night",
        "is_error": True,
    }


@pytest.mark.asyncio
async def test_a_successful_result_carries_no_is_error_key() -> None:
    _Scripted.load(
        {
            "stop_reason": "tool_use",
            "content": [_tool_use("tu_1", "get_sleep_nights", {"startDate": "a", "endDate": "b"})],
        },
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "done"}]},
    )

    await _run(_Recorder())

    assert "is_error" not in _Scripted.payloads[-1]["messages"][-1]["content"][0]


@pytest.mark.asyncio
async def test_the_tool_budget_forces_a_prose_answer_rather_than_looping() -> None:
    """Chat runs in-request, so an unbounded loop is Mark watching a spinner.

    Once the budget is spent the next call goes out with ``tool_choice: none``,
    which guarantees prose. That is cheap on purpose: a ``tool_choice`` change
    invalidates only the *messages* cache, and both of this path's breakpoints
    are in ``system``.
    """
    _Scripted.load(
        {
            "stop_reason": "tool_use",
            "content": [_tool_use("tu_1", "get_sleep_nights", {"startDate": "a", "endDate": "b"})],
        },
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Here is what I found."}]},
    )

    result = await _run(_Recorder(), max_tool_uses=1)

    assert result.tool_uses == 1
    assert _Scripted.payloads[0].get("tool_choice") is None
    assert _Scripted.payloads[1]["tool_choice"] == {"type": "none"}
    assert result.output_markdown == "Here is what I found."


@pytest.mark.asyncio
async def test_the_round_cap_bounds_a_model_that_keeps_asking() -> None:
    keeps_asking = {
        "stop_reason": "tool_use",
        "content": [_tool_use("tu_1", "get_sleep_nights", {"startDate": "a", "endDate": "b"})],
    }
    _Scripted.load(
        keeps_asking,
        keeps_asking,
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Enough."}]},
    )

    result = await _run(_Recorder(), max_tool_uses=99)

    assert result.api_calls == MAX_TOOL_ROUNDS
    assert _Scripted.payloads[-1]["tool_choice"] == {"type": "none"}
    assert result.output_markdown == "Enough."


@pytest.mark.asyncio
async def test_an_answer_with_no_lookups_costs_exactly_one_call() -> None:
    """The common case must not pay for the capability it did not use."""
    _Scripted.load({"stop_reason": "end_turn", "content": [{"type": "text", "text": "Fine."}]})

    result = await _run(_Recorder())

    assert (result.api_calls, result.tool_uses) == (1, 0)
    assert _Scripted.payloads[0]["tools"] == TOOLS
    assert "tool_choice" not in _Scripted.payloads[0]


@pytest.mark.asyncio
async def test_max_tokens_is_still_loud_on_the_tool_path() -> None:
    """A truncated answer that returned quietly would read as a complete one."""
    _Scripted.load(
        {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "Your readiness is"}]}
    )

    with pytest.raises(MorningAnalysisError, match="max_tokens"):
        await _run(_Recorder())
