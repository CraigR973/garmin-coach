"""Supabase Storage uploads via the service-role key (server-side).

The app authenticates with its own name+PIN JWT, **not** Supabase Auth, so the
browser's anon Supabase client never establishes a Supabase session — in Storage
RLS ``auth.uid()`` is NULL and the avatars bucket's owner-insert policy can never
pass (this is the "new row violates row-level security policy" error seen on
direct browser uploads). Uploading from the backend with the service-role key
bypasses RLS entirely, which is the correct path for this auth model.
"""

import time

import httpx
import structlog

from src.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

AVATAR_BUCKET = "avatars"

# Server-side cap on the received image body. The client resizes before upload,
# but we guard here too. Kept in sync with the avatars bucket file_size_limit.
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB

# Accepted content types → stored file extension.
_EXT_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

ALLOWED_AVATAR_TYPES = frozenset(_EXT_BY_TYPE)


class StorageError(RuntimeError):
    """Raised when the Supabase Storage upload fails or is misconfigured."""


async def upload_avatar(player_id: str, content: bytes, content_type: str) -> str:
    """Upload avatar bytes to the avatars bucket; return the public URL.

    Uses the service-role key so the upload bypasses RLS. The object key is
    ``<player_id>/<timestamp>.<ext>`` — the player-id prefix namespaces each
    player's uploads and matches the bucket's path convention.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise StorageError("Supabase storage is not configured")

    ext = _EXT_BY_TYPE.get(content_type)
    if ext is None:
        raise StorageError(f"Unsupported content type: {content_type}")

    key = f"{player_id}/{int(time.time() * 1000)}.{ext}"
    base = settings.supabase_url.rstrip("/")
    upload_url = f"{base}/storage/v1/object/{AVATAR_BUCKET}/{key}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            upload_url,
            content=content,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": content_type,
                "x-upsert": "true",
                "cache-control": "max-age=3600",
            },
        )

    if resp.status_code not in (200, 201):
        log.error(
            "avatar upload failed",
            player_id=player_id,
            status=resp.status_code,
            body=resp.text[:500],
        )
        raise StorageError(f"Storage upload failed ({resp.status_code})")

    # Public bucket → object is served at the /public/ path without auth.
    return f"{base}/storage/v1/object/public/{AVATAR_BUCKET}/{key}"
