"""Batch 390 (Decision #512): the self-improving loop's private queue and feed.

Every alert, unhealthy job, written correction, pass-on and dispute becomes one row in
``improvement_items``, repeats folded in; a token-gated feed hands the daily reviewer
(391) the last 14 days; closed rows lose their words after 90 days.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src import run_scheduled
from src.config import settings
from src.database import get_db
from src.main import app
from src.models.coaching import Analysis, BriefMessage, Feedback, ManualEntry
from src.models.operations import ImprovementItem, JobRun
from src.models.profile import Profile, UserRole
from src.scheduler import create_scheduler
from src.services import admin_alerts, improvement_items, job_ledger_freshness, job_runs
from src.services.brief_chat import CoachChatToolbox
from src.services.job_runs import JobResult
from src.tools.loop_pr_body import problems

READ = "r" * 40
WRITE = "w" * 40
NOW = datetime(2026, 11, 24, 12, 0)


# -- Rules, without a database --------------------------------------------------------


def test_every_state_has_rules_and_closed_states_have_no_way_out() -> None:
    assert improvement_items.STATES == set(improvement_items.TRANSITIONS)
    for state in improvement_items.CLOSED_STATES:
        assert improvement_items.TRANSITIONS[state] == frozenset()
    improvement_items.check_transition("new", "triaged")
    improvement_items.check_transition("with_mark", "proposed")
    for current, new in (("new", "shipped"), ("verified", "new"), ("new", "nonsense")):
        with pytest.raises(improvement_items.TransitionError):
            improvement_items.check_transition(current, new)


def test_detail_keeps_codes_only_and_words_are_capped() -> None:
    assert improvement_items.clean_detail(
        {"reason": "timeout", "subject_date": date(2026, 11, 22), "hrv_ms": 41, "nested": {}}
    ) == {"reason": "timeout", "subject_date": "2026-11-22"}
    assert improvement_items.clean_words({"mark": "  ", "coach": 3}) is None
    words = improvement_items.clean_words({"mark": "x" * 9000})
    assert words is not None and len(words["mark"]) == improvement_items.WORDS_MAX


def test_a_cursor_round_trips_and_a_bad_one_is_refused() -> None:
    cursor = improvement_items.FeedCursor(NOW, "chat", str(uuid.uuid4()))
    assert improvement_items.FeedCursor.decode(cursor.encode()) == cursor
    for raw in ("", "2026-11-24T12:00:00|chat", "not-a-date|chat|x"):
        with pytest.raises(ValueError):
            improvement_items.FeedCursor.decode(raw)


@pytest.mark.asyncio
async def test_queue_item_needs_recording_on_and_a_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> None:
        seen.append(kwargs)

    monkeypatch.setattr(improvement_items, "record_item", fake)
    assert (
        improvement_items.queue_item(source="alert", kind="k", summary="s", fingerprint="f")
        is False
    )
    monkeypatch.setattr(improvement_items, "RECORDING_ENABLED", True)
    assert improvement_items.queue_item(source="alert", kind="k", summary="s", fingerprint="f")
    await improvement_items.drain_pending()
    assert seen == [{"source": "alert", "kind": "k", "summary": "s", "fingerprint": "f"}]


def test_queue_item_without_a_running_loop_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(improvement_items, "RECORDING_ENABLED", True)
    assert (
        improvement_items.queue_item(source="alert", kind="k", summary="s", fingerprint="f")
        is False
    )


def test_admin_alert_queues_each_emailed_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(improvement_items, "queue_item", lambda **kw: queued.append(kw) or True)
    for kind in admin_alerts.KINDS:
        admin_alerts.admin_alert(Mock(), "event", kind=kind, reason="r", source="garmin")
    assert {entry["kind"] for entry in queued} == set(admin_alerts.EMAIL_SUBJECTS)
    billing = next(entry for entry in queued if entry["kind"] == admin_alerts.KIND_BILLING)
    assert billing["source"] == "alert"
    assert billing["fingerprint"] == "alert:billing:garmin"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job", "result", "queued"),
    [
        ("post-workout-backstop", JobResult.degraded("step_failures"), True),
        ("hive-poll", JobResult.failed("hive_poll_failed"), True),
        ("hive-poll", JobResult.succeeded(), False),
        ("backup", JobResult.failed("backup_failed"), False),
    ],
)
async def test_an_unhealthy_job_queues_one_folded_item(
    monkeypatch: pytest.MonkeyPatch, job: str, result: JobResult, queued: bool
) -> None:
    record = AsyncMock(return_value=None)
    monkeypatch.setattr(improvement_items, "record_item", record)
    await job_runs._queue_unhealthy_outcome(job, result)
    if queued:
        record.assert_awaited_once()
        assert record.await_args.kwargs["source"] == "job_outcome"
        assert record.await_args.kwargs["fingerprint"] == f"job:{job}"
    else:
        record.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_pass_on_is_queued_with_both_texts_even_when_the_email_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = AsyncMock(return_value=None)
    monkeypatch.setattr(improvement_items, "record_item", record)
    monkeypatch.setattr(
        settings, "alert_email_relay_url", "https://script.google.com/macros/s/x/exec"
    )
    monkeypatch.setattr(settings, "alert_email_relay_secret", "s")
    monkeypatch.setattr("src.services.operator_email.send_pass_on", AsyncMock(return_value=False))
    monkeypatch.setattr("src.services.brief_chat.admin_alert", Mock())
    player = SimpleNamespace(id=uuid.uuid4())
    toolbox = CoachChatToolbox(None, player, "Why has my session no read?")  # type: ignore[arg-type]
    result = await toolbox.execute(
        tool_use_id="one",
        name="pass_to_craig",
        payload={"summary": "Mark asks about a missing read."},
    )
    assert result.is_error
    kwargs = record.await_args.kwargs
    assert kwargs["source"] == "pass_on" and kwargs["user_id"] == player.id
    assert kwargs["words"] == {
        "mark": "Why has my session no read?",
        "coach": "Mark asks about a missing read.",
    }


def test_the_retention_job_is_registered_watched_and_runnable() -> None:
    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("improvement_items_retention")
        assert job is not None
        assert str(job.trigger) == "cron[hour='3', minute='55']"
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    assert "improvement-items-retention" in run_scheduled.JOBS
    assert job_ledger_freshness.MAX_AGE["improvement-items-retention"] == timedelta(days=2)
    assert "improvement-items-retention" in job_runs._LOCAL_DAILY_JOBS


# -- The loop PR body check ----------------------------------------------------------

GOOD_BODY = """## Item
1b2c3d4e-0000-4000-8000-000000000001

