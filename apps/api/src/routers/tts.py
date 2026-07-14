"""Hosted read-aloud voice: opt-in consent toggle + synthesis proxy (Batch 116).

The brief's default read-aloud path is on-device `SpeechSynthesis` (Batch 106
/ 111, DECISIONS #179 / #184) — text never leaves the browser. This router
adds an explicit, off-by-default alternative: once a user flips
`Profile.hosted_tts_consent` on via `PUT /consent`, the frontend may call
`POST /synthesize` to have brief text read in a natural hosted voice via
OpenAI's TTS API. Consent is required on every call, not just remembered
client-side, so a stale client can never silently start sending health-data
text to a third party.

Synthesized audio is cached in-process only (never persisted), consistent
with #179's "read aloud, keep nothing" precedent for this feature.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.config import settings
from src.database import get_db
from src.services.openai_tts import OpenAITTSError, synthesize_speech

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])

# Cost/abuse guard — briefs are a few hundred to a couple of thousand words;
# this comfortably covers a full brief with room to spare.
MAX_TEXT_LENGTH = 6000
_CACHE_MAX_ENTRIES = 20

# Process-local only (see module docstring) — a dict is enough for a
# single-instance API process; entries evict oldest-first once full.
_audio_cache: OrderedDict[str, bytes] = OrderedDict()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _cache_key(text: str) -> str:
    raw = f"{settings.openai_tts_model}:{settings.openai_tts_voice}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> bytes | None:
    audio = _audio_cache.get(key)
    if audio is not None:
        _audio_cache.move_to_end(key)
    return audio


def _cache_put(key: str, audio: bytes) -> None:
    _audio_cache[key] = audio
    _audio_cache.move_to_end(key)
    while len(_audio_cache) > _CACHE_MAX_ENTRIES:
        _audio_cache.popitem(last=False)


class ConsentBody(BaseModel):
    enabled: bool


class ConsentData(BaseModel):
    hostedTtsConsent: bool


class ConsentMeta(BaseModel):
    generatedAtUtc: str


class ConsentEnvelope(BaseModel):
    data: ConsentData
    meta: ConsentMeta
    errors: list[str] = Field(default_factory=list)


class SynthesizeBody(BaseModel):
    text: str


@router.put("/consent", response_model=ConsentEnvelope)
async def set_hosted_tts_consent(
    body: ConsentBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConsentEnvelope:
    player.hosted_tts_consent = body.enabled
    await db.commit()
    return ConsentEnvelope(
        data=ConsentData(hostedTtsConsent=player.hosted_tts_consent),
        meta=ConsentMeta(generatedAtUtc=_now()),
    )


@router.post("/synthesize")
async def synthesize(body: SynthesizeBody, player: CurrentUser) -> Response:
    if not player.hosted_tts_consent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hosted read-aloud voice is not enabled for this account.",
        )
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hosted read-aloud voice is not configured.",
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    text = text[:MAX_TEXT_LENGTH]

    key = _cache_key(text)
    cached = _cache_get(key)
    if cached is not None:
        return Response(content=cached, media_type="audio/mpeg")

    try:
        result = await synthesize_speech(
            api_key=settings.openai_api_key,
            model_name=settings.openai_tts_model,
            voice=settings.openai_tts_voice,
            text=text,
        )
    except OpenAITTSError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="the hosted voice could not be reached",
        ) from exc

    _cache_put(key, result.audio_bytes)
    return Response(content=result.audio_bytes, media_type=result.content_type)
