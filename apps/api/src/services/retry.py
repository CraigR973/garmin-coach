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
    """Retry a blocking call in a worker thread, sleeping ``delay_sec`` (× ``backoff`` each retry).

    ``backoff > 1.0`` gives exponential backoff, which keeps the Garmin daily
    sync 429-safe without hammering the API on the rate-limit window.

    Batch 312: each attempt runs in a worker thread (``asyncio.to_thread``). The
    operations are the Garmin and Hive clients, synchronous over ``requests``
    with their own timeouts and retries, and run directly each one held the
    event loop for the whole call: no request and no other job ran, for minutes
    on a slow Garmin day (27 Sep). The waits between attempts stay on the loop,
    where they always yielded. Overlapping calls to one service are kept apart by
    that client's own lock, not here.
    """
    delay = delay_sec
    for attempt in range(attempts):
        try:
            return await asyncio.to_thread(operation)
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
