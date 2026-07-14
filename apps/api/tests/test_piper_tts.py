from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.piper_tts import PiperTTSError, synthesize_speech


def _fake_completed(*, returncode: int = 0, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["piper"], returncode=returncode, stdout=b"", stderr=stderr
    )


@pytest.mark.asyncio
async def test_synthesize_speech_returns_wav_bytes(tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"fake-model")
    config_path = tmp_path / "voice.onnx.json"
    config_path.write_text("{}")

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        output_path = Path(cmd[cmd.index("--output_file") + 1])
        output_path.write_bytes(b"wav-bytes")
        return _fake_completed()

    with patch("src.services.piper_tts.subprocess.run", side_effect=_fake_run):
        result = await synthesize_speech(
            model_path=str(model_path), config_path=str(config_path), text="Train as planned today."
        )

    assert result.audio_bytes == b"wav-bytes"
    assert result.content_type == "audio/wav"


@pytest.mark.asyncio
async def test_synthesize_speech_raises_when_model_missing(tmp_path: Path) -> None:
    missing_model = tmp_path / "missing.onnx"
    with pytest.raises(PiperTTSError, match="not found"):
        await synthesize_speech(
            model_path=str(missing_model), config_path=str(tmp_path / "c.json"), text="hi"
        )


@pytest.mark.asyncio
async def test_synthesize_speech_raises_on_nonzero_exit(tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"fake-model")
    config_path = tmp_path / "voice.onnx.json"
    config_path.write_text("{}")

    with patch(
        "src.services.piper_tts.subprocess.run",
        return_value=_fake_completed(returncode=1, stderr=b"boom"),
    ):
        with pytest.raises(PiperTTSError, match="boom"):
            await synthesize_speech(
                model_path=str(model_path), config_path=str(config_path), text="hi"
            )


@pytest.mark.asyncio
async def test_synthesize_speech_raises_on_timeout(tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"fake-model")
    config_path = tmp_path / "voice.onnx.json"
    config_path.write_text("{}")

    with patch(
        "src.services.piper_tts.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="piper", timeout=45),
    ):
        with pytest.raises(PiperTTSError, match="failed to run"):
            await synthesize_speech(
                model_path=str(model_path), config_path=str(config_path), text="hi"
            )
