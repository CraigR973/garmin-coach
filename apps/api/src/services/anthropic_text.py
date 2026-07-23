"""Shared Anthropic text-generation boundary for Garmin Coach analyses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class AnthropicTextResult:
    output_markdown: str
    raw_response: dict[str, Any]
    model_name: str


class AnthropicApiError(RuntimeError):
    """A non-2xx from the Anthropic Messages API, carrying a classified ``reason``.

    ``reason`` is a stable, log-safe slug (``billing`` / ``rate_limit`` / ``auth`` /
    ``overloaded`` / ``prompt_too_long`` / ``invalid_request`` / ``server_error`` /
    ``other``) so a caller can act on the *class* of failure — notably firing the
    admin billing alert (Batch 141) — without re-parsing the provider's prose. The
    eight analysis callers all catch ``Exception``, so raising this distinct type on
    the HTTP path (the parse/semantic failures below still raise the caller's
    ``error_cls``) doesn't change any existing handler.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        status_code: int,
        anthropic_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code
        self.anthropic_type = anthropic_type


def classify_anthropic_error(
    status_code: int, *, error_type: str | None, error_message: str | None
) -> str:
    """Map an Anthropic error response to a stable reason slug (Batch 141).

    The credit-exhaustion case that froze the brief on 2026-07-21 arrives as a
    **400** ``invalid_request_error`` whose *message* names the credit balance — it
    can't be told from an ordinary bad request by status code alone, so the message
    is the signal and is checked first. Deterministic and case-folded for a reliable
    ``billing`` classification (which is what raises the admin alert).
    """
    message = (error_message or "").lower()
    etype = (error_type or "").lower()
    if "credit balance" in message or "plans & billing" in message or "billing" in message:
        return "billing"
    if status_code == 429 or etype == "rate_limit_error":
        return "rate_limit"
    if status_code in (401, 403) or etype == "authentication_error":
        return "auth"
    if status_code == 529 or etype == "overloaded_error":
        return "overloaded"
    if "prompt is too long" in message or "max_tokens" in message:
        return "prompt_too_long"
    if status_code >= 500:
        return "server_error"
    if status_code == 400:
        return "invalid_request"
    return "other"


def _error_from_http_status(exc: httpx.HTTPStatusError) -> AnthropicApiError:
    """Parse + log an Anthropic non-2xx into a classified error (Batch 141).

    ``httpx``'s ``raise_for_status`` discards the response body, so the *reason*
    (e.g. "Your credit balance is too low…") never reached the logs — recovering it
    on 2026-07-21 needed a manual out-of-band API call. Read the body here and log
    the provider's ``error.type`` / ``error.message``. The API key is never logged:
    it travels only in the request ``x-api-key`` header and is never echoed in a
    response body.
    """
    response = exc.response
    status_code = response.status_code
    error_type: str | None = None
    error_message: str | None = None
    try:
        body = response.json()
    except Exception:  # pragma: no cover - non-JSON error body is rare
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            raw_type = err.get("type")
            raw_message = err.get("message")
            error_type = raw_type if isinstance(raw_type, str) else None
            error_message = raw_message if isinstance(raw_message, str) else None
    reason = classify_anthropic_error(
        status_code, error_type=error_type, error_message=error_message
    )
    log.error(
        "anthropic_api_error",
        status_code=status_code,
        reason=reason,
        anthropic_type=error_type,
        anthropic_message=error_message,
    )
    detail = error_message or f"Anthropic API returned HTTP {status_code}."
    return AnthropicApiError(
        detail, reason=reason, status_code=status_code, anthropic_type=error_type
    )


async def generate_anthropic_text(
    *,
    api_key: str,
    model_name: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
    error_cls: type[Exception],
    prior_messages: list[dict[str, str]] | None = None,
) -> AnthropicTextResult:
    """``prior_messages`` (optional) carries earlier user/assistant turns before
    ``user_prompt`` for a multi-turn conversation (Batch 119's brief follow-up
    chat); single-turn callers omit it and behave exactly as before.

    A non-2xx from Anthropic raises :class:`AnthropicApiError` (with a classified
    ``reason``); a well-formed response that is unusable (max_tokens, no text, not a
    JSON object) still raises the caller's ``error_cls`` as before.
    """
    messages: list[dict[str, str]] = [
        *(prior_messages or []),
        {"role": "user", "content": user_prompt},
    ]
    payload: dict[str, Any] = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _error_from_http_status(exc) from exc
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
