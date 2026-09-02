"""Make an ORM instance usable again after a rollback (Batch 242 / CR236-01).

``Session.rollback()`` restores the identity-map snapshot, and for a top-level
transaction that expires **every** loaded instance — untouched ones included,
and the primary key is not exempt. Under an ``AsyncSession`` the next plain
attribute read is implicit IO outside ``greenlet_spawn``, so it raises
``MissingGreenlet``.

That matters because of *where* it happens. When it happens inside an ``except``
clause, the new exception propagates **past the handler's sibling clauses** —
Python does not offer a raising handler to its siblings — so it escapes the loop
the handler was protecting and lands in whatever outermost handler exists. In
this app that turned one profile's recoverable step into a whole job reported as
an outage, with ``record_failure`` and the operator alert on the lines below
never reached at all.

Two rules follow, and they are different:

* **Log fields come from scalars hoisted into locals before the ``try``.** That
  needs no IO and cannot fail. Prefer it always.
* **Instances handed to another call after the rollback must be reloaded**, and
  that is what this module is for. Awaited, so it cannot raise the way an
  implicit refresh does.

This is a leaf on purpose. Both ``scheduler.py`` and ``routers/daily_loop.py``
need it, and a router importing a private helper out of the scheduler is the
coupling CR236-02/CR236-09 already flag.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import inspect
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def restore_after_rollback(session: AsyncSession, *instances: Any) -> None:
    """Re-load any of ``instances`` that a rollback expired.

    A no-op when nothing is expired — the check is pure state inspection, so
    this costs nothing on the happy path and can be called defensively at the
    top of a loop iteration as well as inside a handler.
    """

    for instance in instances:
        if instance is None:
            continue
        try:
            state = inspect(instance)
        except NoInspectionAvailable:
            # A plain dataclass or DTO passed alongside the ORM ones. A rollback
            # cannot expire it, so there is nothing to do — and raising here
            # would defeat the point of the module.
            continue
        if not state.expired:
            continue
        try:
            await session.refresh(instance)
        except Exception:
            # The row may not have survived the transaction just discarded.
            # Whatever reads it next will fail on its own terms; it must not
            # fail *here*, inside the handler whose whole job is to record the
            # failure. Never raise from a recovery path.
            log.warning(
                "could not reload instance after rollback",
                entity=type(instance).__name__,
            )
