"""Batch 291 — admin alerts reach Craig through Sentry.

Production has one profile, Mark's, so the operator push had no recipient, and the
monthly longitudinal analysis, gated on an alert route, skipped every day after its one
crash on 25 Aug. Craig's decision (25 Sep 2026): Sentry is the operator route.

* With no operator profile configured, a configured Sentry DSN is a ready alert route;
  an operator profile that is the subject is still refused.
* Every admin alert is one error-level event tagged ``admin_alert=<kind>``, so a single
  Sentry rule catches them all, and none of them reaches Mark's phone.
* A failed note reading stays a warning (Craig, 3 Oct 2026).
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

import src.scheduler as scheduler
from src.config import settings
from src.services import admin_alerts, cross_surface_agreement, notes_reader, nudge_alerts
from src.services import morning_analysis as morning_analysis_module
from src.services.admin_alerts import (
    ADMIN_ALERT_TAG,
    KIND_BILLING,
    KIND_CROSS_SURFACE,
    KIND_FIGURE_CONTEST,
    KIND_GENERATION_FAILURE,
    KIND_LONGITUDINAL,
    KIND_VERDICT_LESS_CAUTIOUS,
    KINDS,
    admin_alert,
    generation_failure_kind,
)
from src.services.cross_surface_agreement import alert_disagreements, evaluate_agreement
from src.services.job_runs import JobStatus
from src.services.longitudinal_analysis import (
    LongitudinalAnalysisService,
    billing_alert_readiness,
)
from src.services.morning_analysis import _log_verdict_engines
from src.services.nudge_alerts import NudgeAlertService
from src.services.verdict_grading import ENGINE_GRADED

SENTRY_DSN = "https://public@o1.ingest.sentry.io/1"


@pytest.fixture
def tags(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """The tags each admin alert sets on its Sentry scope."""
    seen: list[tuple[str, str]] = []

    class _Scope:
        def set_tag(self, key: str, value: str) -> None:
            seen.append((key, value))

    @contextmanager
    def new_scope() -> Iterator[_Scope]:
        yield _Scope()

    monkeypatch.setattr(admin_alerts.sentry_sdk, "new_scope", new_scope)
    return seen


# -- the route ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sentry_is_the_route_when_no_operator_profile_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "admin_alert_user_id", "")
    monkeypatch.setattr(settings, "sentry_dsn_backend", SENTRY_DSN)
    readiness = await billing_alert_readiness(Mock(), subject_profile_id=uuid.uuid4())
    assert (readiness.ready, readiness.route) == (True, "sentry")


@pytest.mark.asyncio
async def test_with_neither_sentry_nor_an_operator_nothing_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "admin_alert_user_id", "")
    monkeypatch.setattr(settings, "sentry_dsn_backend", "")
    readiness = await billing_alert_readiness(Mock())
    assert (readiness.ready, readiness.reason) == (False, "admin_alert_user_id_unset")


@pytest.mark.asyncio
async def test_an_operator_profile_that_is_the_subject_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark = uuid.uuid4()
    monkeypatch.setattr(settings, "admin_alert_user_id", str(mark))
    monkeypatch.setattr(settings, "sentry_dsn_backend", SENTRY_DSN)
    readiness = await billing_alert_readiness(Mock(), subject_profile_id=mark)
    assert (readiness.ready, readiness.reason) == (False, "admin_alert_points_to_subject")


# -- every admin alert: error level, one stable tag ----------------------------------------


def test_the_helper_logs_at_error_level_with_the_tag(tags: list[tuple[str, str]]) -> None:
    logger = Mock()
    admin_alert(logger, "something_needs_craig", kind=KIND_BILLING, detail=1)
    logger.error.assert_called_once_with(
        "something_needs_craig", admin_alert=KIND_BILLING, detail=1
    )
    assert tags == [(ADMIN_ALERT_TAG, KIND_BILLING)]


def test_the_kinds() -> None:
    assert KINDS == {
        "billing",
        "generation_failure",
        "longitudinal",
        "cross_surface_disagreement",
        "figure_contest",
        "verdict_less_cautious",
    }
    assert generation_failure_kind("billing", "brief") == KIND_BILLING
    assert generation_failure_kind("billing", "longitudinal_analysis") == KIND_BILLING
    assert generation_failure_kind("timeout", "longitudinal_analysis") == KIND_LONGITUDINAL
    assert generation_failure_kind("timeout", "brief") == KIND_GENERATION_FAILURE


@pytest.mark.asyncio
async def test_a_failed_generation_reaches_sentry_and_never_marks_phone(
    monkeypatch: pytest.MonkeyPatch, tags: list[tuple[str, str]]
) -> None:
    log, push = Mock(), AsyncMock()
    monkeypatch.setattr(nudge_alerts, "log", log)
    monkeypatch.setattr(nudge_alerts, "send_notification", push)
    monkeypatch.setattr(settings, "admin_alert_user_id", "")

    pushed = await NudgeAlertService(Mock()).notify_admin_generation_failure(
        reason="billing", subject_date=date(2026, 10, 4)
    )

    assert pushed is False
    push.assert_not_called()
    assert log.error.call_args.args == ("brief_generation_admin_alert",)
    assert log.error.call_args.kwargs["admin_alert"] == KIND_BILLING
    assert tags == [(ADMIN_ALERT_TAG, KIND_BILLING)]


@pytest.mark.asyncio
async def test_a_contested_figure_reaches_sentry(
    monkeypatch: pytest.MonkeyPatch, tags: list[tuple[str, str]]
) -> None:
    log = Mock()
    monkeypatch.setattr(nudge_alerts, "log", log)
    monkeypatch.setattr(settings, "admin_alert_user_id", "")

    await NudgeAlertService(Mock()).notify_admin_figure_contest(
        dispute_id=uuid.uuid4(),
        label="Bedroom peak",
        value=20.9,
        units="°C",
        subject_date=date(2026, 9, 13),
        reason="That's not my bedroom.",
    )

    assert log.error.call_args.args == ("figure_contest_admin_alert",)
    assert tags == [(ADMIN_ALERT_TAG, KIND_FIGURE_CONTEST)]


def test_a_cross_surface_disagreement_reaches_sentry(
    monkeypatch: pytest.MonkeyPatch, tags: list[tuple[str, str]]
) -> None:
    from tests.test_batch_272_cross_surface_agreement import _stored_week_check

    log = Mock()
    monkeypatch.setattr(cross_surface_agreement, "log", log)
    check = _stored_week_check(date(2026, 9, 7), date(2026, 9, 13), 20.9)
    assert check is not None

    alert_disagreements(
        evaluate_agreement([check]), surface="weekly_review", user_id=uuid.uuid4(), subject="x"
    )

    assert log.error.call_args.args[0] == "cross_surface_disagreement"
    assert tags == [(ADMIN_ALERT_TAG, KIND_CROSS_SURFACE)]


def test_a_graded_verdict_two_steps_less_cautious_reaches_sentry(
    monkeypatch: pytest.MonkeyPatch, tags: list[tuple[str, str]]
) -> None:
    log = Mock()
    monkeypatch.setattr(morning_analysis_module, "log", log)
    monkeypatch.setattr(morning_analysis_module, "VERDICT_ENGINE", ENGINE_GRADED)

    _log_verdict_engines(
        Mock(id=uuid.uuid4()),
        date(2026, 10, 7),
        ladder_status="Red",
        graded=Mock(status="Green", label="Green"),
    )

    assert log.error.call_args.args == ("verdict_graded_two_steps_less_cautious",)
    assert tags == [(ADMIN_ALERT_TAG, KIND_VERDICT_LESS_CAUTIOUS)]


@pytest.mark.asyncio
async def test_a_failed_monthly_analysis_reaches_sentry(
    monkeypatch: pytest.MonkeyPatch, tags: list[tuple[str, str]]
) -> None:
    log = Mock()
    monkeypatch.setattr(scheduler, "log", log)
    player = Mock(id=uuid.uuid4(), timezone="Europe/London")
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [player]
    session = MagicMock()
    session.execute = AsyncMock(return_value=rows)
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[Any]:
        yield session

    class _Failing:
        def __init__(self, _session: Any) -> None:
            pass

        async def collect_pending(self, _player: Any) -> Any:
            raise RuntimeError("the batch endpoint fell over")

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", fake_session)
    monkeypatch.setattr(scheduler, "LongitudinalAnalysisService", _Failing)

    result = await scheduler.run_longitudinal_analysis()

    assert (result.status, result.reason) == (JobStatus.degraded, "longitudinal_analysis_failed")
    assert log.error.call_args.args == ("longitudinal analysis failed",)
    assert log.error.call_args.kwargs["exc_info"] is True
    assert tags == [(ADMIN_ALERT_TAG, KIND_LONGITUDINAL)]


def test_a_failed_note_reading_stays_a_warning() -> None:
    """Craig, 3 Oct 2026: a notes-reader outage alone does not page him."""
    source = inspect.getsource(notes_reader)
    assert '"notes_reading_failed"' in source
    assert "admin_alert" not in source


# -- the monthly analysis runs with Sentry as its route (PostgreSQL, CI) -------------------


@pytest.mark.asyncio
async def test_the_monthly_analysis_submits_with_sentry_as_the_route(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_longitudinal_analysis_db import _BatchClient, _finding_payload, _seed_profiles

    player_id, operator_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(settings, "admin_alert_user_id", "")
    monkeypatch.setattr(settings, "sentry_dsn_backend", SENTRY_DSN)
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player, _operator = await _seed_profiles(
            session, player_id=player_id, operator_id=operator_id
        )
        readiness = await billing_alert_readiness(session, subject_profile_id=player.id)
        assert (readiness.ready, readiness.route) == (True, "sentry")
        client = _BatchClient(_finding_payload())

        submitted = await LongitudinalAnalysisService(session).submit_monthly(
            player, as_of_date=date(2026, 8, 24), client=client
        )

        assert submitted.submitted is True
        assert client.submissions == 1


def test_an_alert_raised_in_the_job_runner_reaches_sentry() -> None:
    """Found at 291's close-out: the job runner initialised Sentry but not logging.

    Without the API's logging setup, structlog printed to stdout and Sentry saw no
    error a job logged (0 events, measured 4 Oct 2026). A subprocess, because logging
    and Sentry state are process-wide; the transport records instead of sending.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = (
        "import sys, asyncio\n"
        "import sentry_sdk, structlog\n"
        "from sentry_sdk.transport import Transport\n"
        "import src.run_scheduled as rs\n"
        "from src.services.admin_alerts import admin_alert\n"
        "from src.services.job_runs import JobResult\n"
        "seen = []\n"
        "class Capture(Transport):\n"
        "    def capture_envelope(self, envelope):\n"
        "        for item in envelope.items:\n"
        "            body = item.payload.json if item.payload else None\n"
        "            if body and body.get('level') == 'error':\n"
        "                seen.append(body.get('tags', {}).get('admin_alert'))\n"
        "rs.init_sentry = lambda *a, **k: sentry_sdk.init(\n"
        "    dsn='https://public@o1.ingest.sentry.io/1', transport=Capture) or True\n"
        "def run(coro):\n"
        "    coro.close()\n"
        "    admin_alert(structlog.get_logger('job'), 'probe_alert', kind='longitudinal')\n"
        "    return JobResult.succeeded()\n"
        "rs.asyncio.run = run\n"
        "sys.argv = ['run_scheduled', 'hive-poll']\n"
        "rs.main()\n"
        "sentry_sdk.flush(2)\n"
        "print('ALERTS', seen)\n"
    )
    api_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=api_root,
        env={**os.environ, "PYTHONPATH": str(api_root)},
    )
    assert result.returncode == 0, result.stderr
    assert "ALERTS ['longitudinal']" in result.stdout, result.stdout


def test_a_provider_batch_is_stored_as_json() -> None:
    """Found at close-out: the first monthly submission reached Anthropic, then its record
    failed to save because the SDK's batch object kept real datetimes (4 Oct 2026)."""
    import json
    from datetime import UTC, datetime

    from anthropic.types.messages import MessageBatch

    from src.services.anthropic_batch import _as_object

    batch = MessageBatch.model_validate(
        {
            "id": "msgbatch_test",
            "type": "message_batch",
            "processing_status": "in_progress",
            "request_counts": {
                "processing": 1,
                "succeeded": 0,
                "errored": 0,
                "canceled": 0,
                "expired": 0,
            },
            "created_at": datetime(2026, 10, 4, 3, 34, tzinfo=UTC),
            "expires_at": datetime(2026, 10, 5, 3, 34, tzinfo=UTC),
            "ended_at": None,
            "archived_at": None,
            "cancel_initiated_at": None,
            "results_url": None,
        }
    )

    stored = _as_object(batch, "create")

    assert json.loads(json.dumps(stored))["created_at"].startswith("2026-10-04T03:34")
    assert stored["id"] == "msgbatch_test"
