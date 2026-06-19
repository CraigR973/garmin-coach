"""Tests for the Supabase Storage avatar upload service (service-role path).

The service-role upload is what fixes the "new row violates row-level security
policy" error: the app uses custom JWT auth, so direct browser uploads have a
NULL ``auth.uid()`` and fail the bucket's owner-insert policy. These tests pin
the service-key + bucket-path behaviour without hitting the network.
"""

import pytest

from src.config import settings
from src.services import storage
from src.services.storage import StorageError, upload_avatar


class _Resp:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Minimal async-context httpx.AsyncClient stand-in capturing the POST."""

    captured: dict = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(
        self, url: str, content: bytes | None = None, headers: dict | None = None
    ) -> _Resp:
        _FakeClient.captured = {"url": url, "content": content, "headers": headers or {}}
        return _Resp(200)


async def test_upload_avatar_uses_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "service-key-xyz")
    monkeypatch.setattr(storage.httpx, "AsyncClient", _FakeClient)

    url = await upload_avatar("player-123", b"jpegbytes", "image/jpeg")

    cap = _FakeClient.captured
    assert cap["url"].startswith("https://proj.supabase.co/storage/v1/object/avatars/player-123/")
    assert cap["url"].endswith(".jpg")
    assert cap["headers"]["Authorization"] == "Bearer service-key-xyz"
    assert cap["headers"]["x-upsert"] == "true"
    assert cap["content"] == b"jpegbytes"
    # Public URL is what gets persisted on the profile.
    assert url.startswith("https://proj.supabase.co/storage/v1/object/public/avatars/player-123/")


async def test_upload_avatar_unconfigured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_key", "")
    with pytest.raises(StorageError):
        await upload_avatar("p1", b"x", "image/jpeg")


async def test_upload_avatar_unsupported_type_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "key")
    with pytest.raises(StorageError):
        await upload_avatar("p1", b"x", "text/plain")


async def test_upload_avatar_storage_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "key")

    class _FailClient(_FakeClient):
        async def post(
            self, url: str, content: bytes | None = None, headers: dict | None = None
        ) -> _Resp:
            return _Resp(403, "forbidden")

    monkeypatch.setattr(storage.httpx, "AsyncClient", _FailClient)
    with pytest.raises(StorageError):
        await upload_avatar("p1", b"x", "image/jpeg")
