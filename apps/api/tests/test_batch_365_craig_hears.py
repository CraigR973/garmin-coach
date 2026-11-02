"""Batch 365 — Craig hears when it breaks.

On 1 Nov 2026 Garmin refused the app's stored login from 00:25 to 12:01 UTC. The polls
failed as warnings, the morning was filed ``inputs`` (which alerts nobody), one 11:00 run
made twelve refused logins, and nothing outside the process watched it (DS357-01, -02).
The app had also been refreshing with 21 Jun's token for 132 days, throwing each renewed
one away. These tests pin the watchdog, the once-a-day source alert, the kept token, and
the small fixes that ride with them (CR356-01, -02, -06; DS357-05, -06, -07).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src import scheduler
from src.main import app
from src.models.coaching import BriefGenerationStatus, Sleep
from src.models.operations import JobRun, ProviderToken
from src.models.profile import Profile, UserRole
from src.services import admin_alerts, garmin_tokens
from src.services.admin_alerts import KIND_SOURCE_AUTH, source_auth_alert
from src.services.garmin_sync import GarminConnectClient, GarminCredentials, GarminLoginError
from src.services.job_ledger_freshness import (
    FreshnessReport,
    JobFreshness,
    collect_watchdog_report,
    watchdog_problems,
)
from src.services.morning_inputs import MorningInputPresence
from src.services.morning_pipeline import (
    BACKSTOP_POLICY,
    REASON_INPUTS_PROVIDER,
    MorningBriefOutcome,
    MorningBriefPipeline,
    sync_garmin_daily,
)
from src.services.retry import retry_sync

REPO = Path(__file__).resolve().parents[3]
DAY = date(2026, 11, 1)


@pytest.fixture(autouse=True)
def _fresh_state() -> Any:
    garmin_tokens._reset_for_tests()
    admin_alerts._SOURCE_AUTH_ALERTED.clear()
    yield
    garmin_tokens._reset_for_tests()
    admin_alerts._SOURCE_AUTH_ALERTED.clear()


# -- 365.2: a refused login is never retried, and Craig hears once a day --------------------


@pytest.mark.asyncio
async def test_a_refused_login_is_raised_at_once_and_a_blip_is_still_retried() -> None:
    calls = 0

    def refused() -> None:
        nonlocal calls
        calls += 1
        raise GarminLoginError("refused")

    with pytest.raises(GarminLoginError):
        await retry_sync(refused, delay_sec=0, give_up_on=(GarminLoginError,))
    assert calls == 1

    attempts = 0

    def blip() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError
        return "ok"

    assert await retry_sync(blip, delay_sec=0, give_up_on=(GarminLoginError,)) == "ok"
    assert attempts == 3


def test_a_refused_source_alerts_once_a_day_and_always_logs() -> None:
    logger = MagicMock()
    assert source_auth_alert(logger, "garmin", today=DAY, step="activity_poll") is True
    assert source_auth_alert(logger, "garmin", today=DAY, step="wake_check") is False
    assert source_auth_alert(logger, "hive", today=DAY) is True  # its own day
    assert source_auth_alert(logger, "garmin", today=DAY + timedelta(1)) is True
    errors = [call for call in logger.error.call_args_list]
    assert [call.kwargs["admin_alert"] for call in errors] == [KIND_SOURCE_AUTH] * 3
    assert logger.warning.call_count == 4  # every refusal is still counted
    assert KIND_SOURCE_AUTH in admin_alerts.KINDS


class _RefusingClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_daily_payloads(self, subject_date: date) -> Any:
        self.calls += 1
        raise GarminLoginError("Garmin token blob failed")


@pytest.mark.asyncio
async def test_the_daily_sync_asks_once_and_stops_when_the_login_is_refused() -> None:
    """1 Nov's 11:00 run asked twelve times: four dates, three tries each."""
    profile = MagicMock(id=uuid.uuid4(), timezone="Europe/London", garmin_user_profile_pk=1)
    client = _RefusingClient()
    alert = MagicMock()
    with patch("src.services.morning_pipeline.source_auth_alert", alert):
        result = await sync_garmin_daily(AsyncMock(), [profile], client=client)  # type: ignore[arg-type]
    assert client.calls == 1
    assert (result.garmin_auth_refused, result.failures, result.daily_metrics) == (1, 1, 0)
    alert.assert_called_once()
    assert alert.call_args.args[1] == "garmin"


