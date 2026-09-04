"""Shared Anthropic text-generation boundary for Garmin Coach analyses."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

import httpx
import structlog
from pydantic import BaseModel

from src.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def _timeout(*, read: float | None = None) -> httpx.Timeout:
    """Per-phase timeouts for a non-streamed Messages call.

    The single ``timeout=60.0`` this replaces applied 60s to *every* phase, so the
    read budget was really "60s for Claude to finish the whole answer" — which the
    morning brief outgrew on 2026-08-30 (measured 75.1s). Only ``read`` needs to
    scale with generation length; connect/write/pool stay short so a genuinely
    unreachable API still fails fast instead of hanging for the full read budget.
    """
    return httpx.Timeout(
        connect=10.0,
        # Batch 248: a retry shares one budget with its predecessors, so an
        # attempt gets what is left rather than the whole thing. ``None`` keeps
        # the pre-248 behaviour for every direct caller and every test.
        read=settings.anthropic_read_timeout_seconds if read is None else max(read, 1.0),
        write=30.0,
        pool=10.0,
    )


class AnthropicThinking(TypedDict):
    """The ``thinking`` request field (Batch 233.3).

    ``adaptive`` lets the model decide how much to think, steered by ``effort``.
    ``budget_tokens`` — the pre-4.6 way to ask for extended thinking — is
    **rejected with a 400** on this model generation and deliberately has no
    representation here, so it cannot be reintroduced by a caller.
    """

    type: Literal["adaptive", "disabled"]


def configured_thinking() -> AnthropicThinking:
    """The thinking mode every analysis caller passes, resolved from settings."""

    mode: Literal["adaptive", "disabled"] = (
        "disabled" if settings.anthropic_thinking_mode == "disabled" else "adaptive"
    )
    return {"type": mode}


def configured_effort() -> str:
    """The effort level every analysis caller passes, resolved from settings."""

    return settings.anthropic_effort


class AnthropicCacheControl(TypedDict):
    type: Literal["ephemeral"]


class AnthropicSystemTextBlock(TypedDict, total=False):
    type: Literal["text"]
    text: str
    cache_control: AnthropicCacheControl


AnthropicSystemPrompt = str | list[AnthropicSystemTextBlock]


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
    if (
        etype == "billing_error"
        or "credit balance" in message
        or "plans & billing" in message
        or "billing" in message
        # Batch 248 (AI238-03): a *configured spend cap* is the same outage under a
        # sentence Batch 141 never saw — HTTP 400 ``invalid_request_error`` reading
        # "You have reached your specified API usage limits", with no "billing" or
        # "credit balance" anywhere in it. It classified as ``invalid_request``, so
        # Mark got generic copy and the operator got nothing. Proved live on
        # 2026-08-31 when verification itself tripped the cap (Batch 233 gotcha 1).
        or "usage limit" in message
    ):
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


# Reasons where the coach is *temporarily* unavailable and a retry is the honest
# advice (credit outage, provider rate-limit/overload) vs a harder upstream fault.
# Drives the HTTP status a day-time caller returns when a synchronous Anthropic
# call fails (Batch 143): 503 says "try again shortly", 502 says "upstream broke".
#
# Batch 248 (AI238-04) adds ``timeout`` and ``server_error``. Both are transient by
# definition and both were landing on 502 — "upstream broke" — for the seven
# ``httpx.ReadTimeout``s of the 2026-08-30 outage, which is the wrong advice about
# the wrong thing.
_RETRYABLE_ANTHROPIC_REASONS = frozenset(
    {"billing", "rate_limit", "overloaded", "timeout", "server_error"}
)

# The subset worth *automatically* re-attempting inside one call. ``billing`` is
# excluded deliberately: a credit outage does not clear in eight seconds, and
# retrying it three times turns one failure into three identical ones in the log
# while Mark waits three times as long for the same answer.
_AUTO_RETRY_REASONS = frozenset({"rate_limit", "overloaded", "server_error", "timeout"})

# Three attempts, ~1s then ~2s apart.
#
# **The retry budget is the whole call, not each attempt**, and that is the load-
# bearing part. Batch 234 derived ``anthropic_read_timeout_seconds`` from
# ``anthropic_max_tokens``; Batch 232 derived the generation lease from *that*
# (read + 120s) and made ``validate_timeout_ordering()`` refuse to boot unless the
# lease expires before Batch 144's 720s stale-after guard. Three attempts each
# given the full read budget would be 3x550s = 1650s against a 670s lease — a
# retry outliving its own lease, handing the artifact scope to another worker
# mid-flight, which is precisely the class of defect Batch 232 exists to remove.
#
# So a deadline is set once and each attempt gets what is left of it. A fast 529
# leaves nearly the whole budget for the real attempt; a read timeout that burns
# the budget gets no retry, correctly, because there is no time left to have one.
_MAX_ANTHROPIC_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.0
# Below this there is no point starting another attempt — connect alone is 10s.
_MIN_ATTEMPT_SECONDS = 15.0


def anthropic_http_status(reason: str) -> int:
    """HTTP status for a failed *in-request* Anthropic call (Batch 143).

    503 for a transient/retryable outage (billing/rate-limit/overload), 502 for a
    hard upstream failure — never a bare 500, so the web client parses a real JSON
    body instead of the plain-text ``Internal Server Error`` that broke it on
    2026-07-20/21.
    """
    return 503 if reason in _RETRYABLE_ANTHROPIC_REASONS else 502


def anthropic_user_message(reason: str) -> str:
    """A short, honest, retryable user-facing line for a failed Anthropic call.

    Deliberately generic — the provider's billing/credit prose never reaches the
    user; the classified ``reason`` is what goes to the logs and the admin alert.
    """
    if reason in _RETRYABLE_ANTHROPIC_REASONS:
        return "The coach is briefly unavailable. Please try again in a moment."
    return "The coach couldn't answer just now. Please try again in a moment."


def _usage_int(usage: dict[str, Any], key: str) -> int | None:
    value = usage.get(key)
    return value if isinstance(value, int) else None


def _thinking_tokens(usage: dict[str, Any]) -> int | None:
    """The thinking share of ``output_tokens``, when the provider reports it.

    Batch 233: ``max_tokens`` caps thinking and text together, and on Sonnet 5 at
    ``high`` effort thinking is the overwhelming majority of the budget — a real
    morning brief measured 16,157 output tokens of which **14,610 were thinking**
    and only ~1,547 were the prose Mark reads. Without this field a future session
    reading the logs sees a single large ``output_tokens`` and cannot tell whether
    the ceiling is under pressure from a longer brief or from a deeper think, which
    are fixed in opposite ways.
    """
    details = usage.get("output_tokens_details")
    if not isinstance(details, dict):
        return None
    return _usage_int(details, "thinking_tokens")


def _log_usage(raw: dict[str, Any], *, model_name: str) -> None:
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return
    log.info(
        "anthropic_usage",
        model_name=model_name,
        input_tokens=_usage_int(usage, "input_tokens"),
        output_tokens=_usage_int(usage, "output_tokens"),
        thinking_tokens=_thinking_tokens(usage),
        cache_creation_input_tokens=_usage_int(usage, "cache_creation_input_tokens"),
        cache_read_input_tokens=_usage_int(usage, "cache_read_input_tokens"),
    )


def anthropic_error_from_http_status(exc: httpx.HTTPStatusError) -> AnthropicApiError:
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


def anthropic_error_from_transport(exc: httpx.RequestError) -> AnthropicApiError:
    """Classify a transport failure that never became an HTTP response (Batch 248).

    AI238-04, and the oldest AI-layer defect in the repo. A single `client.post`
    guarded only by `except httpx.HTTPStatusError` lets every `httpx` transport
    exception escape uncaught: `main.py` registers one exception handler and it is
    not this, so a timeout reached the *user* as a bare 500 with a plain-text body
    the web client cannot parse — the exact regression Batch 143 closed for the
    HTTP-status path — and reached the *operator* as nothing at all.

    On 2026-08-30 that was seven `httpx.ReadTimeout`s between 08:59 and 09:23,
    every one classified `other`, every one a retryable failure card that failed
    again on retry. Batch 234 raised the read budget so the immediate cause is
    gone; this closes the illegibility, which is what made the outage impossible
    to read *while it was happening*.

    A timeout is not the same event as a connection refusal, and the reason slug
    keeps them apart: `timeout` is "we may already have been billed for an answer
    we hung up on" (Batch 234's finding), `transport` is "the request never
    landed".
    """
    reason = "timeout" if isinstance(exc, httpx.TimeoutException) else "transport"
    log.error(
        "anthropic_transport_error",
        reason=reason,
        exception_type=type(exc).__name__,
        # `str(exc)` on an httpx transport error is the failure mode, never the
        # payload — the API key travels in a header and is not echoed here.
        detail=str(exc),
    )
    return AnthropicApiError(
        f"Anthropic request failed at the transport: {type(exc).__name__}.",
        reason=reason,
        # No response arrived, so there is no upstream status to report. 0 says
        # "never got one" rather than inventing a plausible-looking 5xx.
        status_code=0,
    )


async def _post_with_retry(
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    model_name: str,
) -> Any:
    """POST to Anthropic, re-attempting only the reasons a retry can actually fix.

    Batch 248 (AI238-04). Before this there was no retry anywhere in the app:
    ``_RETRYABLE_ANTHROPIC_REASONS`` only chose which sentence Mark saw, so a
    single 529 at 06:40 cost the whole morning until the 11:00 backstop.

    One change to one function covers all nine ``generate_anthropic_text``
    callers. See ``_MAX_ANTHROPIC_ATTEMPTS`` for why the budget is the call
    rather than the attempt.
    """

    budget = settings.anthropic_read_timeout_seconds
    deadline = time.monotonic() + budget
    last: AnthropicApiError | None = None

    for attempt in range(1, _MAX_ANTHROPIC_ATTEMPTS + 1):
        # The first attempt gets the budget itself, so the common path is exactly
        # what Batch 234 derived and nothing about it changed. Only a retry pays
        # for its predecessors out of the same budget.
        remaining = None if attempt == 1 else deadline - time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_timeout(read=remaining)) as client:
                response = await client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=payload)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise anthropic_error_from_http_status(exc) from exc
                return response.json()
        except httpx.RequestError as exc:
            error = anthropic_error_from_transport(exc)
        except AnthropicApiError as exc:
            error = exc
        last = error

        if error.reason not in _AUTO_RETRY_REASONS or attempt == _MAX_ANTHROPIC_ATTEMPTS:
            raise error
        delay = _RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
        if deadline - time.monotonic() - delay < _MIN_ATTEMPT_SECONDS:
            log.warning(
                "anthropic_call_not_retried",
                model_name=model_name,
                reason=error.reason,
                attempt=attempt,
                cause="budget_exhausted",
                budget_seconds=budget,
            )
            raise error
        log.warning(
            "anthropic_call_retrying",
            model_name=model_name,
            reason=error.reason,
            attempt=attempt,
            max_attempts=_MAX_ANTHROPIC_ATTEMPTS,
            delay_seconds=delay,
            remaining_seconds=round(deadline - time.monotonic(), 1),
        )
        await asyncio.sleep(delay)

    # Unreachable: the loop either returns or raises on its final attempt. Kept so
    # the contract is total rather than relying on the reader to prove it.
    raise (
        last
        if last is not None
        else AnthropicApiError(
            "Anthropic call failed with no recorded error.", reason="other", status_code=0
        )
    )


#: Constraints Anthropic's structured-output grammar does not accept. Anthropic's
#: own SDK helpers strip these before sending and then validate the response
#: against the original model; this repo keeps a thin HTTP boundary, so it makes
#: the same split explicitly — the provider gets grammar-supported structure, and
#: ``model_validate`` retains every length/range constraint locally.
#:
#: Batch 253 (AI238-10) moved this out of ``longitudinal_analysis`` so the second
#: structured caller could not re-derive it.
UNSUPPORTED_SCHEMA_CONSTRAINTS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "pattern",
    }
)


def anthropic_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A Pydantic model's JSON Schema in Anthropic's supported subset."""

    def transform(value: Any) -> Any:
        if isinstance(value, list):
            return [transform(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            key: transform(item)
            for key, item in value.items()
            if key not in UNSUPPORTED_SCHEMA_CONSTRAINTS
        }

    schema = transform(model.model_json_schema(by_alias=True))
    if not isinstance(schema, dict):  # pragma: no cover - Pydantic always returns an object
        raise TypeError("Model JSON schema was not an object.")
    return schema


async def generate_anthropic_text(
    *,
    api_key: str,
    model_name: str,
    max_tokens: int,
    system_prompt: AnthropicSystemPrompt,
    user_prompt: str,
    error_cls: type[Exception],
    prior_messages: list[dict[str, str]] | None = None,
    thinking: AnthropicThinking | None = None,
    effort: str | None = None,
    output_schema: dict[str, Any] | None = None,
) -> AnthropicTextResult:
    """``prior_messages`` (optional) carries earlier user/assistant turns before
    ``user_prompt`` for a multi-turn conversation (Batch 119's brief follow-up
    chat); single-turn callers omit it and behave exactly as before. ``system_prompt``
    may be the original string form or an Anthropic system-block list when a caller
    needs a cache breakpoint.

    ``thinking`` and ``effort`` (Batch 233.3) are **absent from the payload unless
    passed**, so a caller that supplies neither produces a byte-identical request to
    the pre-233 one. That is the rollback path, and it is pinned by a test: the two
    fields are the only wire-format difference between running this app on Sonnet 5
    and running it as it was on Sonnet 4.6.

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
    if thinking is not None:
        payload["thinking"] = thinking
    # Batch 253 (AI238-10): ``effort`` and ``format`` are two keys of **one**
    # ``output_config``. Assigning it wholesale for either would silently drop the
    # other — which for a structured caller means turning a schema-constrained
    # response back into prose, with nothing failing until the parse does.
    output_config: dict[str, Any] = {}
    if effort is not None:
        output_config["effort"] = effort
    if output_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": output_schema}
    if output_config:
        payload["output_config"] = output_config
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    raw = await _post_with_retry(headers=headers, payload=payload, model_name=model_name)

    if not isinstance(raw, dict):
        raise error_cls("Claude response was not a JSON object.")

    stop_reason = raw.get("stop_reason")
    if stop_reason == "max_tokens":
        raise error_cls("Claude response hit max_tokens before completing.")

    # Batch 233.3: with thinking on, ``content`` also carries ``thinking`` blocks.
    # This filter already selected ``type == "text"`` and so skips them — the
    # reasoning can never be concatenated into Mark's brief. Pinned by a test
    # because it is the one place adaptive thinking could have leaked into user-
    # facing prose, and it is safe by accident rather than by design.
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
    resolved_model = model if isinstance(model, str) else model_name
    _log_usage(raw, model_name=resolved_model)
    return AnthropicTextResult(
        output_markdown=output,
        raw_response=raw,
        model_name=resolved_model,
    )
