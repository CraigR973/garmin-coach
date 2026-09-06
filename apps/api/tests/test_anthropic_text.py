from __future__ import annotations

from typing import Any

import httpx2
import pytest
from anthropic import APIConnectionError, APIStatusError, APITimeoutError, Timeout
from anthropic.types import Message

from src.config import settings
from src.services.anthropic_text import (
    AnthropicApiError,
    _thinking_tokens,
    anthropic_http_status,
    classify_anthropic_error,
    configured_effort,
    configured_thinking,
    generate_anthropic_text,
)
from src.services.morning_analysis import MorningAnalysisError

# Batch 257 moved the boundary onto the ``anthropic`` SDK, so the fake below is a
# fake *client* rather than a fake transport. Everything these tests actually
# assert is unchanged — ``last_request_json`` is still the request the boundary
# asked to be sent, and the payloads are still the provider's own JSON shape,
# now round-tripped through the SDK's ``Message`` model so a response the SDK
# would reject cannot pass here and fail in production.

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _message(payload: dict[str, Any]) -> Message:
    """A real SDK ``Message`` from the partial payloads these tests write."""
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


def _request() -> httpx2.Request:
    """The SDK is built on ``httpx2``; an ``httpx`` object is rejected by it."""
    return httpx2.Request("POST", _ANTHROPIC_URL)


async def _no_sleep(_seconds: float) -> None:
    """Retry backoff is real time; the tests must not spend it."""
    return None


class _Messages:
    """The ``client.messages`` namespace, for a fake that records one call."""

    def __init__(self, owner: type[_DummyAnthropic]) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> Message:
        self._owner.last_request_json = kwargs
        return _message(self._owner.response_payload)


class _DummyAnthropic:
    last_request_json: dict[str, Any] | None = None
    response_payload: Any = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.messages = _Messages(type(self))

    async def __aenter__(self) -> _DummyAnthropic:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_generate_anthropic_text_raises_on_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": "partial"}],
    }

    with pytest.raises(MorningAnalysisError, match="max_tokens"):
        await generate_anthropic_text(
            api_key="test-key",
            model_name="claude-test",
            max_tokens=4096,
            system_prompt="system",
            user_prompt="prompt",
            error_cls=MorningAnalysisError,
        )


@pytest.mark.asyncio
async def test_generate_anthropic_text_returns_text_on_end_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "**Line one**"},
            {"type": "text", "text": "- Bullet two"},
        ],
    }

    result = await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )

    assert result.model_name == "claude-test"
    assert result.output_markdown == "**Line one**\n\n- Bullet two"


@pytest.mark.asyncio
async def test_generate_anthropic_text_uses_shared_max_token_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "complete"}],
    }

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )

    assert _DummyAnthropic.last_request_json is not None
    assert _DummyAnthropic.last_request_json["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_generate_anthropic_text_accepts_system_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "complete"}],
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 12,
            "cache_creation_input_tokens": 1100,
            "cache_read_input_tokens": 0,
        },
    }
    system_blocks = [
        {
            "type": "text",
            "text": "stable prefix",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "fresh state"},
    ]

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt=system_blocks,
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )

    assert _DummyAnthropic.last_request_json is not None
    assert _DummyAnthropic.last_request_json["system"] == system_blocks


# Batch 141: an Anthropic non-2xx must be classified so a caller can act on the
# failure class — the 2026-07-21 freeze was a 400 whose *message* (not status)
# named the credit balance.
@pytest.mark.parametrize(
    ("status_code", "error_type", "error_message", "expected"),
    [
        (
            400,
            "invalid_request_error",
            "Your credit balance is too low to access the Anthropic API. "
            "Please go to Plans & Billing to upgrade or purchase credits.",
            "billing",
        ),
        (429, "rate_limit_error", "Number of requests has exceeded your rate limit", "rate_limit"),
        (401, "authentication_error", "invalid x-api-key", "auth"),
        (
            400,
            "invalid_request_error",
            "prompt is too long: 250000 tokens > 200000",
            "prompt_too_long",
        ),
        (
            400,
            "invalid_request_error",
            "messages: at least one message is required",
            "invalid_request",
        ),
        (529, "overloaded_error", "Overloaded", "overloaded"),
        (500, "api_error", "Internal server error", "server_error"),
    ],
)
def test_classify_anthropic_error(
    status_code: int, error_type: str, error_message: str, expected: str
) -> None:
    assert (
        classify_anthropic_error(status_code, error_type=error_type, error_message=error_message)
        == expected
    )


