"""Sentry initialisation, reachable from every entrypoint rather than one.

This app has **two** ways in. `uvicorn src.main:app` serves the API, and
`python -m src.run_scheduled <job>` runs a single job to completion for an
external scheduler — the Railway `weekly-review` cron, a manual `railway run`,
anything with its own clock.

`sentry_sdk.init()` used to live at module scope in `main.py`, which meant only
the first of those ever initialised it. Setting `SENTRY_DSN_BACKEND` on the
`weekly-review` service therefore read the variable and did nothing: that
process never imports `main.py`. Verified in the deployed image on 2026-09-12 —
`importlib` of `src.run_scheduled` leaves `src.main` unimported and
`sentry_sdk.get_client().dsn` empty.

**The sharpest consequence was the watchdog.** Batch 242.5's `ledger-freshness`
is deliberately *external-runner only*, because a check that rides the scheduler
it watches goes down for exactly the reason it needs to fire — and its entire
delivery mechanism is `log.error` captured by Sentry. So the one job built to
notice a dead scheduler was silent by construction.

Both entrypoints now call `init_sentry()`. It is idempotent and a no-op without
a DSN, so importing it costs nothing in tests or in a local run.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.types import Event, Hint

from src.config import Environment, settings


def scrub_pii(event: Event, hint: Hint) -> Event | None:
    """Remove display names from Sentry events so player names never appear in error reports."""

    user: Any = event.get("user")
    if isinstance(user, dict):
        user.pop("display_name", None)
        user.pop("username", None)
    return event


def init_sentry(*, integrations: list[Any] | None = None) -> bool:
    """Initialise Sentry if a DSN is configured. Returns whether it is now active.

    ``integrations`` carries the entrypoint's own additions — the API passes the
    FastAPI integration, a job runner has no ASGI app to instrument. The
    SQLAlchemy integration is shared, because both entrypoints talk to the
    database and a job's query failures are as worth seeing as a request's.
    """

    if not settings.sentry_dsn_backend:
        return False

    client = sentry_sdk.get_client()
    if client is not None and client.dsn:
        # Already initialised — calling init twice would tear down the first
        # client and drop anything still queued on it.
        return True

    sentry_sdk.init(
        dsn=settings.sentry_dsn_backend,
        environment=settings.environment,
        integrations=[SqlalchemyIntegration(), *(integrations or [])],
        send_default_pii=False,
        before_send=scrub_pii,
        traces_sample_rate=0.0 if settings.environment != Environment.production else 0.05,
    )
    return True
