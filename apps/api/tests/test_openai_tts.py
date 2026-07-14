from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.services.openai_tts import OpenAITTSError, synthesize_speech


class _DummyResponse:
    def __init__(self, *, content: bytes = b"", raises: bool = False) -> None:
        self.content = content
        self._raises = raises

    def raise_for_status(self) -> None:
        if self._raises:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]


class _DummyAsyncClient:
    last_request_json: dict[str, Any] | None = None
    response: _DummyResponse = _DummyResponse()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> _DummyAsyncClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> _DummyResponse:
        _DummyAsyncClient.last_request_json = json
        return _DummyAsyncClient.response


@pytest.mark.asyncio
async def test_synthesize_speech_returns_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.openai_tts.httpx.AsyncClient", _DummyAsyncClient)
    _DummyAsyncClient.response = _DummyResponse(content=b"mp3-bytes")

    result = await synthesize_speech(
        api_key="test-key",
        model_name="tts-1",
        voice="alloy",
        text="Train as planned today.",
    )

    assert result.audio_bytes == b"mp3-bytes"
    assert result.content_type == "audio/mpeg"
    assert _DummyAsyncClient.last_request_json == {
        "model": "tts-1",
        "voice": "alloy",
        "input": "Train as planned today.",
        "response_format": "mp3",
    }


@pytest.mark.asyncio
async def test_synthesize_speech_raises_on_empty_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.openai_tts.httpx.AsyncClient", _DummyAsyncClient)
    _DummyAsyncClient.response = _DummyResponse(content=b"")

    with pytest.raises(OpenAITTSError, match="did not contain audio"):
        await synthesize_speech(api_key="test-key", model_name="tts-1", voice="alloy", text="hi")


@pytest.mark.asyncio
async def test_synthesize_speech_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.openai_tts.httpx.AsyncClient", _DummyAsyncClient)
    _DummyAsyncClient.response = _DummyResponse(content=b"x", raises=True)

    with pytest.raises(OpenAITTSError, match="request failed"):
        await synthesize_speech(api_key="test-key", model_name="tts-1", voice="alloy", text="hi")
