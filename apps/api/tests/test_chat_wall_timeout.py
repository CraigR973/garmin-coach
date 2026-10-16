"""The chat request has one wall clock budget across provider/tool rounds."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import settings
from src.services.anthropic_text import AnthropicApiError
from src.services.brief_chat import AnthropicBriefChatClient


@pytest.mark.asyncio
@pytest.mark.parametrize("with_toolbox", [False, True])
async def test_stalled_chat_cancels_and_uses_existing_timeout_error(
    monkeypatch: pytest.MonkeyPatch, with_toolbox: bool
) -> None:
    monkeypatch.setattr(settings, "anthropic_chat_wall_timeout_seconds", 0.01)
    cancelled = False

    async def stalled_answer(**kwargs: object) -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        finally:
            cancelled = True

    target = (
        "src.services.brief_chat.generate_anthropic_text_with_tools"
        if with_toolbox
        else "src.services.brief_chat.generate_anthropic_text"
    )
    monkeypatch.setattr(target, stalled_answer)
    toolbox = SimpleNamespace(execute=Mock()) if with_toolbox else None

    with pytest.raises(AnthropicApiError) as caught:
        await AnthropicBriefChatClient(api_key="test-key").generate(
            system_prompt="system",
            user_prompt="Why is today easier?",
            prior_messages=[],
            toolbox=toolbox,  # type: ignore[arg-type]
        )

    assert caught.value.reason == "timeout"
    assert caught.value.status_code == 0
    assert cancelled
