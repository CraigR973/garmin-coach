"""Shared Anthropic text-generation boundary for Garmin Coach analyses.

**Batch 257 moved this onto the official ``anthropic`` SDK**, superseding the
SDK clause of Decision #47. What sits *around* the call is unchanged and is the
reason the migration was worth doing carefully rather than quickly: the
classified error taxonomy (Batch 141), the transport slugs (Batch 248), the
shared-deadline retry (Batch 248, bounded by Batch 232's lease) and the usage
logging (Batch 233) are all still owned here. The SDK replaces exactly one
thing — hand-rolled HTTP against ``POST /v1/messages`` — and every public name
this module exported before the migration still means the same thing, so all
nine ``generate_anthropic_text`` callers were untouched by it.

Two deliberate settings keep the repo's contracts rather than the SDK's:

* ``max_retries=0`` on the client. The SDK retries 408/409/429/5xx twice by
  default, and the app already has a retry whose budget is *the whole call*
  (:data:`_MAX_ANTHROPIC_ATTEMPTS`) because Batch 232 made the generation lease
  expire before Batch 144's stale-after guard. Two retry layers would multiply
  into 9 attempts against a budget sized for 3, which is precisely the class of
  defect Batch 232 exists to remove. One retry layer, and it is this one.
* Per-phase timeouts built here, not the SDK's flat 10-minute default, so
  ``connect``/``write``/``pool`` still fail fast while only ``read`` scales with
  generation length (Batch 234).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

import structlog
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    Timeout,
)
from anthropic.types import Message
from pydantic import BaseModel

from src.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Batch 257 deleted ``ANTHROPIC_MESSAGES_URL`` and ``ANTHROPIC_VERSION`` with the
# migration. The SDK owns both — it sends ``anthropic-version: 2023-06-01``, the
# same value this module pinned by hand — and a hand-maintained copy of a header
# nothing sends is the kind of constant a later reader trusts and should not.


def _timeout(*, read: float | None = None) -> Timeout:
    """Per-phase timeouts for a non-streamed Messages call.

    The single ``timeout=60.0`` this replaces applied 60s to *every* phase, so the
    read budget was really "60s for Claude to finish the whole answer" — which the
    morning brief outgrew on 2026-08-30 (measured 75.1s). Only ``read`` needs to
    scale with generation length; connect/write/pool stay short so a genuinely
    unreachable API still fails fast instead of hanging for the full read budget.

    ``anthropic.Timeout`` *is* ``httpx2.Timeout`` (the SDK is built on ``httpx2``,
    not the ``httpx`` the rest of the app uses), so this is the same per-phase
    object it always was, reached through the SDK's own re-export.
    """
    return Timeout(
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
    #: How many tool calls were executed to produce this answer, and how many
    #: paid API calls it took (Batch 257.6). Both default to the single-call
    #: shape, so every pre-257 caller reads exactly what it always did.
    tool_uses: int = 0
    api_calls: int = 1


@dataclass(frozen=True, slots=True)
class ToolResult:
    """One executed tool call, on its way back to the model."""

    tool_use_id: str
    content: str
    is_error: bool = False

    def to_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
        }
        if self.is_error:
            # A failed tool is *reported*, never dropped. Dropping it leaves a
            # ``tool_use`` block with no matching result, which the provider
            # rejects on the next turn — turning a failed lookup into a failed
            # answer.
            block["is_error"] = True
        return block


class ToolExecutor(Protocol):
    """Runs one tool call. Supplied by the caller; unknown to this module."""

    async def __call__(self, *, tool_use_id: str, name: str, payload: Any) -> ToolResult: ...


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


def text_from_content(content: Any) -> str:
    """The prose out of a response's content blocks, and nothing else.

    Batch 233.3: with thinking on, ``content`` also carries ``thinking`` blocks,
    and with Batch 257's tools it also carries ``tool_use`` blocks. This filter
    has always selected ``type == "text"`` and so skips both — the reasoning can
    never be concatenated into Mark's brief, and neither can a tool call. Pinned
    by a test, because it is the one place adaptive thinking could have leaked
    into user-facing prose and it is safe by design rather than by accident.

    Takes the serialized (``to_dict``) form rather than SDK block objects so the
    single-call path and the tool loop share one definition of "the answer".
    """
    text_parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
    return "\n\n".join(text_parts).strip()


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


def anthropic_error_from_http_status(exc: APIStatusError) -> AnthropicApiError:
    """Parse + log an Anthropic non-2xx into a classified error (Batch 141).

    ``httpx``'s ``raise_for_status`` discarded the response body, so the *reason*
    (e.g. "Your credit balance is too low…") never reached the logs — recovering it
    on 2026-07-21 needed a manual out-of-band API call. The SDK keeps the parsed
    body on the exception (``exc.body``), so Batch 257 reads it from there instead
    of re-parsing the response; the provider's ``error.type`` / ``error.message``
    still reach the log, and the classification is byte-for-byte the same function
    it always was. The API key is never logged: it travels only in the request
    ``x-api-key`` header and is never echoed in a response body.

    The SDK raises a *subclass* per status (``RateLimitError``, ``BadRequestError``,
    …), but this deliberately keeps classifying from the status code and body
    rather than the exception class: the credit-exhaustion outage arrives as a
    ``BadRequestError`` and is only distinguishable by its message, so catching the
    subclass would re-introduce exactly the blind spot Batch 141 closed.
    """
    status_code = exc.status_code
    error_type: str | None = None
    error_message: str | None = None
    body: object | None = exc.body
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


def anthropic_error_from_transport(exc: APIConnectionError) -> AnthropicApiError:
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
    landed". Batch 257: the SDK models that split as `APITimeoutError` inheriting
    from `APIConnectionError`, so the same two slugs come out of an `isinstance`
    on the SDK's own types rather than on `httpx`'s.
    """
    reason = "timeout" if isinstance(exc, APITimeoutError) else "transport"
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


