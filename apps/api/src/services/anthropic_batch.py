"""Thin direct-HTTP boundary for Anthropic Message Batches (Batch 220).

The rest of the app deliberately does not depend on the Anthropic SDK.  This
module keeps that decision while giving the latency-insensitive longitudinal
analyst the four provider operations it needs: count, submit, poll and fetch
JSONL results.  It shares the same classified error path as synchronous
Messages calls, so billing failures reach the existing operator alert.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from src.services.anthropic_text import (
    ANTHROPIC_VERSION,
    anthropic_error_from_http_status,
)

ANTHROPIC_BATCHES_URL = "https://api.anthropic.com/v1/messages/batches"
ANTHROPIC_COUNT_TOKENS_URL = "https://api.anthropic.com/v1/messages/count_tokens"


class AnthropicBatchError(RuntimeError):
    """A successful HTTP response whose batch payload is unusable."""


class MessageBatchClient(Protocol):
    async def count_tokens(self, params: dict[str, Any]) -> int: ...

    async def submit(self, *, custom_id: str, params: dict[str, Any]) -> dict[str, Any]: ...

    async def retrieve(self, batch_id: str) -> dict[str, Any]: ...

    async def results(self, batch_id: str) -> list[dict[str, Any]]: ...


class AnthropicMessageBatchClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    async def count_tokens(self, params: dict[str, Any]) -> int:
        # max_tokens controls generation only and is not accepted by the count
        # endpoint; the remaining fields are the exact request prefix, including
        # the structured-output schema Anthropic injects into the prompt.
        payload = {key: value for key, value in params.items() if key != "max_tokens"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                ANTHROPIC_COUNT_TOKENS_URL,
                headers=self._headers,
                json=payload,
            )
            self._raise_for_status(response)
        raw = response.json()
        input_tokens = raw.get("input_tokens") if isinstance(raw, dict) else None
        if not isinstance(input_tokens, int):
            raise AnthropicBatchError("Anthropic token count did not contain input_tokens.")
        return input_tokens

    async def submit(
        self,
        *,
        custom_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                ANTHROPIC_BATCHES_URL,
                headers=self._headers,
                json={"requests": [{"custom_id": custom_id, "params": params}]},
            )
            self._raise_for_status(response)
        return self._object_response(response, "create")

    async def retrieve(self, batch_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{ANTHROPIC_BATCHES_URL}/{batch_id}",
                headers=self._headers,
            )
            self._raise_for_status(response)
        return self._object_response(response, "retrieve")

    async def results(self, batch_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(
                f"{ANTHROPIC_BATCHES_URL}/{batch_id}/results",
                headers=self._headers,
            )
            self._raise_for_status(response)
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(response.text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AnthropicBatchError(
                    f"Anthropic batch result line {line_number} was not JSON."
                ) from exc
            if not isinstance(item, dict):
                raise AnthropicBatchError(
                    f"Anthropic batch result line {line_number} was not an object."
                )
            rows.append(item)
        if not rows:
            raise AnthropicBatchError("Anthropic batch results were empty.")
        return rows

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise anthropic_error_from_http_status(exc) from exc

    @staticmethod
    def _object_response(response: httpx.Response, operation: str) -> dict[str, Any]:
        raw = response.json()
        if not isinstance(raw, dict):
            raise AnthropicBatchError(f"Anthropic batch {operation} response was not an object.")
        return raw
