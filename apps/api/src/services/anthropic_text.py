"""Shared Anthropic text-generation boundary for Garmin Coach analyses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class AnthropicTextResult:
    output_markdown: str
    raw_response: dict[str, Any]
    model_name: str


async def generate_anthropic_text(
    *,
    api_key: str,
    model_name: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
    error_cls: type[Exception],
) -> AnthropicTextResult:
    payload: dict[str, Any] = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=payload)
        response.raise_for_status()
        raw = response.json()

    if not isinstance(raw, dict):
        raise error_cls("Claude response was not a JSON object.")

    stop_reason = raw.get("stop_reason")
    if stop_reason == "max_tokens":
        raise error_cls("Claude response hit max_tokens before completing.")

    text_parts: list[str] = []
    content = raw.get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
    output = "\n\n".join(text_parts).strip()
    if not output:
        raise error_cls("Claude response did not contain text output.")

    model = raw.get("model")
    return AnthropicTextResult(
        output_markdown=output,
        raw_response=raw,
        model_name=model if isinstance(model, str) else model_name,
    )