@pytest.mark.asyncio
async def test_a_morning_held_by_a_refused_provider_says_so_and_alerts_only_as_a_source() -> None:
    profile = MagicMock(id=uuid.uuid4(), timezone="Europe/London")
    morning = MagicMock()
    morning.grade_and_store = AsyncMock(return_value=MagicMock(written=False, analysis=MagicMock()))
    morning.write_brief = AsyncMock()
    pipeline = MorningBriefPipeline(AsyncMock(), policy=BACKSTOP_POLICY, morning_service=morning)
    pipeline.status = MagicMock(mark_failed=AsyncMock(), mark_generating=AsyncMock())
    pipeline.nudges = MagicMock(
        push_call_ready=AsyncMock(return_value=True),
        notify_admin_generation_failure=AsyncMock(),
    )
    pipeline.coaching = MagicMock(
        regenerate_for_verdict=AsyncMock(return_value=[]),
        propose_chronic_deload=AsyncMock(return_value=[]),
    )
    pipeline._garmin_refused = True
    not_ready = AsyncMock(return_value=MorningInputPresence(daily_metrics=False, sleep=False))
    with patch("src.services.morning_pipeline.morning_input_presence", not_ready):
        outcome = await pipeline.generate_brief(profile, DAY)
    assert outcome.code_only is True
    pipeline.status.mark_failed.assert_awaited_once_with(
        profile.id, DAY, reason=REASON_INPUTS_PROVIDER, commit=True
    )
    pipeline.nudges.notify_admin_generation_failure.assert_not_awaited()
    morning.write_brief.assert_not_awaited()


# -- 365.1: the watchdog -----------------------------------------------------------------------


def _fresh(*stale: str) -> FreshnessReport:
    return FreshnessReport(
        checked=tuple(
            JobFreshness(
                job_name=name,
                last_run_utc=None if name in stale else datetime(2026, 11, 2, 9),
                age=None if name in stale else timedelta(minutes=5),
                max_age=timedelta(hours=2),
            )
            for name in ("wake-check", "morning-sync", *stale)
        )
    )


def test_the_watchdog_names_a_stale_job_a_failing_job_and_a_refused_login() -> None:
    assert watchdog_problems(freshness=_fresh(), recent_runs={}, brief_failures=[]) == ()
    problems = watchdog_problems(
        freshness=_fresh("backup"),
        recent_runs={
            # A frequent job needs two failures in a row; one is a blip.
            "wake-check": [("failed", "wake_check_failed"), ("succeeded", None)],
            "activity-poll": [
                ("failed", "garmin_auth_refused"),
                ("failed", "garmin_auth_refused"),
            ],
            # A daily job's newest failure is enough.
            "morning-sync": [("failed", "morning_pipeline_failed"), ("succeeded", None)],
            "hive-poll": [("failed", "hive_reauth_required")],
        },
        brief_failures=["billing", "inputs", "inputs_provider"],
    )
    assert problems == (
        "stale:backup",
        "failing:activity-poll",
        "failing:morning-sync",
        "garmin_refused",
        "hive_refused",
        "brief_failed:billing",
    )


@asynccontextmanager
async def _session_ctx() -> AsyncIterator[MagicMock]:
    yield MagicMock()


@pytest.mark.asyncio
async def test_the_jobs_route_reports_codes_only_and_503_without_a_database() -> None:
    report = MagicMock(status="alert", problems=("garmin_refused",))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch("src.routers.health.AsyncSessionLocal", _session_ctx),
            patch("src.routers.health.collect_watchdog_report", AsyncMock(return_value=report)),
        ):
            ok = await client.get("/api/v1/health/jobs")
        with (
            patch("src.routers.health.AsyncSessionLocal", _session_ctx),
            patch(
                "src.routers.health.collect_watchdog_report",
                AsyncMock(side_effect=OSError("no database")),
            ),
        ):
            down = await client.get("/api/v1/health/jobs")
    assert (ok.status_code, ok.json()) == (
        200,
        {"status": "alert", "problems": ["garmin_refused"]},
    )
    assert (down.status_code, down.json()["problems"]) == (503, ["db_unreachable"])


