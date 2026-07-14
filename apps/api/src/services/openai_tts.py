"""Shared OpenAI TTS boundary for the hosted read-aloud voice (Batch 116).

Opt-in only — see `Profile.hosted_tts_consent` and `routers/tts.py`. Brief text
only reaches this module once a user has explicitly consented; callers must
enforce that gate themselves, this module just makes the external call.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"


class OpenAITTSError(Exception):
    """Raised when the OpenAI TTS API cannot produce audio."""


@dataclass(frozen=True)
class OpenAITTSResult:
    audio_bytes: bytes
    content_type: str


async def synthesize_speech(
    *,
    api_key: str,
    model_name: str,
    voice: str,
    text: str,
) -> OpenAITTSResult:
    payload = {
        "model": model_name,
        "voice": voice,
        "input": text,
        "response_format": "mp3",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(OPENAI_TTS_URL, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenAITTSError("OpenAI TTS request failed.") from exc

    if not response.content:
        raise OpenAITTSError("OpenAI TTS response did not contain audio.")

    return OpenAITTSResult(audio_bytes=response.content, content_type="audio/mpeg")
