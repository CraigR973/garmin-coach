"""Warms the hosted-voice audio cache right after a morning brief is
generated, so a consenting user's first "Listen" tap is often already cached
instead of waiting through a full synthesis (DECISIONS #197 measured ~30s for
a full brief at `medium` quality).

Opt-in only, same gate as the on-demand path: a no-op unless
`Profile.hosted_tts_consent` is already true at generation time. Never raises
— a pre-generation failure (Piper down, timeout, model missing) must not
break brief generation itself; the on-demand `POST /tts/synthesize` path
(with its own on-device fallback) is still there as a backstop.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from src.config import settings
from src.models.coaching import Analysis
from src.models.profile import Profile
from src.services.markdown_speech import markdown_to_speech_text
from src.services.piper_tts import PiperTTSError, synthesize_speech
from src.services.tts_cache import MAX_TEXT_LENGTH, cache_get, cache_key, cache_put

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def pregenerate_brief_audio(player: Profile, analysis: Analysis) -> None:
    if not player.hosted_tts_consent:
        return
    if not Path(settings.piper_voice_model_path).is_file():
        return

    text = markdown_to_speech_text(analysis.output_markdown).strip()
    if not text:
        return
    text = text[:MAX_TEXT_LENGTH]

    key = cache_key(text)
    if cache_get(key) is not None:
        return

    try:
        result = await synthesize_speech(
            model_path=settings.piper_voice_model_path,
            config_path=settings.piper_voice_config_path,
            text=text,
        )
    except PiperTTSError as exc:
        log.warning("tts_pregenerate_failed", analysis_id=str(analysis.id), error=str(exc))
        return

    cache_put(key, result.audio_bytes)
    log.info("tts_pregenerate_succeeded", analysis_id=str(analysis.id))