def anthropic_client(*, api_key: str, read: float | None = None) -> AsyncAnthropic:
    """The SDK client every Anthropic call in this app goes through (Batch 257).

    ``max_retries=0`` is the load-bearing argument. The SDK retries 408/409/429
    and 5xx twice of its own accord, and :func:`_create_with_retry` below already
    retries the reasons a retry can fix against a budget that is *the whole call*.
    Leaving the SDK's default on would nest one inside the other — up to nine
    attempts against a budget Batch 232 sized for three, with the extra ones
    invisible to the ``anthropic_call_retrying`` log line and to the deadline that
    keeps a generation inside its lease.
    """
    return AsyncAnthropic(
        api_key=api_key,
        timeout=_timeout(read=read),
        max_retries=0,
    )


async def _create_with_retry(
    *,
    api_key: str,
    payload: dict[str, Any],
    model_name: str,
) -> Message:
    """Call Anthropic, re-attempting only the reasons a retry can actually fix.

    Batch 248 (AI238-04). Before this there was no retry anywhere in the app:
    ``_RETRYABLE_ANTHROPIC_REASONS`` only chose which sentence Mark saw, so a
    single 529 at 06:40 cost the whole morning until the 11:00 backstop.

    One change to one function covers all nine ``generate_anthropic_text``
    callers. See ``_MAX_ANTHROPIC_ATTEMPTS`` for why the budget is the call
    rather than the attempt.

    Batch 257 swapped the transport underneath for the SDK and changed nothing
    else here. ``payload`` stays a dict rather than becoming explicit keyword
    arguments *deliberately*: "a field is absent from the request unless a caller
    passes it" is the property Batch 233 built the rollback path on and pinned
    with a test, and a dict is the shape that keeps it directly inspectable.
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
            async with anthropic_client(api_key=api_key, read=remaining) as client:
                # ``messages.create`` is overloaded on ``stream``, so a ``**dict``
                # expansion cannot be checked against it. The untyped local is the
                # cost of keeping the payload a dict (see the docstring); the
                # return is annotated, so everything downstream stays typed.
                create: Any = client.messages.create
                message: Message = await create(**payload)
                return message
        except APIStatusError as exc:
            error = anthropic_error_from_http_status(exc)
        except APIConnectionError as exc:
            error = anthropic_error_from_transport(exc)
        except AnthropicApiError as exc:  # pragma: no cover - defensive
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


def build_messages_payload(
    *,
    model_name: str,
    max_tokens: int,
    system_prompt: AnthropicSystemPrompt,
    messages: list[dict[str, Any]],
    thinking: AnthropicThinking | None = None,
    effort: str | None = None,
    output_schema: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The one place a Messages request is assembled (Batch 257).

    Both callers in this module go through it, so the properties earlier batches
    fought for hold on the tool path for free rather than by being remembered:

    * **A field is absent unless passed** (Batch 233). ``thinking`` and
      ``output_config`` are the only wire-format difference between this app on
      Sonnet 5 and this app as it was on Sonnet 4.6, so the rollback stays a
      settings change rather than a code change.
    * **``effort`` and ``format`` are two keys of one ``output_config``** (Batch
      253, AI238-10). Assigning it wholesale for either silently drops the other,
      which for a structured caller turns a schema-constrained response back into
      prose with nothing failing until the parse does. ``test_batch253_hygiene``
      greps this module's source for that pattern, and it caught the tool loop
      re-introducing it.
    """
    payload: dict[str, Any] = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if thinking is not None:
        payload["thinking"] = thinking
    output_config: dict[str, Any] = {}
    if effort is not None:
        output_config["effort"] = effort
    if output_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": output_schema}
    if output_config:
        payload["output_config"] = output_config
    return payload


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
    messages: list[dict[str, Any]] = [
        *(prior_messages or []),
        {"role": "user", "content": user_prompt},
    ]
    payload = build_messages_payload(
        model_name=model_name,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        messages=messages,
        thinking=thinking,
        effort=effort,
        output_schema=output_schema,
    )
    message = await _create_with_retry(api_key=api_key, payload=payload, model_name=model_name)
    raw = message.to_dict()

    if message.stop_reason == "max_tokens":
        raise error_cls("Claude response hit max_tokens before completing.")

    output = text_from_content(raw.get("content"))
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