## Fault
The post-workout backstop crashed on a planned strength session.

## Change
Load the column the reader needs. Fix alone.

## Tests
A failing test first; every gate green.
"""


def test_a_body_that_follows_the_template_passes() -> None:
    assert problems(GOOD_BODY) == []
    assert problems(GOOD_BODY.replace("crashed", 'crashed ("raiseload")')) == []


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (GOOD_BODY.replace("## Tests", "## Testing"), "missing heading '## Tests'"),
        (
            GOOD_BODY.replace("## Fault", "## Tmp")
            .replace("## Change", "## Fault")
            .replace("## Tmp", "## Change"),
            "headings out of order",
        ),
        (GOOD_BODY.replace("1b2c3d4e-0000-4000-8000-000000000001", "item 42"), "## Item must"),
        (GOOD_BODY + "\n> my legs felt heavy today\n", "a block quote"),
        (
            GOOD_BODY + '\nHe wrote "why did the app not read my session yesterday".\n',
            "a quoted passage",
        ),
    ],
)
def test_a_body_that_departs_from_the_template_fails(body: str, problem: str) -> None:
    assert any(problem in found for found in problems(body)), problems(body)


# -- The token gates, without a database ----------------------------------------------


@pytest.fixture
def client() -> Iterator[AsyncClient]:
    async def fake_db() -> AsyncIterator[Mock]:
        yield Mock()

    app.dependency_overrides[get_db] = fake_db
    try:
        yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    finally:
        app.dependency_overrides.pop(get_db, None)


ROUTES = (
    ("GET", "/api/v1/ops/review-feed", "read"),
    ("GET", f"/api/v1/ops/packets/{uuid.uuid4()}", "read"),
    ("GET", "/api/v1/ops/items", "read"),
    ("POST", "/api/v1/ops/items", "write"),
    ("PATCH", f"/api/v1/ops/items/{uuid.uuid4()}", "write"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "scope"), ROUTES)
async def test_with_no_tokens_set_every_route_is_not_found(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, method: str, path: str, scope: str
) -> None:
    monkeypatch.setattr(settings, "ops_feed_read_token", "")
    monkeypatch.setattr(settings, "ops_feed_write_token", "")
    async with client as http:
        response = await http.request(method, path, headers={"Authorization": f"Bearer {READ}"})
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "scope"), ROUTES)
async def test_a_missing_wrong_or_other_scope_token_is_unauthorized(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, method: str, path: str, scope: str
) -> None:
    monkeypatch.setattr(settings, "ops_feed_read_token", READ)
    monkeypatch.setattr(settings, "ops_feed_write_token", WRITE)
    other = WRITE if scope == "read" else READ
    async with client as http:
        for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": f"Bearer {other}"}):
            response = await http.request(method, path, headers=headers, json={})
            assert response.status_code == 401, (headers, response.text)


# -- Against Postgres ------------------------------------------------------------------


async def _profile(session: AsyncSession) -> Profile:
    user = Profile(
        id=uuid.uuid4(),
        display_name=f"Queue {uuid.uuid4().hex[:8]}",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.mark.asyncio
async def test_a_repeat_folds_into_the_open_item_and_a_closed_one_opens_anew(
    db_conn: AsyncConnection,
) -> None:
    async with _factory(db_conn)() as session:
        first = await improvement_items.record(
            session,
            source="alert",
            kind="billing",
            summary="s",
            fingerprint="alert:billing:",
            words={"coach": "one"},
            now=NOW,
        )
        again = await improvement_items.record(
            session,
            source="alert",
            kind="billing",
            summary="s2",
            fingerprint="alert:billing:",
            now=NOW + timedelta(hours=1),
        )
        assert again == first
        row = await session.get(ImprovementItem, first)
        assert row is not None
        await session.refresh(row)
        assert (row.occurrences, row.summary, row.words) == (2, "s2", {"coach": "one"})
        await improvement_items.update_item(session, first, state="dismissed", now=NOW)
        await session.flush()
        reopened = await improvement_items.record(
            session,
            source="alert",
            kind="billing",
            summary="s3",
            fingerprint="alert:billing:",
            now=NOW + timedelta(days=1),
        )
        assert reopened != first


@pytest.mark.asyncio
async def test_moving_an_item_follows_its_rules_and_closing_stamps_it(
    db_conn: AsyncConnection,
) -> None:
    async with _factory(db_conn)() as session:
        item_id = await improvement_items.record(
            session, source="review", kind="figure", summary="s", fingerprint="review:x", now=NOW
        )
        row = await improvement_items.update_item(
            session, item_id, state="triaged", lane="fix_alone"
        )
        assert (row.state, row.lane, row.closed_utc) == ("triaged", "fix_alone", None)
        with pytest.raises(improvement_items.TransitionError):
            await improvement_items.update_item(session, item_id, state="shipped")
        row = await improvement_items.update_item(session, item_id, state="dismissed", now=NOW)
        assert row.closed_utc == NOW
        with pytest.raises(LookupError):
            await improvement_items.update_item(session, uuid.uuid4(), state="triaged")


@pytest.mark.asyncio
async def test_words_go_ninety_days_after_closing_and_codes_stay(db_conn: AsyncConnection) -> None:
    async with _factory(db_conn)() as session:
        ids = []
        for days, closed in ((91, True), (89, True), (200, False)):
            item_id = await improvement_items.record(
                session,
                source="correction",
                kind="feedback_summary",
                summary="s",
                fingerprint=f"correction:{uuid.uuid4()}",
                words={"mark": "my words"},
                detail={"rating": "way_off"},
                now=NOW - timedelta(days=days),
            )
            if closed:
                await improvement_items.update_item(
                    session, item_id, state="dismissed", now=NOW - timedelta(days=days)
                )
            ids.append(item_id)
        await session.flush()
        assert await improvement_items.wipe_old_words(session, now=NOW) == 1
        rows = [await session.get(ImprovementItem, item_id) for item_id in ids]
        for row in rows:
            assert row is not None
            await session.refresh(row)
        assert [row.words for row in rows if row] == [
            None,
            {"mark": "my words"},
            {"mark": "my words"},
        ]
        assert all(row.detail == {"rating": "way_off"} for row in rows if row)


async def _seed_feed(session: AsyncSession) -> tuple[Profile, Analysis, Analysis]:
    user = await _profile(session)
    recent = Analysis(
        user_id=user.id,
        analysis_type="morning",
        subject_date=date(2026, 11, 22),
        generated_at_utc=NOW - timedelta(days=2),
        prompt_version="morning-analysis-v71",
        model_name="claude-sonnet-5",
        verdict="green",
        context_packet={"verdict": {"status": "green"}},
        output_markdown="Go ahead with today's ride.",
        created_at=NOW - timedelta(days=2),
    )
    old = Analysis(
        user_id=user.id,
        analysis_type="morning",
        subject_date=date(2026, 11, 4),
        generated_at_utc=NOW - timedelta(days=20),
        prompt_version="morning-analysis-v71",
        model_name="claude-sonnet-5",
        verdict="amber",
        context_packet={"verdict": {"status": "amber"}},
        output_markdown="Ease off today.",
        created_at=NOW - timedelta(days=20),
    )
    session.add_all([recent, old])
    await session.flush()
    session.add_all(
        [
            BriefMessage(
                user_id=user.id,
                analysis_id=recent.id,
                role="user",
                content="Why is today green?",
                created_utc=NOW - timedelta(days=1, hours=2),
            ),
            Feedback(
                user_id=user.id,
                analysis_id=recent.id,
                kind="summary",
                rating="a_bit_off",
                correction_text="The ride was yesterday.",
                reason_tags=[],
                created_utc=NOW - timedelta(days=1, hours=1),
            ),
            ManualEntry(
                user_id=user.id,
                entry_date=date(2026, 11, 23),
                entry_at_utc=NOW - timedelta(days=1),
                notes="Slept badly.",
            ),
            JobRun(
                job_name="post-workout-backstop",
                scheduled_window_start_utc=NOW - timedelta(hours=5),
                scheduled_window_end_utc=NOW - timedelta(hours=4),
                started_at_utc=NOW - timedelta(hours=5),
                finished_at_utc=NOW - timedelta(hours=5),
                status="degraded",
                reason="step_failures",
                counters={},
            ),
        ]
    )
    await session.flush()
    await improvement_items.record(
        session,
        source="alert",
        kind="backup",
        summary="Last night's backup failed",
        fingerprint=f"alert:backup:{uuid.uuid4()}",
        now=NOW - timedelta(hours=3),
    )
    await session.flush()
    return user, recent, old


@pytest.mark.asyncio
async def test_the_feed_holds_fourteen_days_in_order_and_pages_without_repeats(
    db_conn: AsyncConnection,
) -> None:
    async with _factory(db_conn)() as session:
        await session.execute(text("DELETE FROM improvement_items"))
        _, recent, old = await _seed_feed(session)
        feed = await improvement_items.build_feed(
            session, since=NOW - timedelta(days=60), limit=improvement_items.FEED_LIMIT_MAX, now=NOW
        )
        types = [event["type"] for event in feed["events"]]
        ids = {event["id"] for event in feed["events"]}
        assert str(recent.id) in ids and str(old.id) not in ids
        assert {"read", "chat", "rating", "checkIn", "jobOutcome", "item"} <= set(types)
        times = [event["at"] for event in feed["events"]]
        assert times == sorted(times)
        assert feed["windowDays"] == 14

        seen: list[str] = []
        cursor = None
        while True:
            page = await improvement_items.build_feed(session, cursor=cursor, limit=2, now=NOW)
            seen += [event["id"] for event in page["events"]]
            if not page["more"]:
                break
            cursor = improvement_items.FeedCursor.decode(page["nextCursor"])
        assert len(seen) == len(set(seen)) and set(seen) >= ids


@pytest.mark.asyncio
async def test_a_packet_is_served_only_inside_the_window(db_conn: AsyncConnection) -> None:
    async with _factory(db_conn)() as session:
        _, recent, old = await _seed_feed(session)
        packet = await improvement_items.packet_for(session, recent.id, now=NOW)
        assert packet is not None and packet["contextPacket"] == {"verdict": {"status": "green"}}
        assert await improvement_items.packet_for(session, old.id, now=NOW) is None


@pytest.fixture
def ops_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_feed_read_token", READ)
    monkeypatch.setattr(settings, "ops_feed_write_token", WRITE)


@pytest.mark.asyncio
async def test_the_routes_read_file_and_move_items_with_their_own_tokens(
    db_conn: AsyncConnection, ops_tokens: None
) -> None:
    factory = _factory(db_conn)

    async def db_override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            read = {"Authorization": f"Bearer {READ}"}
            write = {"Authorization": f"Bearer {WRITE}"}
            feed = await http.get("/api/v1/ops/review-feed", headers=read)
            assert feed.status_code == 200 and set(feed.json()) == {"data", "meta", "errors"}
            created = await http.post(
                "/api/v1/ops/items",
                headers=write,
                json={
                    "source": "review",
                    "kind": "figure_mismatch",
                    "summary": "Two screens named different sleep scores on one morning",
                    "fingerprint": "sleep-score-22-nov",
                    "detail": {"subject_date": "2026-11-22"},
                },
            )
            assert created.status_code == 201, created.text
            item = created.json()["data"]["item"]
            assert item["state"] == "new" and item["source"] == "review"
            moved = await http.patch(
                f"/api/v1/ops/items/{item['id']}",
                headers=write,
                json={"state": "triaged", "lane": "fix_alone", "proposal": {"plan": "x"}},
            )
            assert moved.status_code == 200 and moved.json()["data"]["item"]["lane"] == "fix_alone"
            refused = await http.patch(
                f"/api/v1/ops/items/{item['id']}", headers=write, json={"state": "verified"}
            )
            assert refused.status_code == 409
            listed = await http.get("/api/v1/ops/items", headers=read)
            assert item["id"] in {row["id"] for row in listed.json()["data"]["items"]}
            bad_cursor = await http.get("/api/v1/ops/review-feed?cursor=nope", headers=read)
            assert bad_cursor.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_record_item_writes_through_its_own_session_and_never_raises(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(improvement_items, "RECORDING_ENABLED", True)
    monkeypatch.setattr(improvement_items, "_session_factory", _factory(db_conn))
    fingerprint = f"pass_on:{uuid.uuid4()}"
    item_id = await improvement_items.record_item(
        source="pass_on",
        kind="coach_feedback",
        summary="Mark asked the coach to pass something on",
        fingerprint=fingerprint,
        words={"mark": "q", "coach": "s"},
    )
    assert item_id is not None
    async with _factory(db_conn)() as session:
        row = await session.scalar(
            select(ImprovementItem).where(ImprovementItem.fingerprint == fingerprint)
        )
        assert row is not None and row.words == {"mark": "q", "coach": "s"}
    assert (
        await improvement_items.record_item(
            source="nonsense", kind="k", summary="s", fingerprint="f"
        )
        is None
    )


def test_the_window_and_the_retention_are_craigs_choices() -> None:
    assert improvement_items.FEED_WINDOW_DAYS == 14
    assert improvement_items.WORDS_RETENTION_DAYS == 90
