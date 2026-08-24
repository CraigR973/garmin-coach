"""Direct HTTP contract tests for the Batch 220 Message Batch boundary."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.services.anthropic_batch import (
    ANTHROPIC_BATCHES_URL,
    ANTHROPIC_COUNT_TOKENS_URL,
    AnthropicBatchError,
    AnthropicMessageBatchClient,
)
from src.services.anthropic_text import AnthropicApiError


class _Response:
    def __init__(self, payload: Any, *, text: str | None = None) -> None:
        self.payload = payload
        self.text = text if text is not None else ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class _Client:
    requests: list[tuple[str, str, Any]] = []
    post_responses: list[_Response] = []
    get_responses: list[_Response] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> _Response:
        _Client.requests.append(("POST", url, json))
        return _Client.post_responses.pop(0)

    async def get(self, url: str, *, headers: dict[str, str]) -> _Response:
        _Client.requests.append(("GET", url, None))
        return _Client.get_responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    _Client.requests = []
    _Client.post_responses = []
    _Client.get_responses = []


@pytest.mark.asyncio
async def test_count_and_submit_keep_the_structured_request_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_batch.httpx.AsyncClient", _Client)
    _Client.post_responses = [
        _Response({"input_tokens": 12345}),
        _Response({"id": "msgbatch_123", "processing_status": "in_progress"}),
    ]
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
    count_payload = _Client.requests[0][2]
    assert "max_tokens" not in count_payload
    assert count_payload["output_config"] == params["output_config"]
    assert _Client.requests[0][1] == ANTHROPIC_COUNT_TOKENS_URL
    assert _Client.requests[1] == (
        "POST",
        ANTHROPIC_BATCHES_URL,
        {"requests": [{"custom_id": "longitudinal-test", "params": params}]},
    )


@pytest.mark.asyncio
async def test_retrieve_and_jsonl_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_batch.httpx.AsyncClient", _Client)
    _Client.get_responses = [
        _Response({"id": "msgbatch_123", "processing_status": "ended"}),
        _Response(
            {},
            text=(
                '{"custom_id":"first","result":{"type":"succeeded"}}\n'
                '{"custom_id":"second","result":{"type":"expired"}}\n'
            ),
        ),
    ]
    client = AnthropicMessageBatchClient(api_key="test-key")

    batch = await client.retrieve("msgbatch_123")
    rows = await client.results("msgbatch_123")

    assert batch["processing_status"] == "ended"
    assert [row["custom_id"] for row in rows] == ["first", "second"]
    assert _Client.requests[1][1].endswith("/msgbatch_123/results")


@pytest.mark.asyncio
async def test_results_reject_malformed_jsonl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.anthropic_batch.httpx.AsyncClient", _Client)
    _Client.get_responses = [_Response({}, text="not-json\n")]

    with pytest.raises(AnthropicBatchError, match="line 1"):
        await AnthropicMessageBatchClient(api_key="test-key").results("msgbatch_123")


class _BillingClient(_Client):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "type": "error",
                "error": {"type": "billing_error", "message": "Account unavailable."},
            },
            request=httpx.Request("POST", url),
        )


@pytest.mark.asyncio
async def test_batch_http_billing_error_uses_shared_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.anthropic_batch.httpx.AsyncClient", _BillingClient)

    with pytest.raises(AnthropicApiError) as excinfo:
        await AnthropicMessageBatchClient(api_key="test-key").count_tokens(
            {"model": "claude-test", "messages": [{"role": "user", "content": "x"}]}
        )

    assert excinfo.value.reason == "billing"