# ---------------------------------------------------------------------------
# Batch 257 — the tool loop
# ---------------------------------------------------------------------------

#: API calls one answer may take, tool rounds included. Three rounds is two
#: chances to fetch and then answer; the cap exists because chat runs the model
#: call **in-request** (``ask_coach``), so every extra round trip is time Mark
#: spends watching a spinner.
MAX_TOOL_ROUNDS = 3

#: Tool calls one answer may execute, across all rounds. Parallel calls in one
#: round count individually — a round that asks for three lookups spends three.
MAX_TOOL_USES = 4


async def generate_anthropic_text_with_tools(
    *,
    api_key: str,
    model_name: str,
    max_tokens: int,
    system_prompt: AnthropicSystemPrompt,
    user_prompt: str,
    error_cls: type[Exception],
    tools: list[dict[str, Any]],
    execute_tool: ToolExecutor,
    prior_messages: list[dict[str, Any]] | None = None,
    thinking: AnthropicThinking | None = None,
    effort: str | None = None,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    max_tool_uses: int = MAX_TOOL_USES,
) -> AnthropicTextResult:
    """``generate_anthropic_text``, plus the loop that lets the model fetch.

    A manual loop rather than the SDK's ``tool_runner``, for two reasons that are
    about this app rather than about taste. The runner is beta and drives its own
    loop, so the shared-deadline retry every call here goes through — the one
    Batch 232 sized against the generation lease — would have to be rebuilt
    around it. And the runner would own the request shape, which is where
    ``thinking``/``effort``/``cache_control`` are decided. Everything the runner
    is *recommended* for (approval gates, interception) this path does not need,
    because the tools are read-only by construction.

    Three rules the provider cares about, all load-bearing:

    * **Every** ``tool_result`` goes back in a **single** user message. Splitting
      them across messages trains the model out of asking for parallel calls,
      which is the one thing that keeps a two-lookup answer to one round trip.
    * The assistant turn is appended as the model's own ``content``, unedited —
      thinking blocks included. Re-serialising only the parts that look useful is
      how a harness silently invalidates its own history.
    * A failed tool returns ``is_error``; it is never dropped.

    The last round is sent with ``tool_choice: {"type": "none"}`` so the answer
    is always prose. That is cheap here on purpose: a ``tool_choice`` change
    invalidates only the *messages* cache, and this path's breakpoints are both
    in ``system``.
    """
    messages: list[dict[str, Any]] = [
        *(prior_messages or []),
        {"role": "user", "content": user_prompt},
    ]
    tool_uses = 0
    api_calls = 0
    raw: dict[str, Any] = {}

    for round_index in range(1, max_tool_rounds + 1):
        exhausted = tool_uses >= max_tool_uses or round_index == max_tool_rounds
        payload = build_messages_payload(
            model_name=model_name,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            messages=messages,
            thinking=thinking,
            effort=effort,
            tools=tools,
            tool_choice={"type": "none"} if exhausted else None,
        )

        message = await _create_with_retry(api_key=api_key, payload=payload, model_name=model_name)
        api_calls += 1
        raw = message.to_dict()
        _log_usage(raw, model_name=_resolved_model(raw, model_name))

        if message.stop_reason == "max_tokens":
            raise error_cls("Claude response hit max_tokens before completing.")

        calls = _tool_use_blocks(raw)
        if not calls:
            break

        messages.append({"role": "assistant", "content": raw.get("content", [])})
        results = [
            (
                await execute_tool(
                    tool_use_id=str(call.get("id")),
                    name=str(call.get("name")),
                    payload=call.get("input"),
                )
            ).to_block()
            for call in calls
        ]
        tool_uses += len(calls)
        log.info(
            "anthropic_tool_round",
            model_name=model_name,
            round=round_index,
            tools=[str(call.get("name")) for call in calls],
            errors=sum(1 for block in results if block.get("is_error")),
            tool_uses=tool_uses,
        )
        messages.append({"role": "user", "content": results})

    output = text_from_content(raw.get("content"))
    if not output:
        raise error_cls("Claude response did not contain text output.")
    resolved_model = _resolved_model(raw, model_name)
    return AnthropicTextResult(
        output_markdown=output,
        raw_response=raw,
        model_name=resolved_model,
        tool_uses=tool_uses,
        api_calls=api_calls,
    )


def _resolved_model(raw: dict[str, Any], fallback: str) -> str:
    model = raw.get("model")
    return model if isinstance(model, str) else fallback


def _tool_use_blocks(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``tool_use`` blocks of one response, in the order the model asked.

    ``input`` arrives already parsed by the SDK; it is never string-matched. The
    4.6+ models vary their JSON escaping inside tool inputs, so matching on the
    serialized form is a bug that only shows up on some inputs.
    """
    content = raw.get("content")
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]
