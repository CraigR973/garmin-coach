"""Bucket/prefix-scoped B2 native API; no delete API and no plaintext uploads."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from src.services.backup import _is_full, _safe_filename, _stamp, list_backups

PREFIX = "coach/"
MAX_OBJECT_BYTES = 500_000_000


def _provider_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not host.endswith((".backblazeb2.com", ".backblaze.com"))
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise RuntimeError("backup_b2_endpoint_invalid")
    return url.rstrip("/")


def _digest(path: Path, algorithm: str) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


@dataclass(frozen=True)
class RemoteArchive:
    filename: str
    file_id: str
    size_bytes: int
    sha1: str
    sha256: str


class BackupBucket:
    """One authorised key, never accepted merely on its console label."""

    def __init__(self, client: httpx.AsyncClient, bucket_id: str) -> None:
        if not bucket_id:
            raise RuntimeError("backup_b2_bucket_unset")
        self.client = client
        self.bucket_id = bucket_id
        self.api_url = ""
        self.token = ""
        self.download_url = ""

    async def authorize(self, key_id: str, key: str, *, writer: bool) -> None:
        if not key_id or not key:
            raise RuntimeError("backup_b2_credentials_unset")
        response = await self.client.get(
            "https://api.backblazeb2.com/b2api/v4/b2_authorize_account",
            auth=(key_id, key),
        )
        self._check(response)
        data = response.json()
        storage = data["apiInfo"]["storageApi"]
        allowed = storage["allowed"]
        caps = set(allowed["capabilities"])
        required = {"writeFiles"} if writer else {"listFiles", "readFiles"}
        # Harmless bucket metadata permissions are allowed; no delete, key admin,
        # bucket mutation, share token or read/write crossover.
        permitted = required | {"listBuckets", "readBuckets", "listAllBucketNames"}
        if (
            allowed.get("buckets") is None
            or {b["id"] for b in allowed["buckets"]} != {self.bucket_id}
            or allowed.get("namePrefix") != PREFIX
            or not required <= caps <= permitted
        ):
            raise RuntimeError("backup_b2_key_scope_rejected")
        self.api_url = _provider_url(storage["apiUrl"])
        self.token = data["authorizationToken"]
        self.download_url = _provider_url(storage["downloadUrl"])

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if not response.is_success:
            # Provider bodies/headers are never included: they can carry credentials.
            raise RuntimeError(f"backup_b2_http_{response.status_code}")

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("backup_b2_not_authorized")
        response = await self.client.post(
            f"{self.api_url}/b2api/v4/{method}",
            headers={"Authorization": self.token},
            json=payload,
        )
        self._check(response)
        data: dict[str, Any] = response.json()
        return data

    async def upload(self, path: Path) -> int:
        if not path.name.endswith(".dump.age") or not _safe_filename(path.name):
            raise RuntimeError("backup_offsite_ciphertext_only")
        if path.is_symlink():
            raise RuntimeError("backup_offsite_symlink_rejected")
        with path.open("rb") as source:
            if source.read(22) != b"age-encryption.org/v1\n":
                raise RuntimeError("backup_offsite_ciphertext_only")
        size = path.stat().st_size
        if not 0 < size <= MAX_OBJECT_BYTES:
            raise RuntimeError("backup_object_size_rejected")
        sha1, sha256 = _digest(path, "sha1"), _digest(path, "sha256")
        upload = await self._call("b2_get_upload_url", {"bucketId": self.bucket_id})

        async def chunks() -> AsyncIterator[bytes]:
            with path.open("rb") as stream:
                while chunk := stream.read(1 << 20):
                    yield chunk

        response = await self.client.post(
            _provider_url(upload["uploadUrl"]),
            headers={
                "Authorization": upload["authorizationToken"],
                "X-Bz-File-Name": quote(PREFIX + path.name, safe="/"),
                "Content-Type": "application/octet-stream",
                "Content-Length": str(size),
                "X-Bz-Content-Sha1": sha1,
                "X-Bz-Info-sha256": sha256,
            },
            content=chunks(),
        )
        self._check(response)
        result = response.json()
        if (
            result.get("contentSha1") != sha1
            or result.get("contentLength") != size
            or result.get("fileName") != PREFIX + path.name
            or result.get("bucketId") != self.bucket_id
        ):
            raise RuntimeError("backup_upload_receipt_mismatch")
        return size

    async def latest_pair(self, *, now: datetime | None = None) -> list[RemoteArchive]:
        files: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(100):
            data = await self._call(
                "b2_list_file_names",
                {
                    "bucketId": self.bucket_id,
                    "prefix": PREFIX,
                    "maxFileCount": 1000,
                    "startFileName": cursor,
                },
            )
            files.extend(data["files"])
            next_cursor = data.get("nextFileName")
            if next_cursor is None:
                break
            if next_cursor == cursor:
                raise RuntimeError("backup_listing_cursor_stalled")
            cursor = next_cursor
        else:
            raise RuntimeError("backup_listing_limit_exceeded")
        now = now or datetime.now(UTC)
        chosen: list[RemoteArchive] = []
        for full, max_age in ((True, timedelta(days=8)), (False, timedelta(days=8))):
            candidates = [
                f
                for f in files
                if f.get("action") == "upload"
                and f.get("fileName", "").startswith(PREFIX)
                and _safe_filename(f["fileName"].removeprefix(PREFIX))
                and f["fileName"].endswith(".dump.age")
                and _is_full(f["fileName"].removeprefix(PREFIX)) == full
            ]
            if not candidates:
                raise RuntimeError("backup_offsite_pair_incomplete")
            f = max(candidates, key=lambda f: _stamp(f["fileName"].removeprefix(PREFIX)))
            name = f["fileName"].removeprefix(PREFIX)
            written = datetime.strptime(_stamp(name), "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
            if not timedelta(0) <= now - written <= max_age:
                raise RuntimeError("backup_offsite_archive_stale_or_future")
            chosen.append(
                RemoteArchive(
                    name,
                    f["fileId"],
                    f["contentLength"],
                    f["contentSha1"],
                    f.get("fileInfo", {}).get("sha256", ""),
                )
            )
        return chosen

    async def download(self, archive: RemoteArchive, target: Path) -> None:
        if not 0 < archive.size_bytes <= MAX_OBJECT_BYTES or len(archive.sha256) != 64:
            raise RuntimeError("backup_download_metadata_rejected")
        # Open exclusively and never follow a caller-supplied existing file/symlink.
        total = 0
        created = False
        try:
            with target.open("xb") as stream:
                created = True
                target.chmod(0o600)
                async with self.client.stream(
                    "GET",
                    f"{self.download_url}/b2api/v4/b2_download_file_by_id",
                    params={"fileId": archive.file_id},
                    headers={"Authorization": self.token},
                ) as response:
                    self._check(response)
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > archive.size_bytes:
                            raise RuntimeError("backup_download_size_mismatch")
                        stream.write(chunk)
            if (
                total != archive.size_bytes
                or _digest(target, "sha1") != archive.sha1
                or _digest(target, "sha256") != archive.sha256
            ):
                raise RuntimeError("backup_download_checksum_mismatch")
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise


async def export_backup_pair(
    backup_dir: str, *, bucket_id: str, key_id: str, key: str
) -> dict[str, int]:
    pair = []
    for full in (True, False):
        candidates = [
            b
            for b in list_backups(backup_dir)
            if b.full == full and b.filename.endswith(".dump.age")
        ]
        if not candidates:
            raise RuntimeError("backup_encrypted_pair_incomplete")
        pair.append(candidates[0])
    async with httpx.AsyncClient(timeout=300) as client:
        bucket = BackupBucket(client, bucket_id)
        await bucket.authorize(key_id, key, writer=True)
        sizes = [await bucket.upload(Path(backup_dir) / b.filename) for b in pair]
    return {"offsite_archives": len(sizes), "offsite_bytes": sum(sizes)}