def _watchdog_script() -> types.ModuleType:
    path = REPO / "scripts" / "watchdog.py"
    spec = importlib.util.spec_from_file_location("watchdog_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["watchdog_script"] = module
    spec.loader.exec_module(module)
    return module


def test_the_watchdog_script_fails_on_any_problem_and_passes_on_none() -> None:
    script = _watchdog_script()

    def healthy(url: str, timeout: float) -> tuple[int, dict[str, Any]]:
        if url.endswith("/ready"):
            return 200, {"status": "ready", "db": "ok"}
        return 200, {"status": "ok", "problems": []}

    def broken(url: str, timeout: float) -> tuple[int, dict[str, Any]]:
        if url.endswith("/ready"):
            return 503, {"status": "not_ready", "db": "unreachable"}
        return 200, {"status": "alert", "problems": ["garmin_refused"]}

    assert script.problems("https://api.example", fetch=healthy) == []
    assert script.problems("https://api.example", fetch=broken) == [
        "not_ready:http_503",
        "garmin_refused",
    ]
    with patch.object(script, "problems", return_value=["garmin_refused"]):
        assert script.main(["--base-url", "https://api.example"]) == 1
    with patch.object(script, "problems", return_value=[]):
        assert script.main(["--base-url", "https://api.example"]) == 0


def test_the_watchdog_runs_every_half_hour_off_the_hour_with_no_secret() -> None:
    workflow = (REPO / ".github" / "workflows" / "watchdog.yml").read_text(encoding="utf-8")
    assert 'cron: "7,37 * * * *"' in workflow
    assert "python scripts/watchdog.py --base-url https://api-production-e2bc7.up.railway.app" in (
        workflow
    )
    assert "secrets." not in workflow


async def _job_run(
    session: AsyncSession, name: str, status: str, reason: str | None, at: datetime
) -> None:
    session.add(
        JobRun(
            job_name=name,
            scheduled_window_start_utc=at - timedelta(minutes=1),
            scheduled_window_end_utc=at,
            started_at_utc=at,
            finished_at_utc=at,
            status=status,
            reason=reason,
            counters={},
        )
    )


@pytest.mark.asyncio
async def test_on_postgres_the_watchdog_reads_the_two_newest_runs_and_todays_brief(
    db_conn: AsyncConnection,
) -> None:
    now = datetime(2026, 11, 1, 11, 30)
    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        await session.execute(text("DELETE FROM job_runs"))
        player = Profile(
            id=uuid.uuid4(),
            display_name=f"Watchdog {uuid.uuid4().hex[:6]}",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        await _job_run(session, "activity-poll", "succeeded", None, now - timedelta(hours=3))
        await _job_run(
            session, "activity-poll", "failed", "garmin_auth_refused", now - timedelta(hours=1)
        )
        await _job_run(session, "activity-poll", "failed", "garmin_auth_refused", now)
        await _job_run(session, "morning-sync", "succeeded", None, now - timedelta(minutes=30))
        session.add(
            BriefGenerationStatus(
                user_id=player.id, subject_date=now.date(), status="failed", reason="billing"
            )
        )
        await session.flush()
        report = await collect_watchdog_report(session, now_utc=now.replace(tzinfo=UTC))
    assert report.status == "alert"
    assert {"failing:activity-poll", "garmin_refused", "brief_failed:billing"} <= set(
        report.problems
    )
    assert "failing:morning-sync" not in report.problems
    assert "stale:morning-sync" not in report.problems


# -- 365.3: each renewed Garmin token is kept ---------------------------------------------


DEPLOYED = json.dumps({"di_token": "a" * 600, "di_refresh_token": "deployed", "di_client_id": "c"})


def _tokens(refresh: str) -> str:
    return json.dumps({"di_token": "b" * 600, "di_refresh_token": refresh, "di_client_id": "c"})


class _FakeSession:
    def __init__(self) -> None:
        self.rows: dict[str, ProviderToken] = {}
        self.commits = 0

    async def get(self, model: Any, key: str) -> ProviderToken | None:
        return self.rows.get(key)

    def add(self, row: ProviderToken) -> None:
        self.rows[row.provider] = row

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_a_renewed_token_is_kept_encrypted_and_restored_by_the_next_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(garmin_tokens.settings, "garmin_tokenstore_b64", DEPLOYED)
    session = _FakeSession()
    garmin_tokens.remember(_tokens("renewed-1"))
    assert await garmin_tokens.persist(session) is True  # type: ignore[arg-type]
    assert await garmin_tokens.persist(session) is False  # unchanged: nothing written
    row = session.rows["garmin"]
    assert "renewed-1" not in row.ciphertext  # a database read alone yields no token
    assert row.source_fingerprint == garmin_tokens.fingerprint(DEPLOYED)

    garmin_tokens._reset_for_tests()  # a new process
    assert await garmin_tokens.restore(session) is True  # type: ignore[arg-type]
    assert garmin_tokens.current() == _tokens("renewed-1")


@pytest.mark.asyncio
async def test_a_re_minted_variable_wins_over_the_kept_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(garmin_tokens.settings, "garmin_tokenstore_b64", DEPLOYED)
    session = _FakeSession()
    garmin_tokens.remember(_tokens("renewed-1"))
    await garmin_tokens.persist(session)  # type: ignore[arg-type]
    garmin_tokens._reset_for_tests()
    monkeypatch.setattr(garmin_tokens.settings, "garmin_tokenstore_b64", _tokens("re-minted"))
    assert await garmin_tokens.restore(session) is False  # type: ignore[arg-type]
    assert garmin_tokens.current() is None


def test_a_token_without_a_refresh_token_is_never_kept() -> None:
    garmin_tokens.remember(json.dumps({"di_token": "x"}))
    garmin_tokens.remember("not json")
    assert garmin_tokens.current() is None


class _FakeInner:
    def __init__(self, tokens: str | None) -> None:
        self.tokens = tokens

    def dumps(self) -> str | None:
        return self.tokens


class _FakeGarmin:
    refused: set[str] = set()
    logins: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.client = _FakeInner(None)

    def login(self, tokens: str) -> None:
        _FakeGarmin.logins.append(json.loads(tokens)["di_refresh_token"])
        if tokens in _FakeGarmin.refused:
            raise RuntimeError("invalid_grant")
        # garminconnect refreshes on login; the renewed token is what dumps() returns.
        self.client = _FakeInner(_tokens("renewed-" + json.loads(tokens)["di_refresh_token"]))


def _client(tmp_path: Path) -> GarminConnectClient:
    return GarminConnectClient(
        GarminCredentials(email="", password="", tokenstore=tmp_path, tokenstore_b64=DEPLOYED)
    )


def test_the_client_logs_in_with_the_kept_token_and_keeps_what_garmin_renews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "garminconnect", types.SimpleNamespace(Garmin=_FakeGarmin))
    _FakeGarmin.refused, _FakeGarmin.logins = set(), []
    garmin_tokens.remember(_tokens("kept"))
    _client(tmp_path).login()
    assert _FakeGarmin.logins == ["kept"]
    assert json.loads(garmin_tokens.current() or "{}")["di_refresh_token"] == "renewed-kept"


def test_a_refused_kept_token_falls_back_to_the_deployed_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "garminconnect", types.SimpleNamespace(Garmin=_FakeGarmin))
    _FakeGarmin.refused, _FakeGarmin.logins = {_tokens("kept")}, []
    garmin_tokens.remember(_tokens("kept"))
    _client(tmp_path).login()
    assert _FakeGarmin.logins == ["kept", "deployed"]
    assert json.loads(garmin_tokens.current() or "{}")["di_refresh_token"] == "renewed-deployed"