class _ErrorMessages:
    async def create(self, **kwargs: Any) -> Message:
        raise _status_error(
            400,
            etype="invalid_request_error",
            message="Your credit balance is too low to access the Anthropic API.",
        )


class _ErrorAnthropic:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.messages = _ErrorMessages()

    async def __aenter__(self) -> _ErrorAnthropic:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_generate_anthropic_text_raises_classified_billing_on_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _ErrorAnthropic)

    with pytest.raises(AnthropicApiError) as excinfo:
        await generate_anthropic_text(
            api_key="test-key",
            model_name="claude-test",
            max_tokens=16,
            system_prompt="system",
            user_prompt="prompt",
            error_cls=MorningAnalysisError,
        )

    # The classified reason (not the caller's error_cls) is what lets the check-in
    # background task fire the admin billing alert.
    assert excinfo.value.reason == "billing"
    assert excinfo.value.status_code == 400


class _TimeoutCapturingAnthropic(_DummyAnthropic):
    """Records the ``timeout=`` the boundary constructs its client with."""

    last_timeout: Timeout | None = None
    last_max_retries: Any = None

    def __init__(self, *args: Any, timeout: Any = None, **kwargs: Any) -> None:
        _TimeoutCapturingAnthropic.last_timeout = timeout
        _TimeoutCapturingAnthropic.last_max_retries = kwargs.get("max_retries")
        super().__init__(*args, **kwargs)


@pytest.mark.asyncio
async def test_generate_anthropic_text_read_timeout_outlasts_a_long_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The morning brief takes minutes, so the *read* budget must be minutes.

    Regression for 2026-08-30: a flat ``timeout=60.0`` applied 60s to the whole
    response, and a brief measured at 75s (then 139s on regeneration) died on
    ``httpx.ReadTimeout`` *after* Anthropic had already generated and billed it.
    Every attempt that morning failed the same way, so the brief never arrived.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _TimeoutCapturingAnthropic)
    _TimeoutCapturingAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "brief"}],
    }

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )

    timeout = _TimeoutCapturingAnthropic.last_timeout
    assert isinstance(timeout, Timeout)
    # Comfortably past the slowest observed brief, so growth in the packet does
    # not silently re-open the failure.
    assert timeout.read is not None and timeout.read >= 240.0
    # Connect/write stay short: an unreachable API must fail fast rather than
    # hang for the whole read budget.
    assert timeout.connect is not None and timeout.connect <= 15.0
    assert timeout.write is not None and timeout.write <= 60.0


