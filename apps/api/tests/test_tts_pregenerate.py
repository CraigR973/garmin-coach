from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.config import settings
from src.models.coaching import Analysis
from src.models.profile import Profile, UserRole
from src.services import tts_cache
from src.services.piper_tts import PiperTTSError, PiperTTSResult
from src.services.tts_pregenerate import pregenerate_brief_audio


def _player(*, hosted_tts_consent: bool) -> Profile:
    return Profile(
        id=uuid.uuid4(),
        display_name="Pregenerate Test",
        pin_hash="x" * 60,
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
        hosted_tts_consent=hosted_tts_consent,
    )


def _analysis(*, output_markdown: str = "**Green light**\n\nTrain as planned.") -> Analysis:
    return Analysis(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        analysis_type="morning",
        subject_date=datetime.now(UTC).date(),
        generated_at_utc=datetime.now(UTC),
        prompt_version="morning-v1",
        output_markdown=output_markdown,
    )


def _point_settings_at_existing_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"fake")
    monkeypatch.setattr(settings, "piper_voice_model_path", str(model_path))
    monkeypatch.setattr(settings, "piper_voice_config_path", str(tmp_path / "voice.onnx.json"))


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    tts_cache._audio_cache.clear()


@pytest.mark.asyncio
async def test_skips_when_consent_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def _fake_synthesize(**kwargs: object) -> PiperTTSResult:
        nonlocal calls
        calls += 1
        return PiperTTSResult(audio_bytes=b"wav", content_type="audio/wav")

    monkeypatch.setattr("src.services.tts_pregenerate.synthesize_speech", _fake_synthesize)

    await pregenerate_brief_audio(_player(hosted_tts_consent=False), _analysis())

    assert calls == 0


@pytest.mark.asyncio
async def test_skips_when_voice_model_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "piper_voice_model_path", str(tmp_path / "missing.onnx"))
    calls = 0

    async def _fake_synthesize(**kwargs: object) -> PiperTTSResult:
        nonlocal calls
        calls += 1
        return PiperTTSResult(audio_bytes=b"wav", content_type="audio/wav")

    monkeypatch.setattr("src.services.tts_pregenerate.synthesize_speech", _fake_synthesize)

    await pregenerate_brief_audio(_player(hosted_tts_consent=True), _analysis())

    assert calls == 0


@pytest.mark.asyncio
async def test_synthesizes_and_warms_the_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_settings_at_existing_model(monkeypatch, tmp_path)

    captured: dict[str, Any] = {}

    async def _fake_synthesize(**kwargs: object) -> PiperTTSResult:
        captured.update(kwargs)
        return PiperTTSResult(audio_bytes=b"real-wav-bytes", content_type="audio/wav")

    monkeypatch.setattr("src.services.tts_pregenerate.synthesize_speech", _fake_synthesize)

    analysis = _analysis(output_markdown="# Morning\n\n**Green light** — keep the ride.")
    await pregenerate_brief_audio(_player(hosted_tts_consent=True), analysis)

    # Pregeneration must use the same markdown-to-speech transform the
    # frontend uses, so the cache key matches what the browser later sends.
    assert captured["text"] == "Morning\n\nGreen light — keep the ride."

    key = tts_cache.cache_key("Morning\n\nGreen light — keep the ride.")
    assert tts_cache.cache_get(key) == b"real-wav-bytes"


@pytest.mark.asyncio
async def test_skips_synthesis_when_already_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_settings_at_existing_model(monkeypatch, tmp_path)

    analysis = _analysis(output_markdown="Train as planned today.")
    tts_cache.cache_put(tts_cache.cache_key("Train as planned today."), b"already-cached")

    calls = 0

    async def _fake_synthesize(**kwargs: object) -> PiperTTSResult:
        nonlocal calls
        calls += 1
        return PiperTTSResult(audio_bytes=b"wav", content_type="audio/wav")

    monkeypatch.setattr("src.services.tts_pregenerate.synthesize_speech", _fake_synthesize)

    await pregenerate_brief_audio(_player(hosted_tts_consent=True), analysis)

    assert calls == 0


@pytest.mark.asyncio
async def test_never_raises_on_synthesis_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_settings_at_existing_model(monkeypatch, tmp_path)

    async def _failing_synthesize(**kwargs: object) -> PiperTTSResult:
        raise PiperTTSError("boom")

    monkeypatch.setattr("src.services.tts_pregenerate.synthesize_speech", _failing_synthesize)

    # Must not raise.
    await pregenerate_brief_audio(_player(hosted_tts_consent=True), _analysis())
