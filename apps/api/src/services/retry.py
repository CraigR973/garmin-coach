"""Small retry wrappers shared by the scheduler and the morning pipeline.

Batch 251 (CR236-02): these lived in ``scheduler.py``, which is why
``services/morning_pipeline.py`` could not own the input sync without importing
the scheduler back. They are generic, have no scheduler dependency, and are a
leaf so anything may import them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def retry_sync[T](
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    delay_sec: float = 1.0,
    backoff: float = 1.0,
) -> T:
    """Retry a sync operation, sleeping ``delay_sec`` (× ``backoff`` each retry).

    ``backoff > 1.0`` gives exponential backoff, which keeps the Garmin daily
    sync 429-safe without hammering the API on the rate-limit window.
    """
    delay = delay_sec
    for attempt in range(attempts):
        try:
            return operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay *= backoff
    raise RuntimeError("retry loop exited unexpectedly")


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    delay_sec: float = 1.0,
) -> T:
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay_sec)
    raise RuntimeError("retry loop exited unexpectedly")