@pytest.mark.asyncio
async def test_generate_anthropic_text_read_timeout_is_env_tunable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow spell can be ridden out from Railway without shipping a deploy."""
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _TimeoutCapturingAnthropic)
    monkeypatch.setattr(
        "src.services.anthropic_text.settings.anthropic_read_timeout_seconds", 450.0
    )
    _TimeoutCapturingAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "brief"}],
    }

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )

    timeout = _TimeoutCapturingAnthropic.last_timeout
    assert timeout is not None and timeout.read == 450.0


@pytest.mark.asyncio
async def test_the_sdks_own_retries_are_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One retry layer, and it is this module's (Batch 257).

    The SDK re-attempts 408/409/429 and 5xx twice by default. Left on, it nests
    inside :data:`_MAX_ANTHROPIC_ATTEMPTS` — up to nine attempts against a budget
    Batch 232 sized for three, with the extra ones invisible to the
    ``anthropic_call_retrying`` log line *and* free to outlive the generation
    lease that `validate_timeout_ordering()` refuses to boot without. The nesting
    would not fail a test or raise an error; it would just quietly spend three
    times the wall clock the deadline was built around.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _TimeoutCapturingAnthropic)
    _TimeoutCapturingAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "brief"}],
    }

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )

    assert _TimeoutCapturingAnthropic.last_max_retries == 0


# ---------------------------------------------------------------------------
# Batch 233 — Sonnet 5, adaptive thinking, and the ceiling it shares with prose
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thinking_and_effort_are_absent_unless_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rollback path: a caller that passes neither sends the pre-233 request.

    ``thinking`` and ``output_config`` are the *only* wire-format difference
    between this app on Sonnet 5 and this app as it was on Sonnet 4.6. If either
    leaks into the payload by default, reverting the model becomes a code change
    rather than a settings change.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "complete"}],
    }

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )

    payload = _DummyAnthropic.last_request_json
    assert payload is not None
    assert set(payload) == {"model", "max_tokens", "system", "messages"}


@pytest.mark.asyncio
async def test_thinking_and_effort_reach_the_payload_when_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "complete"}],
    }

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
        thinking={"type": "adaptive"},
        effort="high",
    )

    payload = _DummyAnthropic.last_request_json
    assert payload is not None
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_payload_never_carries_a_parameter_sonnet_5_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sonnet 5 returns a 400 for sampling parameters, ``budget_tokens`` and prefill.

    The boundary builds a fixed payload, so this pins the whole breaking-change
    list in one place rather than trusting a grep that decays.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "complete"}],
    }

    await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
        prior_messages=[{"role": "user", "content": "earlier"}],
        thinking={"type": "adaptive"},
        effort="high",
    )

    payload = _DummyAnthropic.last_request_json
    assert payload is not None
    for rejected in ("temperature", "top_p", "top_k", "budget_tokens"):
        assert rejected not in payload
    assert "budget_tokens" not in payload["thinking"]
    # No assistant prefill: the user turn is always appended last.
    assert payload["messages"][-1]["role"] == "user"


@pytest.mark.asyncio
async def test_thinking_blocks_never_reach_the_users_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With thinking on, ``content`` carries a thinking block before the text.

    Measured on a real morning brief, 14,610 of 16,157 output tokens were
    thinking. The boundary must return only the prose.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [
            {
                "type": "thinking",
                "thinking": "the user's readiness is 64, so...",
                "signature": "sig",
            },
            {"type": "text", "text": "# Morning Read"},
        ],
    }

    result = await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
        thinking={"type": "adaptive"},
        effort="high",
    )

    assert result.output_markdown == "# Morning Read"
    assert "readiness is 64" not in result.output_markdown


@pytest.mark.asyncio
async def test_max_tokens_still_raises_rather_than_returning_partial_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thinking shares ``max_tokens`` with the prose, so this stop must stay loud.

    A truncated brief that returned quietly would read as a complete coaching
    verdict with its conclusion missing — worse than the Batch 141 failure card.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _DummyAnthropic)
    _DummyAnthropic.response_payload = {
        "model": "claude-test",
        "stop_reason": "max_tokens",
        "content": [
            {
                "type": "thinking",
                "thinking": "long deliberation that ate the budget",
                "signature": "sig",
            },
            {"type": "text", "text": "# Morning Read\n\nYour readiness is"},
        ],
    }

    with pytest.raises(MorningAnalysisError, match="max_tokens"):
        await generate_anthropic_text(
            api_key="test-key",
            model_name="claude-test",
            max_tokens=4096,
            system_prompt="system",
            user_prompt="prompt",
            error_cls=MorningAnalysisError,
            thinking={"type": "adaptive"},
            effort="high",
        )


def test_configured_thinking_and_effort_follow_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "anthropic_thinking_mode", "adaptive")
    monkeypatch.setattr(settings, "anthropic_effort", "high")
    assert configured_thinking() == {"type": "adaptive"}
    assert configured_effort() == "high"

    # The rollback lever: one setting restores Sonnet 4.6's behaviour.
    monkeypatch.setattr(settings, "anthropic_thinking_mode", "disabled")
    assert configured_thinking() == {"type": "disabled"}


def test_thinking_tokens_are_logged_when_the_provider_reports_them() -> None:
    """The ceiling is under pressure from thinking, not prose — the log must say so."""
    usage = {
        "input_tokens": 26474,
        "output_tokens": 16157,
        "output_tokens_details": {"thinking_tokens": 14610},
    }
    assert _thinking_tokens(usage) == 14610
    # Absent on a thinking-off response, and on providers that omit the field.
    assert _thinking_tokens({"output_tokens": 2305}) is None
    assert _thinking_tokens({"output_tokens_details": None}) is None


# ---------------------------------------------------------------------------
# Batch 248 — AI238-04: transport failures were classified by nothing and
# retried by nothing. Both production outages replayed as tests.
# ---------------------------------------------------------------------------


class _ScriptedMessages:
    async def create(self, **kwargs: Any) -> Message:
        index = _ScriptedAnthropic.attempts
        _ScriptedAnthropic.attempts += 1
        outcome = _ScriptedAnthropic.script[index]
        if isinstance(outcome, Exception):
            raise outcome
        return _message(outcome)


class _ScriptedAnthropic:
    """Plays a scripted sequence of outcomes, one per attempt.

    Each item is either an exception to raise or a payload to return, so a test
    can express "529, then success" without stubbing the whole client.
    """

    script: list[Any] = []
    attempts: int = 0
    read_timeouts: list[float] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        timeout = kwargs.get("timeout")
        if timeout is not None:
            _ScriptedAnthropic.read_timeouts.append(timeout.read)
        self.messages = _ScriptedMessages()

    async def __aenter__(self) -> _ScriptedAnthropic:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    @classmethod
    def load(cls, *outcomes: Any) -> None:
        cls.script = list(outcomes)
        cls.attempts = 0
        cls.read_timeouts = []


def _ok_payload() -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": "the read"}],
        "model": "claude-test",
        "stop_reason": "end_turn",
    }


def _status_error(status_code: int, *, etype: str, message: str) -> APIStatusError:
    """The SDK's own non-2xx exception, carrying the provider's parsed body.

    ``anthropic_error_from_http_status`` reads ``exc.body`` rather than re-parsing
    the response, so the body is what the classification actually sees.
    """
    body = {"type": "error", "error": {"type": etype, "message": message}}
    response = httpx2.Response(status_code, json=body, request=_request())
    return APIStatusError("boom", response=response, body=body)


async def _generate() -> Any:
    return await generate_anthropic_text(
        api_key="test-key",
        model_name="claude-test",
        max_tokens=4096,
        system_prompt="system",
        user_prompt="prompt",
        error_cls=MorningAnalysisError,
    )


@pytest.mark.asyncio
async def test_read_timeout_becomes_a_classified_timeout_not_an_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 2026-08-30 outage, replayed.

    Seven `httpx.ReadTimeout`s between 08:59 and 09:23, every one uncaught: it
    escaped `generate_anthropic_text` entirely, classified as nothing, reached
    Mark as a bare 500 the web client could not parse and the operator as
    silence. `main.py` registers one exception handler and it is not this one.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _ScriptedAnthropic)
    _ScriptedAnthropic.load(
        APITimeoutError(request=_request()),
        APITimeoutError(request=_request()),
        APITimeoutError(request=_request()),
    )

    with pytest.raises(AnthropicApiError) as caught:
        await _generate()

    assert caught.value.reason == "timeout"
    # No response ever arrived, so there is no upstream status to report.
    assert caught.value.status_code == 0


@pytest.mark.asyncio
async def test_a_connection_failure_is_transport_not_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`timeout` means "we may already have been billed for an answer we hung up
    on" (Batch 234's finding); `transport` means the request never landed. The
    two deserve different reason slugs even though both are `RequestError`s."""
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _ScriptedAnthropic)
    _ScriptedAnthropic.load(
        APIConnectionError(message="refused", request=_request()),
        APIConnectionError(message="refused", request=_request()),
        APIConnectionError(message="refused", request=_request()),
    )

    with pytest.raises(AnthropicApiError) as caught:
        await _generate()

    assert caught.value.reason == "transport"


