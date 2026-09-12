"""Sentry has to initialise for the job runner too, not only for the API.

Found 2026-09-12 while verifying that `SENTRY_DSN_BACKEND` was live: it was set
on both Railway services and the `weekly-review` cron still reported to nobody,
because `sentry_sdk.init()` lived at module scope in `main.py` and
`python -m src.run_scheduled` never imports it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import settings
from src.observability import init_sentry, scrub_pii


def test_no_dsn_is_a_no_op() -> None:
    """Local runs and tests must not need a DSN, or every one of them pays for it."""
    with patch.object(settings, "sentry_dsn_backend", ""):
        assert init_sentry() is False


def test_a_dsn_initialises_with_pii_off_and_the_scrubber_on() -> None:
    dsn = "https://public@o1.ingest.de.sentry.io/2"
    with (
        patch.object(settings, "sentry_dsn_backend", dsn),
        patch("src.observability.sentry_sdk.get_client", return_value=None),
        patch("src.observability.sentry_sdk.init") as init,
    ):
        assert init_sentry() is True

    kwargs = init.call_args.kwargs
    assert kwargs["dsn"] == dsn
    assert kwargs["send_default_pii"] is False
    assert kwargs["before_send"] is scrub_pii


def test_init_is_idempotent() -> None:
    """Calling init twice tears down the first client and drops its queue.

    Both entrypoints call this, and a future third one might too, so a second
    call has to be free rather than destructive.
    """
    live = MagicMock()
    live.dsn = "https://public@o1.ingest.de.sentry.io/2"
    with (
        patch.object(settings, "sentry_dsn_backend", live.dsn),
        patch("src.observability.sentry_sdk.get_client", return_value=live),
        patch("src.observability.sentry_sdk.init") as init,
    ):
        assert init_sentry() is True

    init.assert_not_called()


def test_the_entrypoint_passes_its_own_integrations() -> None:
    """The API instruments FastAPI; a job runner has no ASGI app to instrument.

    SQLAlchemy is shared, because a job's query failures are as worth seeing as
    a request's.
    """
    marker = MagicMock()
    with (
        patch.object(settings, "sentry_dsn_backend", "https://public@o1.ingest.de.sentry.io/2"),
        patch("src.observability.sentry_sdk.get_client", return_value=None),
        patch("src.observability.sentry_sdk.init") as init,
    ):
        init_sentry(integrations=[marker])

    names = [type(i).__name__ for i in init.call_args.kwargs["integrations"]]
    assert "SqlalchemyIntegration" in names
    assert marker in init.call_args.kwargs["integrations"]


def test_scrub_pii_removes_display_name_and_username() -> None:
    event = {"user": {"id": "abc", "display_name": "Mark", "username": "mark"}}
    scrubbed = scrub_pii(event, {})  # type: ignore[arg-type]
    assert scrubbed is not None
    assert scrubbed["user"] == {"id": "abc"}


def test_the_job_runner_initialises_sentry_without_importing_the_api() -> None:
    """The regression guard, and the whole reason this module exists.

    If `init_sentry()` ever moves back inside `main.py`, the only way the job
    runner could reach it is by importing the API — so this asserts both halves:
    the runner initialises Sentry, and it does so without pulling in `src.main`.
    A subprocess is used because import state is process-wide and the rest of the
    suite has already imported plenty.
    """
    script = (
        "import sys, runpy\n"
        "import src.run_scheduled as rs\n"
        "calls = []\n"
        "rs.init_sentry = lambda *a, **k: calls.append(1) or True\n"
        "sys.argv = ['run_scheduled', 'hive-poll']\n"
        "rs.asyncio.run = lambda coro: coro.close() or __import__('src.services.job_runs',"
        " fromlist=['JobResult']).JobResult.succeeded()\n"
        "rs.main()\n"
        "print('INIT_CALLED', len(calls))\n"
        "print('MAIN_IMPORTED', 'src.main' in sys.modules)\n"
    )
    # Derived, not hardcoded: this runs on CI as well as on a laptop.
    api_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=api_root,
        env={**os.environ, "PYTHONPATH": str(api_root)},
    )
    assert result.returncode == 0, result.stderr
    assert "INIT_CALLED 1" in result.stdout, result.stdout
    assert "MAIN_IMPORTED False" in result.stdout, result.stdout