def test_garminconnect_is_pinned_to_the_line_whose_token_store_the_app_keeps() -> None:
    requirements = (REPO / "apps" / "api" / "requirements.txt").read_text(encoding="utf-8")
    assert "garminconnect>=0.3.7,<0.4" in requirements
    lock = (REPO / "apps" / "api" / "requirements.lock").read_text(encoding="utf-8")
    assert "garminconnect==0.3." in lock


# -- 365.4: the small fixes ---------------------------------------------------------------------


def test_sentry_never_receives_a_failing_frames_local_variables() -> None:
    from src import observability

    source = Path(observability.__file__).read_text(encoding="utf-8")
    assert "include_local_variables=False" in source


def test_every_job_gets_fifteen_minutes_of_misfire_grace() -> None:
    created = scheduler.create_scheduler()
    defaults = created._job_defaults  # type: ignore[attr-defined]
    assert (defaults["misfire_grace_time"], defaults["coalesce"]) == (900, True)


def _savepoint(db_conn: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


async def _player(session: AsyncSession, name: str) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name=f"{name} {uuid.uuid4().hex[:6]}",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.flush()
    return player


@pytest.mark.asyncio
async def test_on_postgres_a_failed_backstop_step_is_isolated_and_named(
    db_conn: AsyncConnection,
) -> None:
    """CR356-01, proved: the handler read ``profile.id`` after its rollback and raised."""
    async with _savepoint(db_conn) as session:
        player = await _player(session, "Isolated Step")
        await session.commit()
        pipeline = MorningBriefPipeline(session, policy=BACKSTOP_POLICY)
        outcome = MorningBriefOutcome()

        async def touches_the_database_then_fails() -> int:
            await session.execute(text("SELECT 1"))
            raise RuntimeError("step failed")

        value = await pipeline._isolated(
            touches_the_database_then_fails, player, DAY, None, outcome, step="amber regeneration"
        )
    assert value == 0
    assert (outcome.failures, outcome.failed_steps) == (1, ["amber regeneration"])


@pytest.mark.asyncio
async def test_on_postgres_a_failed_month_still_writes_the_season(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR356-02: without the reload between buckets the season read the expired profile."""
    async with _savepoint(db_conn) as session:
        player = await _player(session, "Trends Reload")
        session.add(Sleep(user_id=player.id, calendar_date=DAY, raw_payload={}, factors_json={}))
        await session.commit()
        mine = player.id
        seasons: list[uuid.UUID] = []

        async def narrative_run(self: Any, who: Profile, *, bucket: str, as_of: date) -> Any:
            if who.id != mine:
                return MagicMock(generated=False, status="existing")
            if bucket == "month":
                await self.session.execute(text("SELECT 1"))
                raise RuntimeError("month failed")
            seasons.append(who.id)  # reads the profile the month's rollback expired
            return MagicMock(generated=True)

        monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: session)
        monkeypatch.setattr(scheduler.TrendsService, "narrative_run", narrative_run)
        monkeypatch.setattr(
            scheduler.NudgeAlertService, "notify_admin_generation_failure", AsyncMock()
        )
        result = await scheduler.run_trend_narratives()
    assert seasons == [mine]
    assert result.counters["generated"] >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", ["reader", "push"])
async def test_on_postgres_a_failed_backstop_reader_or_push_leaves_the_next_reader_a_profile(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch, fails: str
) -> None:
    """CR356-02: the two reloads in the 20:30 backstop, after a reader and after a push."""
    async with _savepoint(db_conn) as session:
        player = await _player(session, "Backstop Reload")
        await session.commit()
        mine = player.id
        later: list[uuid.UUID] = []

        async def ride(self: Any, who: Profile, *, since: datetime, commit: bool) -> list[Any]:
            if who.id != mine:
                return []
            await self.session.execute(text("SELECT 1"))
            if fails == "reader":
                raise RuntimeError("reader failed")
            return [MagicMock(generated=True, analysis=MagicMock())]

        async def flexibility(
            self: Any, who: Profile, *, since: datetime, commit: bool
        ) -> list[Any]:
            if who.id == mine:
                later.append(who.id)  # reads the profile the failure's rollback expired
            return []

        async def push(self: Any, *args: Any, **kwargs: Any) -> bool:
            await self.session.execute(text("SELECT 1"))
            raise RuntimeError("push failed")

        monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: session)
        monkeypatch.setattr(
            scheduler.PostWorkoutAnalysisService, "generate_for_pending_rides", ride
        )
        monkeypatch.setattr(
            scheduler.PostFlexibilityAnalysisService,
            "generate_for_pending_flexibility",
            flexibility,
        )
        for service, method in (
            (scheduler.PostStrengthAnalysisService, "generate_for_pending_strength"),
            (scheduler.PostWalkAnalysisService, "generate_for_pending_walks"),
        ):
            monkeypatch.setattr(service, method, AsyncMock(return_value=[]))
        monkeypatch.setattr(scheduler.NudgeAlertService, "push_workout_analysis", push)
        result = await scheduler.run_post_workout_backstop()
    assert later == [mine]
    assert result.counters["failed"] >= 1
