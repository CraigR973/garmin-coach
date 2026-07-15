"""Hosted read-aloud voice: opt-in consent toggle + synthesis proxy (Batch 116).

The brief's default read-aloud path is on-device `SpeechSynthesis` (Batch 106
/ 111, DECISIONS #179 / #184) — text never leaves the browser. This router
adds an explicit, off-by-default alternative: once a user flips
`Profile.hosted_tts_consent` on via `PUT /consent`, the frontend may call
`POST /synthesize` to have brief text read in a natural voice via a
self-hosted Piper model (DECISIONS #190 — swapped in for an earlier
OpenAI-hosted engine so brief text never leaves our own infra). Consent is
required on every call, not just remembered client-side, so a stale client
can never silently start generating audio the user hasn't opted into.

Synthesized audio is cached in-process only (never persisted), consistent
with #179's "read aloud, keep nothing" precedent for this feature.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.config import settings
from src.database import get_db
from src.services.piper_tts import PiperTTSError, synthesize_speech
from src.services.tts_cache import MAX_TEXT_LENGTH, cache_get, cache_key, cache_put

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    if not Path(settings.piper_voice_model_path).is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hosted read-aloud voice is not configured.",
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    text = text[:MAX_TEXT_LENGTH]

    key = cache_key(text)
    cached = cache_get(key)
    if cached is not None:
        return Response(content=cached, media_type="audio/wav")

    try:
        result = await synthesize_speech(
            model_path=settings.piper_voice_model_path,
            config_path=settings.piper_voice_config_path,
            text=text,
        )
    except PiperTTSError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="the hosted voice could not be reached",
        ) from exc

    cache_put(key, result.audio_bytes)
    return Response(content=result.audio_bytes, media_type=result.content_type)
