from __future__ import annotations

from typing import Any

import pytest

from src.services.anthropic_text import generate_anthropic_text
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