@pytest.mark.asyncio
async def test_an_overloaded_response_is_retried_and_can_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single 529 at 06:40 used to cost the whole morning until the 11:00
    backstop, because nothing anywhere in the app retried anything."""
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _ScriptedAnthropic)
    monkeypatch.setattr("src.services.anthropic_text.asyncio.sleep", _no_sleep)

    _ScriptedAnthropic.load(
        _status_error(529, etype="overloaded_error", message="Overloaded"),
        _ok_payload(),
    )

    result = await _generate()

    assert result.output_markdown == "the read"
    assert _ScriptedAnthropic.attempts == 2


@pytest.mark.asyncio
async def test_billing_is_never_auto_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A credit outage does not clear in eight seconds. Retrying it turns one
    failure into three identical log lines while Mark waits three times as long
    for the same answer."""
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _ScriptedAnthropic)
    monkeypatch.setattr("src.services.anthropic_text.asyncio.sleep", _no_sleep)

    _ScriptedAnthropic.load(
        _status_error(
            400,
            etype="invalid_request_error",
            message="Your credit balance is too low to access the Anthropic API.",
        )
    )

    with pytest.raises(AnthropicApiError) as caught:
        await _generate()

    assert caught.value.reason == "billing"
    assert _ScriptedAnthropic.attempts == 1


