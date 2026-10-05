"""One call at a time to an external service, across the whole process (Batch 312).

Until Batch 312 every Garmin and Hive call ran on the event loop, which kept
them apart by accident: while one ran, nothing else could start another. Run in
worker threads they can overlap, so each client holds its service's lock for the
whole of a call instead. The lock is re-entrant because a client's fetch calls
its own ``login``.

This is a leaf on purpose: the Garmin and Hive clients both use it.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable


def one_at_a_time[**P, R](lock: threading.RLock) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Hold ``lock`` for the whole of every call to the decorated function."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(function)
        def locked(*args: P.args, **kwargs: P.kwargs) -> R:
            with lock:
                return function(*args, **kwargs)

        return locked

    return decorate
