"""Fail-fast global/per-user budgets for paid or CPU-heavy work (Batch 161)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock
from typing import Literal

from fastapi import HTTPException, status

WorkloadKind = Literal["anthropic", "tts"]

_POOL_LIMITS: dict[WorkloadKind, tuple[int, int]] = {
    # A single profile cannot fan out paid calls through concurrent tabs, while
    # background work for the optional second profile still has room to run.
    "anthropic": (4, 1),
    # Piper is a CPU-bound subprocess on the small Railway instance.
    "tts": (1, 1),
}

_lock = Lock()
_active_global: dict[WorkloadKind, int] = defaultdict(int)
_active_by_user: dict[tuple[WorkloadKind, uuid.UUID], int] = defaultdict(int)


class WorkloadBudgetExceeded(HTTPException):
    pass


@asynccontextmanager
async def workload_slot(
    *,
    workload: WorkloadKind,
    user_id: uuid.UUID,
) -> AsyncIterator[None]:
    """Acquire a fail-fast slot; queue depth is deliberately zero.

    SlowAPI bounds repeated authenticated requests over time. This guard bounds
    simultaneous work in-process and refuses excess work before an Anthropic
    request or Piper subprocess starts.
    """

    global_limit, per_user_limit = _POOL_LIMITS[workload]
    key = (workload, user_id)
    with _lock:
        if _active_by_user[key] >= per_user_limit:
            raise WorkloadBudgetExceeded(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="An expensive request is already running for this account. Please retry.",
            )
        if _active_global[workload] >= global_limit:
            raise WorkloadBudgetExceeded(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="This service is temporarily busy. Please retry shortly.",
            )
        _active_by_user[key] += 1
        _active_global[workload] += 1

    try:
        yield
    finally:
        with _lock:
            _active_by_user[key] -= 1
            _active_global[workload] -= 1
            if _active_by_user[key] == 0:
                del _active_by_user[key]
            if _active_global[workload] == 0:
                del _active_global[workload]


def reset_workload_budgets() -> None:
    """Test-only reset; production slots are always released by ``finally``."""

    with _lock:
        _active_global.clear()
        _active_by_user.clear()
