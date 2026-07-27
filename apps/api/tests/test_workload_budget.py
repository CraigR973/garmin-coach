"""Fail-fast concurrency budgets release cleanly after success/failure."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from starlette.requests import Request

from src.rate_limit import per_user_key
from src.services.workload_budget import WorkloadBudgetExceeded, workload_slot


@pytest.mark.asyncio
async def test_tts_budget_returns_per_user_429_global_503_and_recovers() -> None:
    first_user = uuid.uuid4()
    other_user = uuid.uuid4()

    async with workload_slot(workload="tts", user_id=first_user):
        with pytest.raises(WorkloadBudgetExceeded) as same_user:
            async with workload_slot(workload="tts", user_id=first_user):
                pass
        assert same_user.value.status_code == 429

        with pytest.raises(WorkloadBudgetExceeded) as globally_busy:
            async with workload_slot(workload="tts", user_id=other_user):
                pass
        assert globally_busy.value.status_code == 503

    async with workload_slot(workload="tts", user_id=other_user):
        pass


@pytest.mark.asyncio
async def test_anthropic_budget_caps_global_parallelism() -> None:
    users = [uuid.uuid4() for _ in range(5)]
    async with AsyncExitStack() as stack:
        for user_id in users[:4]:
            await stack.enter_async_context(workload_slot(workload="anthropic", user_id=user_id))
        with pytest.raises(WorkloadBudgetExceeded) as exc_info:
            async with workload_slot(workload="anthropic", user_id=users[4]):
                pass
        assert exc_info.value.status_code == 503


def test_rate_limit_key_is_shared_across_a_users_devices_after_auth() -> None:
    user_id = str(uuid.uuid4())
    first = Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer first-device")],
        }
    )
    second = Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer second-device")],
        }
    )
    first.state.current_user_id = user_id
    second.state.current_user_id = user_id

    assert per_user_key(first) == per_user_key(second) == f"user:{user_id}"
