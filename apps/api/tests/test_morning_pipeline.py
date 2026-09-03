"""Batch 251 (CR236-02/06/09): one morning pipeline, one status owner, one 409.

The three triggers used to be three implementations. These tests pin the parts of
that which are contracts rather than structure: that all three doors lead to the
same pipeline, that the transaction contract is declared rather than inherited,
that both generating triggers record the same outcome, and that the private
cross-module import cannot come back.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src import scheduler
from src.main import app
from src.routers import daily_loop as daily_loop_router
from src.services.generation_requests import (
    STATUS_FAILED,
    STATUS_RUNNING,
    GenerationClaim,
    GenerationRequestInProgress,
    _record_claim_failure,
)
from src.services.morning_inputs import MorningInputPresence
from src.services.morning_pipeline import (
    BACKSTOP_POLICY,
    CHECKIN_POLICY,
    CommitPolicy,
    MorningBriefPipeline,
    MorningInputResult,
    MorningTrigger,
    run_checkin_brief,
)

SRC = Path(scheduler.__file__).resolve().parent


def _router_ast() -> ast.Module:
    return ast.parse((SRC / "routers" / "daily_loop.py").read_text())


def _profile() -> MagicMock:
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.timezone = "Europe/London"
    profile.latitude = None
    profile.longitude = None
    profile.is_active = True
    profile.deleted_at = None
    profile.hosted_tts_consent = False
    return profile


def _session_ctx(session: object) -> object:
    class _Ctx:
        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_a: object) -> None:
            return None

    return _Ctx()


def _ready() -> AsyncMock:
    return AsyncMock(return_value=MorningInputPresence(daily_metrics=True, sleep=True))


# ---------------------------------------------------------------------------
# All three triggers run one pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_morning_trigger_goes_through_the_one_pipeline() -> None:
    """Wake, check-in and the 11:00 backstop each build a MorningBriefPipeline.

    Before Batch 251 this was three implementations in two modules — which is what
    every morning-path defect in the ledger (141, 144, 222, 232.1) has in common.
    """
    profile = _profile()
    session = AsyncMock()
    sync = AsyncMock(return_value=MorningInputResult())
    generate = AsyncMock(return_value=MagicMock(failures=0))
    nudge = AsyncMock(return_value=MagicMock(sent=True, failures=0))

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch(
            "src.services.morning_pipeline.AsyncSessionLocal", return_value=_session_ctx(session)
        ),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch.object(MorningBriefPipeline, "sync_inputs", sync),
        patch.object(MorningBriefPipeline, "generate_brief", generate),
        patch.object(MorningBriefPipeline, "send_wake_nudge", nudge),
    ):
        await scheduler.run_wake_nudge()
        await scheduler.run_morning_weather_sync()
        session.get = AsyncMock(return_value=profile)
        await daily_loop_router._generate_brief_after_checkin(profile.id, date(2026, 9, 3))

    assert sync.await_count == 3  # every trigger syncs through the same helper
    assert nudge.await_count == 1  # only the wake job nudges
    assert generate.await_count == 2  # the backstop and the check-in generate


def test_the_router_no_longer_reaches_into_the_scheduler() -> None:
    """CR236-02's most concrete symptom: a router importing a *private* scheduler
    helper inside a function to dodge an import cycle. Pinned so it cannot return.
    """
    imported = {
        node.module
        for node in ast.walk(_router_ast())
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(module.startswith("src.scheduler") for module in imported)
    assert not hasattr(scheduler, "_sync_morning_inputs")


def test_the_wake_job_and_the_backstop_no_longer_share_a_name() -> None:
    """``run_scheduled`` exposes the *backstop* as ``morning-sync`` while the wake
    job was called ``run_morning_sync`` — the two names collided on the one word
    that distinguished them.
    """
    from src import run_scheduled

    assert run_scheduled.JOBS["morning-sync"] is scheduler.run_morning_weather_sync
    assert hasattr(scheduler, "run_wake_nudge")
    assert not hasattr(scheduler, "run_morning_sync")


# ---------------------------------------------------------------------------
# The transaction contract is a parameter, not an accident
# ---------------------------------------------------------------------------


def test_each_trigger_declares_its_transaction_contract() -> None:
    assert CHECKIN_POLICY.trigger is MorningTrigger.CHECKIN
    assert CHECKIN_POLICY.commit is CommitPolicy.TERMINAL
    assert BACKSTOP_POLICY.trigger is MorningTrigger.BACKSTOP
    assert BACKSTOP_POLICY.commit is CommitPolicy.PER_STEP


@pytest.mark.asyncio
async def test_terminal_commit_aborts_the_whole_run_when_a_later_step_fails() -> None:
    """The check-in's contract: the brief and its consequences are one artifact, so
    a failed proposal step must not leave a half-written brief behind."""
    profile = _profile()
    session = AsyncMock()
    morning = MagicMock()
    morning.generate_and_store = AsyncMock(
        return_value=MagicMock(generated=True, analysis=MagicMock())
    )
    coaching = MagicMock()
    coaching.regenerate_for_verdict = AsyncMock(side_effect=RuntimeError("boom"))
    status = MagicMock()
    status.mark_failed = AsyncMock(return_value=MagicMock())
    status.mark_ready = AsyncMock(return_value=MagicMock())

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = MorningBriefPipeline(session, policy=CHECKIN_POLICY, morning_service=morning)
        pipeline.coaching = coaching
        pipeline.status = status
        pipeline.nudges = MagicMock(notify_admin_generation_failure=AsyncMock(return_value=True))
        outcome = await pipeline.generate_brief(profile, date(2026, 9, 3))

    assert outcome.failures == 1
    session.rollback.assert_awaited()
    session.commit.assert_not_awaited()  # nothing half-written
    status.mark_ready.assert_not_awaited()
    status.mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_per_step_commit_isolates_a_failed_step_and_continues() -> None:
    """The backstop's contract: it is a multi-profile loop, so one bad step must
    not cost this profile the rest of the ladder — nor another profile its inputs."""
    profile = _profile()
    session = AsyncMock()
    morning = MagicMock()
    morning.generate_and_store = AsyncMock(
        return_value=MagicMock(generated=True, analysis=MagicMock())
    )
    coaching = MagicMock()
    coaching.regenerate_for_verdict = AsyncMock(side_effect=RuntimeError("boom"))
    coaching.propose_chronic_deload = AsyncMock(return_value=[MagicMock()])
    nudges = MagicMock()
    nudges.push_brief_ready = AsyncMock(return_value=True)
    insights = MagicMock()
    insights.record_drivers = AsyncMock(return_value=MagicMock(record_count=1))

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = MorningBriefPipeline(session, policy=BACKSTOP_POLICY, morning_service=morning)
        pipeline.coaching = coaching
        pipeline.nudges = nudges
        pipeline.insights = insights
        pipeline.status = MagicMock(mark_ready=AsyncMock(), mark_failed=AsyncMock())
        outcome = await pipeline.generate_brief(profile)

    assert outcome.failures == 1  # the one bad step, and only that one
    assert outcome.proposals_regenerated == 0
    assert outcome.chronic_deload_proposals == 1  # the ladder continued
    assert outcome.brief_ready_pushes == 1
    assert outcome.drivers_cached == 1


# ---------------------------------------------------------------------------
# BriefGenerationStatus has a single owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_backstop_failure_now_reaches_mark_and_the_operator() -> None:
    """CR236-02's concrete open asymmetry.

    The 11:00 backstop wrote **no** ``BriefGenerationStatus`` row of any kind, so a
    backstop generation failure produced no failure card, no Retry affordance and
    no operator alert beyond a degraded ``JobResult``. It was survivable only
    because Mark could still check in and take the router path.
    """
    profile = _profile()
    session = AsyncMock()
    morning = MagicMock()
    morning.generate_and_store = AsyncMock(side_effect=RuntimeError("anthropic down"))
    status = MagicMock(mark_failed=AsyncMock(return_value=MagicMock()))
    alert = AsyncMock(return_value=True)

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = MorningBriefPipeline(session, policy=BACKSTOP_POLICY, morning_service=morning)
        pipeline.status = status
        pipeline.nudges = MagicMock(notify_admin_generation_failure=alert)
        outcome = await pipeline.generate_brief(profile, date(2026, 9, 3))

    assert outcome.failures == 1
    status.mark_failed.assert_awaited_once_with(
        profile.id, date(2026, 9, 3), reason="other", commit=True
    )
    alert.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unsynced_morning_is_recorded_but_never_alerted() -> None:
    """``inputs`` is his watch not having synced — a user-state condition rather
    than a fault, and already visible to him on the screen. Both triggers now write
    the card; neither wakes the operator for it."""
    profile = _profile()
    session = AsyncMock()
    status = MagicMock(mark_failed=AsyncMock(return_value=MagicMock()))
    alert = AsyncMock(return_value=True)
    not_ready = AsyncMock(return_value=MorningInputPresence(daily_metrics=False, sleep=False))

    with patch("src.services.morning_pipeline.morning_input_presence", not_ready):
        pipeline = MorningBriefPipeline(session, policy=BACKSTOP_POLICY)
        pipeline.status = status
        pipeline.nudges = MagicMock(notify_admin_generation_failure=alert)
        outcome = await pipeline.generate_brief(profile, date(2026, 9, 3))

    assert outcome.inputs_not_ready is True
    status.mark_failed.assert_awaited_once_with(
        profile.id, date(2026, 9, 3), reason="inputs", commit=True
    )
    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_in_flight_holder_is_still_never_recorded_as_a_failure() -> None:
    """Batch 232.1, now in one handler instead of two with two different bodies."""
    profile = _profile()
    session = AsyncMock()
    morning = MagicMock()
    morning.generate_and_store = AsyncMock(side_effect=GenerationRequestInProgress())
    status = MagicMock(mark=AsyncMock(), mark_failed=AsyncMock(), mark_ready=AsyncMock())

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = MorningBriefPipeline(session, policy=BACKSTOP_POLICY, morning_service=morning)
        pipeline.status = status
        outcome = await pipeline.generate_brief(profile, date(2026, 9, 3))

    assert outcome.deferred is True
    assert outcome.failures == 0
    status.mark_failed.assert_not_awaited()
    status.mark_ready.assert_not_awaited()


def test_only_the_pipeline_and_the_request_path_write_generation_status() -> None:
    """One owner. The router keeps ``mark_generating`` because only it knows a
    check-in was just accepted; every ready/failed transition is the pipeline's.
    """
    writers = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "BriefGenerationStatusService" in path.read_text()
    }
    assert writers == {
        "routers/daily_loop.py",
        "services/brief_generation_status.py",
        "services/daily_loop_envelope.py",
        "services/morning_pipeline.py",
    }
    router_calls = {
        node.func.attr
        for node in ast.walk(_router_ast())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "mark_generating" in router_calls
    assert "mark_ready" not in router_calls and "mark_failed" not in router_calls


# ---------------------------------------------------------------------------
# CR236-06 — a transport exception stops carrying domain control flow
# ---------------------------------------------------------------------------


def test_generation_in_progress_is_a_domain_exception_not_an_http_one() -> None:
    """It is raised in a service and caught by two scheduler jobs and a background
    task, none of which has a client to send a 409 to. Anything catching
    ``HTTPException`` broadly in between used to swallow it — the Batch 232 defect.
    """
    exc = GenerationRequestInProgress()
    assert isinstance(exc, Exception)
    assert not isinstance(exc, HTTPException)


def test_the_409_is_translated_in_exactly_one_place() -> None:
    handler = app.exception_handlers.get(GenerationRequestInProgress)
    assert handler is not None
    assert inspect.iscoroutinefunction(handler)


@pytest.mark.asyncio
async def test_the_registered_handler_answers_409() -> None:
    handler = app.exception_handlers[GenerationRequestInProgress]
    response = await handler(MagicMock(), GenerationRequestInProgress())
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_a_poisoned_session_keeps_its_original_exception() -> None:
    """The recording flush used to run unconditionally. When the body failed for a
    database reason the Session already needed a rollback, so the flush raised
    ``PendingRollbackError`` — replacing the real exception and losing the
    ``failure_reason`` it was recording. Mark then got the generic failure copy
    while the row kept ``status='running'`` on a live lease.
    """
    session = AsyncMock()
    session.get_transaction = MagicMock(return_value=MagicMock(is_active=False))
    claim = GenerationClaim(row=MagicMock(status=STATUS_RUNNING), existing_analysis=None)

    await _record_claim_failure(session, claim, RuntimeError("database went away"))

    session.flush.assert_not_awaited()
    assert claim.row.status == STATUS_RUNNING  # untouched, not falsely marked


@pytest.mark.asyncio
async def test_the_failure_reason_comes_from_a_type_test_not_a_duck_type() -> None:
    """``getattr(exc, "reason", …)`` would stringify any unrelated ``.reason`` a
    future exception happened to carry. ``AnthropicApiError`` is the type that
    actually defines one."""
    from src.services.anthropic_text import AnthropicApiError

    session = AsyncMock()
    session.get_transaction = MagicMock(return_value=MagicMock(is_active=True))

    impostor = RuntimeError("unrelated")
    impostor.reason = "not-a-generation-reason"  # type: ignore[attr-defined]
    claim = GenerationClaim(row=MagicMock(status=STATUS_RUNNING), existing_analysis=None)
    await _record_claim_failure(session, claim, impostor)
    assert claim.row.failure_reason == "generation_error"

    real = AnthropicApiError("billing", reason="billing", status_code=400)
    claim = GenerationClaim(row=MagicMock(status=STATUS_RUNNING), existing_analysis=None)
    await _record_claim_failure(session, claim, real)
    assert claim.row.failure_reason == "billing"
    assert claim.row.status == STATUS_FAILED


# ---------------------------------------------------------------------------
# CR236-09 — the router is a router again
# ---------------------------------------------------------------------------


def test_the_daily_loop_router_is_transport_only() -> None:
    """1,747 lines holding 45 DTOs, a 261-line ``_envelope``, a Dreo fan client
    wrapper and a background generation task — around four routes."""
    tree = _router_ast()
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    functions = [
        node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    ]
    assert classes == []  # all 45 DTOs moved to the schemas module
    assert "build_envelope" not in functions
    assert "_read_fans" not in functions and "_fallback_fans" not in functions
    routes = sum(
        1
        for node in ast.walk(tree)
        for dec in getattr(node, "decorator_list", [])
        if ast.unparse(dec).startswith("router.")
    )
    assert routes == 4


@pytest.mark.asyncio
async def test_the_check_in_entry_point_skips_an_inactive_profile() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    generate = AsyncMock()
    with (
        patch(
            "src.services.morning_pipeline.AsyncSessionLocal", return_value=_session_ctx(session)
        ),
        patch.object(MorningBriefPipeline, "generate_brief", generate),
    ):
        await run_checkin_brief(uuid.uuid4(), date(2026, 9, 3))
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_check_in_syncs_its_own_inputs_before_reading_them() -> None:
    """Batch 222 made the "Syncing your overnight data" stage real. It did so by
    importing a private scheduler helper from a router; the sync is now the
    pipeline's, and the ordering it guaranteed is pinned here."""
    profile = _profile()
    session = AsyncMock()
    session.get = AsyncMock(return_value=profile)
    order: list[str] = []

    async def sync(*_a: object, **_k: object) -> MorningInputResult:
        order.append("sync")
        return MorningInputResult()

    async def generate(*_a: object, **_k: object) -> MagicMock:
        order.append("generate")
        return MagicMock()

    with (
        patch(
            "src.services.morning_pipeline.AsyncSessionLocal", return_value=_session_ctx(session)
        ),
        patch.object(MorningBriefPipeline, "sync_inputs", sync),
        patch.object(MorningBriefPipeline, "generate_brief", generate),
    ):
        await run_checkin_brief(profile.id, date(2026, 9, 3))

    assert order == ["sync", "generate"]
