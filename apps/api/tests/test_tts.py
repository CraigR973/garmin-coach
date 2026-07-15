"""Tests for the hosted read-aloud voice router (Batch 116 / DECISIONS #190).

`PUT /api/v1/tts/consent` persists the opt-in flag; `POST /api/v1/tts/synthesize`
is gated on that flag *and* on the Piper voice model file being present, and
never calls the (faked) Piper synthesis service unless both hold.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.config import settings
from src.database import get_db
from src.main import app
from src.models.profile import Profile, UserRole
from src.routers import tts as tts_router
from src.services import tts_cache
from src.services.piper_tts import PiperTTSError, PiperTTSResult


def _db_override(session_factory: async_sessionmaker[AsyncSession]):
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return _override


def _user_override(user_id: uuid.UUID):
    async def _override(db: AsyncSession = Depends(get_db)) -> Profile:
        user = await db.get(Profile, user_id)
        assert user is not None
        return user

    return _override


async def _seed_player(
    session_factory: async_sessionmaker[AsyncSession], *, hosted_tts_consent: bool
) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="TTS Router Test",
                pin_hash="x" * 60,
                role=UserRole.player,
                timezone="Europe/London",
                is_active=True,
                hosted_tts_consent=hosted_tts_consent,
            )
        )
        await session.commit()
    return user_id


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    tts_cache._audio_cache.clear()


def _point_settings_at_existing_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"fake-model")
    config_path = tmp_path / "voice.onnx.json"
    config_path.write_text("{}")
    monkeypatch.setattr(settings, "piper_voice_model_path", str(model_path))
    monkeypatch.setattr(settings, "piper_voice_config_path", str(config_path))


@pytest.mark.asyncio
async def test_put_consent_persists(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, hosted_tts_consent=False)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put("/api/v1/tts/consent", json={"enabled": True})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["data"]["hostedTtsConsent"] is True


@pytest.mark.asyncio
async def test_synthesize_requires_consent(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, hosted_tts_consent=False)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/tts/synthesize", json={"text": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_synthesize_requires_voice_model_configured(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "piper_voice_model_path", str(tmp_path / "missing.onnx"))
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, hosted_tts_consent=True)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/tts/synthesize", json={"text": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503, response.text


@pytest.mark.asyncio
async def test_synthesize_returns_audio_and_caches(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_settings_at_existing_model(monkeypatch, tmp_path)
    calls = 0

    async def _fake_synthesize(**kwargs: object) -> PiperTTSResult:
        nonlocal calls
        calls += 1
        return PiperTTSResult(audio_bytes=b"wav-bytes", content_type="audio/wav")

    monkeypatch.setattr(tts_router, "synthesize_speech", _fake_synthesize)

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, hosted_tts_consent=True)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            text = "Train as planned today."
            first = await client.post("/api/v1/tts/synthesize", json={"text": text})
            second = await client.post("/api/v1/tts/synthesize", json={"text": text})
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "audio/wav"
    assert first.content == b"wav-bytes"
    assert second.content == b"wav-bytes"
    # Second identical call is served from the in-process cache, not a fresh call.
    assert calls == 1


@pytest.mark.asyncio
async def test_synthesize_502_on_upstream_failure(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_settings_at_existing_model(monkeypatch, tmp_path)

    async def _failing_synthesize(**kwargs: object) -> PiperTTSResult:
        raise PiperTTSError("boom")

    monkeypatch.setattr(tts_router, "synthesize_speech", _failing_synthesize)

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, hosted_tts_consent=True)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/tts/synthesize", json={"text": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502, response.text


@pytest.mark.asyncio
async def test_synthesize_rejects_blank_text(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_settings_at_existing_model(monkeypatch, tmp_path)
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, hosted_tts_consent=True)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/tts/synthesize", json={"text": "   "})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400, response.text
