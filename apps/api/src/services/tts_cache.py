"""In-process cache for synthesized hosted-voice audio (Batch 116).

Shared between `routers/tts.py` (serves cache hits to the frontend) and
`services/tts_pregenerate.py` (warms the cache right after a brief is
generated, so it's often already hit by the time a user taps Listen).

Process-local, in-memory only — never persisted to disk, consistent with
DECISIONS #179's "read aloud, keep nothing" precedent. A backend restart
(e.g. a deploy) between pre-generation and playback loses the warm entry;
that's an accepted tradeoff over adding audio persistence.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from src.config import settings

# Cost/abuse guard — briefs are a few hundred to a couple of thousand words;
# this comfortably covers a full brief with room to spare.
MAX_TEXT_LENGTH = 6000
_CACHE_MAX_ENTRIES = 20

_audio_cache: OrderedDict[str, bytes] = OrderedDict()


def cache_key(text: str) -> str:
    raw = f"{settings.piper_voice_model_path}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(key: str) -> bytes | None:
    audio = _audio_cache.get(key)
    if audio is not None:
        _audio_cache.move_to_end(key)
    return audio


def cache_put(key: str, audio: bytes) -> None:
    _audio_cache[key] = audio
    _audio_cache.move_to_end(key)
    while len(_audio_cache) > _CACHE_MAX_ENTRIES:
        _audio_cache.popitem(last=False)
