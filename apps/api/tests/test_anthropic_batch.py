"""Contract tests for the Message Batch boundary (Batch 220, on the SDK since 257).

The subject is unchanged: the four provider operations the longitudinal analyst
needs, and the guarantee that a failure on this path classifies through the same
taxonomy as one on the synchronous path. What changed is that the fake is now a
fake *SDK client* rather than a fake transport — and one test's subject moved
into the SDK entirely, which is recorded below rather than silently dropped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from anthropic import APIStatusError

from src.services.anthropic_batch import (
    AnthropicBatchError,
    AnthropicMessageBatchClient,
)
from src.services.anthropic_text import AnthropicApiError


class _Recorded:
    """A recorded call: the operation name and the arguments it was given."""

    def __init__(self, operation: str, payload: Any) -> None:
        self.operation = operation
        self.payload = payload


class _Obj:
    """Stands in for an SDK model: attribute access plus ``to_dict``."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        for key, value in payload.items():
            setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._payload)


class _Batches:
    async def create(self, *, requests: Any) -> _Obj:
        _Client.calls.append(_Recorded("batches.create", {"requests": requests}))
        return _Obj(_Client.next_batch)

    async def retrieve(self, batch_id: str) -> _Obj:
        _Client.calls.append(_Recorded("batches.retrieve", batch_id))
        return _Obj(_Client.next_batch)

    async def results(self, batch_id: str) -> AsyncIterator[_Obj]:
        _Client.calls.append(_Recorded("batches.results", batch_id))

        async def _rows() -> AsyncIterator[_Obj]:
            for row in _Client.next_rows:
                yield _Obj(row)

        return _rows()


class _Messages:
    def __init__(self) -> None:
        self.batches = _Batches()

    async def count_tokens(self, **kwargs: Any) -> _Obj:
        _Client.calls.append(_Recorded("count_tokens", kwargs))
        return _Obj({"input_tokens": _Client.next_token_count})


class _Client:
    calls: list[_Recorded] = []
    next_batch: dict[str, Any] = {}
    next_rows: list[dict[str, Any]] = []
    next_token_count: int = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        _Client.last_init_kwargs = kwargs
        self.messages = _Messages()

    last_init_kwargs: dict[str, Any] = {}

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    _Client.calls = []
    _Client.next_batch = {}
    _Client.next_rows = []
    _Client.next_token_count = 0
    _Client.last_init_kwargs = {}


@pytest.mark.asyncio
async def test_count_and_submit_keep_the_structured_request_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_batch.AsyncAnthropic", _Client)
    _Client.next_token_count = 12345
    _Client.next_batch = {"id": "msgbatch_123", "processing_status": "in_progress"}
    params = {
        "model": "claude-test",
        "max_tokens": 4096,
        "system": "system",
        "messages": [{"role": "user", "content": "evidence"}],
        "output_config": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
    }
    client = AnthropicMessageBatchClient(api_key="test-key")

    count = await client.count_tokens(params)
    batch = await client.submit(custom_id="longitudinal-test", params=params)

    assert count == 12345
    assert batch["id"] == "msgbatch_123"
    count_call = _Client.calls[0]
    assert count_call.operation == "count_tokens"
    # ``max_tokens`` controls generation only and the count endpoint rejects it;
    # everything else is the exact request prefix, schema included.
    assert "max_tokens" not in count_call.payload
    assert count_call.payload["output_config"] == params["output_config"]
    submit_call = _Client.calls[1]
    assert submit_call.operation == "batches.create"
    assert submit_call.payload == {
        "requests": [{"custom_id": "longitudinal-test", "params": params}]
    }


@pytest.mark.asyncio
async def test_retrieve_and_results_return_plain_dicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``longitudinal_analysis`` reads dicts, so the SDK models are flattened here.

    Its fake provider returns dicts too, so this is the one place the real client
    and the test double have to agree on a shape.
    """
    monkeypatch.setattr("src.services.anthropic_batch.AsyncAnthropic", _Client)
    _Client.next_batch = {"id": "msgbatch_123", "processing_status": "ended"}
    _Client.next_rows = [
        {"custom_id": "first", "result": {"type": "succeeded"}},
        {"custom_id": "second", "result": {"type": "expired"}},
    ]
    client = AnthropicMessageBatchClient(api_key="test-key")

    batch = await client.retrieve("msgbatch_123")
    rows = await client.results("msgbatch_123")

    assert batch["processing_status"] == "ended"
    assert [row["custom_id"] for row in rows] == ["first", "second"]
    assert _Client.calls[-1].operation == "batches.results"
    assert _Client.calls[-1].payload == "msgbatch_123"


@pytest.mark.asyncio
async def test_empty_results_are_an_error_rather_than_a_silent_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replaces ``test_results_reject_malformed_jsonl``, whose subject moved.

    That test pinned this module's hand-written per-line ``json.loads`` and its
    two bespoke "line N was not JSON" messages. Batch 257 deleted that parsing —
    the SDK decodes the JSONL stream — so asserting on it here would be asserting
    on the SDK. What this module still owns is the *emptiness* check: a finished
    batch that yields no rows must raise rather than report zero findings, which
    would read as "the analyst found nothing".
    """
    monkeypatch.setattr("src.services.anthropic_batch.AsyncAnthropic", _Client)
    _Client.next_batch = {"id": "msgbatch_123", "processing_status": "ended"}
    _Client.next_rows = []

    with pytest.raises(AnthropicBatchError, match="empty"):
        await AnthropicMessageBatchClient(api_key="test-key").results("msgbatch_123")


class _BillingMessages(_Messages):
    async def count_tokens(self, **kwargs: Any) -> _Obj:
        body = {
            "type": "error",
            "error": {"type": "billing_error", "message": "Account unavailable."},
        }
        raise APIStatusError(
            "boom",
            response=httpx2.Response(
                400,
                json=body,
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
            ),
            body=body,
        )


class _BillingClient(_Client):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.messages = _BillingMessages()


@pytest.mark.asyncio
async def test_batch_billing_error_uses_shared_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A credit outage during the monthly submission must reach the same alert.

    The SDK raises its own hierarchy, so this module translates back into
    ``AnthropicApiError`` rather than inheriting the translation from a shared
    ``raise_for_status``. If that translation is lost, the failure escapes
    unclassified and the operator hears nothing — the Batch 141 hole, reopened.
    """
    monkeypatch.setattr("src.services.anthropic_batch.AsyncAnthropic", _BillingClient)

    with pytest.raises(AnthropicApiError) as excinfo:
        await AnthropicMessageBatchClient(api_key="test-key").count_tokens(
            {"model": "claude-test", "messages": [{"role": "user", "content": "x"}]}
        )

    assert excinfo.value.reason == "billing"


@pytest.mark.asyncio
async def test_the_batch_client_does_not_stack_the_sdks_own_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``max_retries=0``: the app owns retry policy, on both Anthropic paths.

    Left at the SDK default, a poll would silently re-attempt three times, and a
    poll whose cadence no longer means what the caller thinks is a poll that can
    outlive the window it was scheduled in.
    """
    monkeypatch.setattr("src.services.anthropic_batch.AsyncAnthropic", _Client)
    _Client.next_batch = {"id": "msgbatch_123", "processing_status": "ended"}

    await AnthropicMessageBatchClient(api_key="test-key").retrieve("msgbatch_123")

    assert _Client.last_init_kwargs["max_retries"] == 0
