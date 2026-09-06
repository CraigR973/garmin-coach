"""Anthropic Message Batches boundary (Batch 220, moved onto the SDK in Batch 257).

This module gives the latency-insensitive longitudinal analyst the four provider
operations it needs: count, submit, poll and fetch results. It shares the same
classified error path as synchronous Messages calls, so billing failures still
reach the existing operator alert.

Batch 257 replaced the hand-rolled HTTP with the ``anthropic`` SDK, in step with
:mod:`src.services.anthropic_text`. The four ``MessageBatchClient`` methods keep
their exact signatures and return plain dicts, so ``longitudinal_analysis`` and
its fake client were untouched: the results loop still receives the same JSONL
rows, now decoded by the SDK rather than by ``json.loads`` per line.

The 60s/120s budgets stay as they were (Decision on Batch 234): submit, poll and
retrieve are control-plane calls, where a long read budget would hide a stuck
poll rather than accommodate a long answer.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic, Timeout

from src.services.anthropic_text import (
    anthropic_error_from_http_status,
    anthropic_error_from_transport,
)

_CONTROL_PLANE_TIMEOUT = 60.0
_RESULTS_TIMEOUT = 120.0


class AnthropicBatchError(RuntimeError):
    """A successful response whose batch payload is unusable."""


class MessageBatchClient(Protocol):
    async def count_tokens(self, params: dict[str, Any]) -> int: ...

    async def submit(self, *, custom_id: str, params: dict[str, Any]) -> dict[str, Any]: ...

    async def retrieve(self, batch_id: str) -> dict[str, Any]: ...

    async def results(self, batch_id: str) -> list[dict[str, Any]]: ...


class AnthropicMessageBatchClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key

    def _client(self, *, timeout: float) -> AsyncAnthropic:
        # ``max_retries=0`` for the same reason ``anthropic_text`` sets it: the
        # app owns its own retry policy, and a poll that silently retries three
        # times is a poll whose cadence no longer means what the caller thinks.
        return AsyncAnthropic(
            api_key=self.api_key,
            timeout=Timeout(timeout, connect=10.0),
            max_retries=0,
        )

    async def count_tokens(self, params: dict[str, Any]) -> int:
        # max_tokens controls generation only and is not accepted by the count
        # endpoint; the remaining fields are the exact request prefix, including
        # the structured-output schema Anthropic injects into the prompt.
        payload = {key: value for key, value in params.items() if key != "max_tokens"}
        async with self._client(timeout=_CONTROL_PLANE_TIMEOUT) as client:
            with _classified():
                count: Any = client.messages.count_tokens
                counted = await count(**payload)
        input_tokens = counted.input_tokens
        if not isinstance(input_tokens, int):  # pragma: no cover - SDK types this as int
            raise AnthropicBatchError("Anthropic token count did not contain input_tokens.")
        return input_tokens

    async def submit(
        self,
        *,
        custom_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._client(timeout=_CONTROL_PLANE_TIMEOUT) as client:
            with _classified():
                create: Any = client.messages.batches.create
                batch = await create(requests=[{"custom_id": custom_id, "params": params}])
        return _as_object(batch, "create")

    async def retrieve(self, batch_id: str) -> dict[str, Any]:
        async with self._client(timeout=_CONTROL_PLANE_TIMEOUT) as client:
            with _classified():
                batch = await client.messages.batches.retrieve(batch_id)
        return _as_object(batch, "retrieve")

    async def results(self, batch_id: str) -> list[dict[str, Any]]:
        """Every JSONL row of a finished batch, decoded.

        The SDK's ``results`` re-``retrieve``s the batch first to find its
        ``results_url``, so this is two provider calls where the hand-rolled
        version made one. ``_collect_one`` only reaches here once polling has
        already seen ``processing_status == "ended"``, and the whole path runs
        monthly, so the extra control-plane call costs nothing worth optimising
        away — and it removes the hand-written per-line ``json.loads`` and its
        two bespoke error messages.
        """
        rows: list[dict[str, Any]] = []
        async with self._client(timeout=_RESULTS_TIMEOUT) as client:
            with _classified():
                stream = await client.messages.batches.results(batch_id)
                async for entry in stream:
                    rows.append(_as_object(entry, "results"))
        if not rows:
            raise AnthropicBatchError("Anthropic batch results were empty.")
        return rows


class _classified:
    """Re-raise an SDK failure as the app's classified :class:`AnthropicApiError`.

    The whole point of this module sharing ``anthropic_text``'s taxonomy is that a
    credit outage during the monthly submission reaches the operator by the same
    route as one during the morning brief. The SDK raises its own hierarchy, so
    that translation has to happen here rather than being inherited from a shared
    ``raise_for_status``.
    """

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> Literal[False]:
        if isinstance(exc, APIStatusError):
            raise anthropic_error_from_http_status(exc) from exc
        if isinstance(exc, APIConnectionError):
            raise anthropic_error_from_transport(exc) from exc
        return False


def _as_object(value: Any, operation: str) -> dict[str, Any]:
    to_dict = getattr(value, "to_dict", None)
    raw = to_dict() if callable(to_dict) else value
    if not isinstance(raw, dict):
        raise AnthropicBatchError(f"Anthropic batch {operation} response was not an object.")
    return raw


__all__ = [
    "AnthropicBatchError",
    "AnthropicMessageBatchClient",
    "MessageBatchClient",
]