@pytest.mark.asyncio
async def test_a_retry_is_refused_when_the_call_budget_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry budget is the whole call, not each attempt.

    Batch 234 derived the read budget, Batch 232 derived the generation lease
    from it, and `validate_timeout_ordering()` refuses to boot unless the lease
    outlives the paid call. Three attempts each given the full read budget would
    be 3x550s against a 670s lease — a retry outliving its own lease and handing
    the artifact scope to another worker mid-flight.
    """
    monkeypatch.setattr("src.services.anthropic_text.AsyncAnthropic", _ScriptedAnthropic)
    monkeypatch.setattr("src.services.anthropic_text.asyncio.sleep", _no_sleep)
    # A budget too small to fit a second attempt.
    monkeypatch.setattr(settings, "anthropic_read_timeout_seconds", 5.0)

    _ScriptedAnthropic.load(_status_error(529, etype="overloaded_error", message="Overloaded"))

    with pytest.raises(AnthropicApiError) as caught:
        await _generate()

    assert caught.value.reason == "overloaded"
    # Retryable, but there was no budget left to retry inside.
    assert _ScriptedAnthropic.attempts == 1


def test_the_spend_cap_wording_classifies_as_billing() -> None:
    """The 2026-08-31 outage, replayed — and it is not the 2026-07-21 one.

    A configured spend cap arrives as HTTP 400 `invalid_request_error` reading
    "You have reached your specified API usage limits". None of "billing",
    "credit balance" or "plans & billing" appears in it, so it classified as
    `invalid_request`: generic copy for Mark, no alert for the operator. It was
    proved live when Batch 233's own verification tripped the cap.
    """
    assert (
        classify_anthropic_error(
            400,
            error_type="invalid_request_error",
            error_message="You have reached your specified API usage limits.",
        )
        == "billing"
    )


def test_the_original_credit_wording_still_classifies_as_billing() -> None:
    assert (
        classify_anthropic_error(
            400,
            error_type="invalid_request_error",
            error_message="Your credit balance is too low to access the Anthropic API.",
        )
        == "billing"
    )


def test_an_ordinary_bad_request_is_still_not_billing() -> None:
    """The widened match must not swallow every 400."""
    assert (
        classify_anthropic_error(
            400,
            error_type="invalid_request_error",
            error_message="messages: at least one message is required",
        )
        == "invalid_request"
    )


def test_a_timeout_advises_a_retry_rather_than_claiming_upstream_broke() -> None:
    """503 says "try again shortly", 502 says "upstream broke". Seven timeouts
    on 2026-08-30 said the second about the first."""
    assert anthropic_http_status("timeout") == 503
    assert anthropic_http_status("server_error") == 503
    assert anthropic_http_status("auth") == 502
