"""A Backblaze 503, 408, other 5xx or dropped connection is retried (22 Nov 2026).

Sunday's full archive uploaded, then Backblaze answered the second upload with HTTP
503 and the week's offsite pair was lost: ``backup_offsite`` failed on the first
error. Backblaze's integration checklist asks a client to get a new upload URL and
try again after a dropped connection, a timeout, 408 or any 5xx, and to back off
(honouring ``Retry-After``) before retrying its other calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.services import backup_offsite
from src.services.backup_offsite import BackupBucket, export_backup_pair

BODY = b"age-encryption.org/v1\nsynthetic ciphertext"


def _auth() -> dict[str, Any]:
    return {
        "authorizationToken": "private-token",
        "apiInfo": {
            "storageApi": {
                "apiUrl": "https://api001.backblazeb2.com",
                "downloadUrl": "https://f001.backblazeb2.com",
                "allowed": {
                    "buckets": [{"id": "bucket"}],
                    "namePrefix": "coach/",
                    "capabilities": ["writeFiles"],
                },
            }
        },
    }


def _receipt(req: httpx.Request) -> httpx.Response:
    name = req.headers["X-Bz-File-Name"]
    return httpx.Response(
        200,
        json={
            "contentLength": len(req.content),
            "fileName": name,
            "contentSha1": hashlib.sha1(req.content).hexdigest(),
            "bucketId": "bucket",
        },
    )


class Backblaze:
    """A fake B2: each upload URL is handed out once, and uploads answer from a script."""

    def __init__(self, upload_answers: list[Any]) -> None:
        self.upload_answers = upload_answers
        self.upload_urls_issued = 0
        self.uploads: list[httpx.Request] = []
        self.calls: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("b2_authorize_account"):
            self.calls.append("authorize")
            return httpx.Response(200, json=_auth())
        if path.endswith("b2_get_upload_url"):
            self.calls.append("get_upload_url")
            self.upload_urls_issued += 1
            n = self.upload_urls_issued
            return httpx.Response(
                200,
                json={
                    "uploadUrl": f"https://pod-{n:03d}.backblaze.com/upload",
                    "authorizationToken": f"upload-token-{n}",
                },
            )
        self.calls.append("upload")
        self.uploads.append(req)
        assert req.url.host == f"pod-{self.upload_urls_issued:03d}.backblaze.com"
        assert req.headers["Authorization"] == f"upload-token-{self.upload_urls_issued}"
        assert req.content == BODY or req.content.startswith(b"age-encryption.org/v1\n")
        answer = self.upload_answers.pop(0) if self.upload_answers else 200
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx.Response):
            return answer
        if answer == 200:
            return _receipt(req)
        return httpx.Response(answer, json={"code": "service_unavailable", "message": "busy"})


@pytest.fixture
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waited: list[float] = []

    async def pause(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr(backup_offsite, "_pause", pause)
    return waited


def _cipher(tmp_path: Path, name: str = "coach_full_20261122_030000.dump.age") -> Path:
    path = tmp_path / name
    path.write_bytes(BODY)
    return path


async def _upload(fake: Backblaze, path: Path) -> int:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        bucket = BackupBucket(client, "bucket")
        await bucket.authorize("id", "key", writer=True)
        return await bucket.upload(path)


@pytest.mark.asyncio
async def test_a_503_on_upload_gets_a_new_upload_url_and_succeeds(
    tmp_path: Path, pauses: list[float]
) -> None:
    fake = Backblaze([503, 200])
    assert await _upload(fake, _cipher(tmp_path)) == len(BODY)
    assert fake.calls == ["authorize", "get_upload_url", "upload", "get_upload_url", "upload"]
    assert [req.content for req in fake.uploads] == [BODY, BODY]
    assert pauses == [1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [408, 500, 502, 503, 504])
async def test_every_status_backblaze_asks_us_to_retry_is_retried(
    tmp_path: Path, pauses: list[float], answer: int
) -> None:
    fake = Backblaze([answer, answer, 200])
    assert await _upload(fake, _cipher(tmp_path)) == len(BODY)
    assert fake.upload_urls_issued == 3
    assert pauses == [1.0, 2.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_a_dropped_connection_is_retried_with_a_new_upload_url(
    tmp_path: Path, pauses: list[float], kind: type[httpx.TransportError]
) -> None:
    fake = Backblaze([kind("connection lost"), 200])
    assert await _upload(fake, _cipher(tmp_path)) == len(BODY)
    assert fake.upload_urls_issued == 2
    assert pauses == [1.0]


@pytest.mark.asyncio
async def test_retry_after_is_honoured_and_capped(tmp_path: Path, pauses: list[float]) -> None:
    fake = Backblaze(
        [
            httpx.Response(503, headers={"Retry-After": "3"}),
            httpx.Response(503, headers={"Retry-After": "86400"}),
            200,
        ]
    )
    assert await _upload(fake, _cipher(tmp_path)) == len(BODY)
    assert pauses == [3.0, backup_offsite.MAX_RETRY_AFTER_S]


@pytest.mark.asyncio
async def test_a_lasting_503_fails_after_the_last_attempt_with_the_status_only(
    tmp_path: Path, pauses: list[float]
) -> None:
    fake = Backblaze([503] * backup_offsite.B2_ATTEMPTS)
    with pytest.raises(RuntimeError) as failure:
        await _upload(fake, _cipher(tmp_path))
    assert str(failure.value) == "backup_b2_http_503"
    assert len(fake.uploads) == backup_offsite.B2_ATTEMPTS
    assert pauses == list(backup_offsite.B2_RETRY_DELAYS_S)


@pytest.mark.asyncio
async def test_a_connection_that_never_comes_back_fails_without_provider_text(
    tmp_path: Path, pauses: list[float]
) -> None:
    fake = Backblaze([httpx.ConnectError("upload-token-1 pod-001")] * backup_offsite.B2_ATTEMPTS)
    with pytest.raises(RuntimeError) as failure:
        await _upload(fake, _cipher(tmp_path))
    assert str(failure.value) == "backup_b2_unreachable"
    assert len(fake.uploads) == backup_offsite.B2_ATTEMPTS


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [400, 401, 403, 404])
async def test_a_client_error_is_not_retried(
    tmp_path: Path, pauses: list[float], answer: int
) -> None:
    fake = Backblaze([answer])
    with pytest.raises(RuntimeError, match=f"backup_b2_http_{answer}"):
        await _upload(fake, _cipher(tmp_path))
    assert len(fake.uploads) == 1
    assert pauses == []


@pytest.mark.asyncio
async def test_a_busy_api_call_backs_off_and_retries(tmp_path: Path, pauses: list[float]) -> None:
    answers = iter([httpx.Response(503), httpx.Response(429, headers={"Retry-After": "2"})])

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("b2_authorize_account"):
            return httpx.Response(200, json=_auth())
        if req.url.path.endswith("b2_get_upload_url"):
            nxt = next(answers, None)
            if nxt is not None:
                return nxt
            return httpx.Response(
                200,
                json={
                    "uploadUrl": "https://pod-001.backblaze.com/upload",
                    "authorizationToken": "upload-token-1",
                },
            )
        return _receipt(req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bucket = BackupBucket(client, "bucket")
        await bucket.authorize("id", "key", writer=True)
        assert await bucket.upload(_cipher(tmp_path)) == len(BODY)
    assert pauses == [1.0, 2.0]


@pytest.mark.asyncio
async def test_the_22_nov_failure_now_exports_the_whole_pair(
    tmp_path: Path, pauses: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full archive uploads; the nightly's first upload gets a 503; the pair still lands."""

    tmp_path.chmod(0o700)
    _cipher(tmp_path, "coach_full_20261122_030000.dump.age")
    _cipher(tmp_path, "coach_20261121_030000.dump.age")
    fake = Backblaze([200, 503, 200])
    original = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return original(transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr(backup_offsite.httpx, "AsyncClient", client)
    counters = await export_backup_pair(str(tmp_path), bucket_id="bucket", key_id="id", key="key")
    assert counters == {"offsite_archives": 2, "offsite_bytes": 2 * len(BODY)}
    names = [req.headers["X-Bz-File-Name"] for req in fake.uploads]
    assert names == [
        "coach/coach_full_20261122_030000.dump.age",
        "coach/coach_20261121_030000.dump.age",
        "coach/coach_20261121_030000.dump.age",
    ]
    assert pauses == [1.0]
