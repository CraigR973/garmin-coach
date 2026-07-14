"""Self-hosted Piper TTS boundary for the hosted read-aloud voice (Batch 116
follow-up, DECISIONS #190 — swapped in for the original OpenAI-hosted engine
so brief text never leaves our own infra, removing both the per-use API cost
and the third-party-data question).

Opt-in only — see `Profile.hosted_tts_consent` and `routers/tts.py`. Brief
text only reaches this module once a user has explicitly consented; callers
must enforce that gate themselves, this module just runs the synthesis.

Shells out to the `piper` console script (installed by the `piper-tts` pip
package) rather than using its Python API directly: the CLI surface is far
more stable across Piper releases than the in-process API, which has changed
shape more than once. Runs synchronously in a thread since synthesis is
CPU-bound, not I/O-bound.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# A `medium`-quality voice took >45s to synthesize a full brief on Railway's
# CPU and timed out in production (DECISIONS #191) — the voice model moved to
# `low` quality for speed, but this stays generous as a safety margin since
# synthesis speed on shared CPU is still not something verified ahead of time.
PIPER_TIMEOUT_SECONDS = 60


class PiperTTSError(Exception):
    """Raised when Piper cannot produce audio."""


@dataclass(frozen=True)
class PiperTTSResult:
    audio_bytes: bytes
    content_type: str


def _run_piper(*, model_path: str, config_path: str, text: str) -> bytes:
    if not Path(model_path).is_file():
        raise PiperTTSError(f"Piper voice model not found at {model_path}.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "speech.wav"
        try:
            result = subprocess.run(
                [
                    "piper",
                    "--model",
                    model_path,
                    "--config",
                    config_path,
                    "--output_file",
                    str(output_path),
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=PIPER_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PiperTTSError("Piper process failed to run.") from exc

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise PiperTTSError(f"Piper exited with {result.returncode}: {stderr}")

        if not output_path.is_file():
            raise PiperTTSError("Piper did not produce an output file.")

        audio_bytes = output_path.read_bytes()

    if not audio_bytes:
        raise PiperTTSError("Piper produced an empty audio file.")

    return audio_bytes


async def synthesize_speech(
    *,
    model_path: str,
    config_path: str,
    text: str,
) -> PiperTTSResult:
    audio_bytes = await asyncio.to_thread(
        _run_piper, model_path=model_path, config_path=config_path, text=text
    )
    return PiperTTSResult(audio_bytes=audio_bytes, content_type="audio/wav")
