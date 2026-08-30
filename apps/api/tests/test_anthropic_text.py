from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.services.anthropic_text import (
    AnthropicApiError,
    classify_anthropic_error,
    generate_anthropic_text,
)
from src.services.morning_analysis import MorningAnalysisError


class _DummyResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _DummyAsyncClient:
    last_request_json: dict[str, Any] | None = None
    response_payload: Any = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> _DummyAsyncClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> _DummyResponse:
        _DummyAsyncClient.last_request_json = json
        return _DummyResponse(_DummyAsyncClient.response_payload)


@pytest.mark.asyncio
async def test_generate_anthropic_text_raises_on_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.httpx.AsyncClient", _DummyAsyncClient)
    _DummyAsyncClient.response_payload = {
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
    monkeypatch.setattr("src.services.anthropic_text.httpx.AsyncClient", _DummyAsyncClient)
    _DummyAsyncClient.response_payload = {
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
    monkeypatch.setattr("src.services.anthropic_text.httpx.AsyncClient", _DummyAsyncClient)
    _DummyAsyncClient.response_payload = {
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

    assert _DummyAsyncClient.last_request_json is not None
    assert _DummyAsyncClient.last_request_json["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_generate_anthropic_text_accepts_system_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.httpx.AsyncClient", _DummyAsyncClient)
    _DummyAsyncClient.response_payload = {
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

    assert _DummyAsyncClient.last_request_json is not None
    assert _DummyAsyncClient.last_request_json["system"] == system_blocks


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


class _ErrorAsyncClient:
    status_code: int = 400
    body: Any = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API.",
        },
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> _ErrorAsyncClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> httpx.Response:
        return httpx.Response(self.status_code, json=self.body, request=httpx.Request("POST", url))


@pytest.mark.asyncio
async def test_generate_anthropic_text_raises_classified_billing_on_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_text.httpx.AsyncClient", _ErrorAsyncClient)

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


class _TimeoutCapturingAsyncClient(_DummyAsyncClient):
    """Records the ``timeout=`` the boundary constructs its client with."""

    last_timeout: httpx.Timeout | None = None

    def __init__(self, *args: Any, timeout: Any = None, **kwargs: Any) -> None:
        _TimeoutCapturingAsyncClient.last_timeout = timeout
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
    monkeypatch.setattr(
        "src.services.anthropic_text.httpx.AsyncClient", _TimeoutCapturingAsyncClient
    )
    _TimeoutCapturingAsyncClient.response_payload = {
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

    timeout = _TimeoutCapturingAsyncClient.last_timeout
    assert isinstance(timeout, httpx.Timeout)
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
    monkeypatch.setattr(
        "src.services.anthropic_text.httpx.AsyncClient", _TimeoutCapturingAsyncClient
    )
    monkeypatch.setattr(
        "src.services.anthropic_text.settings.anthropic_read_timeout_seconds", 450.0
    )
    _TimeoutCapturingAsyncClient.response_payload = {
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

    timeout = _TimeoutCapturingAsyncClient.last_timeout
    assert timeout is not None and timeout.read == 450.0
