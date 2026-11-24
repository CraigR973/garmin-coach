"""Batch 378 (Decisions #509, #511): every alert reaches Craig by email.

Craig chose email on 22 Nov 2026, from a Gmail account used only by the app to his own
address. Railway's Hobby plan blocks outbound SMTP, so the app posts over HTTPS to a
Google Apps Script web app in that account, which holds the recipient. Before this,
alerts went to Sentry, where no rule told him: on 22 Nov a pass-on from Mark, an
overnight Anthropic credit outage and a failed backup all reached nobody.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from src import scheduler
from src.config import settings
from src.services import admin_alerts, job_runs, operator_email
from src.services.brief_chat import CoachChatToolbox
from src.services.job_ledger_freshness import FreshnessReport, watchdog_problems
from src.services.job_runs import JobResult

NOW = datetime(2026, 11, 22, 16, 0, tzinfo=UTC)
RELAY = "https://script.google.com/macros/s/AKfycbTestDeploymentId/exec"
#: A made-up value, low-entropy on purpose so the repo's secret scan does not flag it.
SECRET = "x" * 32


@pytest.fixture
def route(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, str]]]:
    """A configured relay whose sends are captured instead of leaving the process."""

    monkeypatch.setattr(settings, "alert_email_relay_url", RELAY)
    monkeypatch.setattr(settings, "alert_email_relay_secret", SECRET)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        operator_email, "_dispatch", lambda subject, body: sent.append((subject, body))
    )
    operator_email.reset_for_tests()
    yield sent
    operator_email.reset_for_tests()


@pytest.fixture
def no_route(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    monkeypatch.setattr(settings, "alert_email_relay_url", "")
    monkeypatch.setattr(settings, "alert_email_relay_secret", "")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        operator_email, "_dispatch", lambda subject, body: sent.append((subject, body))
    )
    operator_email.reset_for_tests()
    return sent


class FakeRelay:
    """Apps Script as the app meets it: a POST, a redirect, then the script's JSON."""

    def __init__(self, answer: Callable[[], httpx.Response] | None = None) -> None:
        self.posts: list[dict[str, Any]] = []
        self.answer = answer or (lambda: httpx.Response(200, json={"status": "sent"}))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "script.google.com":
            assert request.method == "POST"
            self.posts.append(json.loads(request.content))
            return httpx.Response(
                302,
                headers={"Location": "https://script.googleusercontent.com/macros/echo?u=1"},
            )
        assert request.url.host == "script.googleusercontent.com"
        assert request.method == "GET"
        return self.answer()


@pytest.fixture
def relay(monkeypatch: pytest.MonkeyPatch) -> FakeRelay:
    fake = FakeRelay()
    monkeypatch.setattr(
        operator_email,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(fake), follow_redirects=True),
    )
    return fake


@pytest.mark.parametrize(
    "url",
    [
        RELAY.replace("https://", "http://"),
        RELAY.replace("script.google.com", "script.google.com.evil.example"),
        RELAY.replace("script.google.com", "evil.example"),
        RELAY + "?redirect=x",
        RELAY.replace("/exec", "/dev"),
        "https://user:pw@script.google.com/macros/s/x/exec",
        "",
    ],
)
def test_only_an_apps_script_exec_url_is_a_route(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setattr(settings, "alert_email_relay_url", url)
    monkeypatch.setattr(settings, "alert_email_relay_secret", SECRET)
    assert not operator_email.route_ready()


def test_the_route_needs_the_secret_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "alert_email_relay_url", RELAY)
    monkeypatch.setattr(settings, "alert_email_relay_secret", " ")
    assert not operator_email.route_ready()
    monkeypatch.setattr(settings, "alert_email_relay_secret", SECRET)
    assert operator_email.route_ready()


def test_a_send_posts_the_secret_subject_and_body_and_follows_the_redirect(
    route: list[tuple[str, str]], relay: FakeRelay
) -> None:
    assert operator_email.send_sync("[Garmin Coach]  Last night's\nbackup failed", "Body") is True
    assert relay.posts == [
        {"secret": SECRET, "subject": "[Garmin Coach] Last night's backup failed", "body": "Body"}
    ]


def test_a_long_subject_and_body_are_capped(route: list[tuple[str, str]], relay: FakeRelay) -> None:
    assert operator_email.send_sync("s" * 500, "b" * 9000)
    (post,) = relay.posts
    assert len(post["subject"]) == operator_email.SUBJECT_MAX
    assert len(post["body"]) == operator_email.BODY_MAX


@pytest.mark.parametrize(
    "answer",
    [
        lambda: httpx.Response(200, json={"status": "forbidden"}),
        lambda: httpx.Response(200, json={"status": "bad_request"}),
        lambda: httpx.Response(200, text="<html>Script function not found</html>"),
        lambda: httpx.Response(500, json={"status": "sent"}),
        lambda: httpx.Response(200, json=["sent"]),
    ],
)
def test_anything_but_a_sent_answer_is_not_a_send(
    route: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    answer: Callable[[], httpx.Response],
) -> None:
    fake = FakeRelay(answer)
    monkeypatch.setattr(
        operator_email,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(fake), follow_redirects=True),
    )
    logger = Mock()
    monkeypatch.setattr(operator_email, "log", logger)
    assert operator_email.send_sync("subject", "body") is False
    logged = repr(logger.mock_calls)
    assert SECRET not in logged and "AKfycb" not in logged


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout])
def test_an_unreachable_relay_returns_false_and_logs_only_the_error_class(
    route: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise failure(f"cannot reach {request.url}")

    monkeypatch.setattr(
        operator_email,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(broken), follow_redirects=True),
    )
    logger = Mock()
    monkeypatch.setattr(operator_email, "log", logger)
    assert operator_email.send_sync("subject", "body") is False
    logger.warning.assert_called_once_with("operator email failed", error=failure.__name__)
    logged = repr(logger.mock_calls)
    assert SECRET not in logged and "AKfycb" not in logged


def test_no_route_sends_nothing(no_route: list[tuple[str, str]], relay: FakeRelay) -> None:
    assert operator_email.send_sync("subject", "body") is False
    assert operator_email.notify("billing", "x", now=NOW) is False
    assert relay.posts == [] and no_route == []


def test_one_kind_emails_once_a_day_and_billing_every_six_hours(
    route: list[tuple[str, str]],
) -> None:
    assert operator_email.notify("job_outcome", "s", fingerprint="hive-poll", now=NOW)
    assert not operator_email.notify(
        "job_outcome", "s", fingerprint="hive-poll", now=NOW + timedelta(hours=23)
    )
    assert operator_email.notify("job_outcome", "s", fingerprint="wake-check", now=NOW)
    assert operator_email.notify(
        "job_outcome", "s", fingerprint="hive-poll", now=NOW + timedelta(days=1)
    )
    assert operator_email.notify("billing", "s", now=NOW)
    assert not operator_email.notify("billing", "s", now=NOW + timedelta(hours=5, minutes=59))
    assert operator_email.notify("billing", "s", now=NOW + timedelta(hours=6))
    assert len(route) == 5


def test_an_email_carries_only_codes_never_words_or_figures(
    route: list[tuple[str, str]],
) -> None:
    operator_email.notify(
        "generation_failure",
        "A paid generation failed",
        details={
            "reason": "timeout",
            "artifact": "brief",
            "subject_date": "2026-11-22",
            "mark_words": "my chest felt tight",
            "coach_summary": "summary",
            "profile_id": "4c20033a",
            "hrv_ms": 41,
        },
        now=NOW,
    )
    ((subject, body),) = route
    assert subject == "[Garmin Coach] A paid generation failed"
    assert "Reason: timeout" in body and "Artifact: brief" in body
    assert "Subject date: 2026-11-22" in body and "22 Nov 2026, 16:00 UTC" in body
    for private in ("chest", "summary", "4c20033a", "41"):
        assert private not in body


def test_admin_alert_emails_every_kind_except_information_and_the_pass_on(
    route: list[tuple[str, str]],
) -> None:
    logger = Mock()
    for kind in admin_alerts.KINDS:
        admin_alerts.admin_alert(logger, "event", kind=kind, reason="r")
    emailed = {subject for subject, _ in route}
    assert len(route) == len(admin_alerts.KINDS) - 2
    assert all(s.startswith("[Garmin Coach] ") for s in emailed)
    assert "[Garmin Coach] Anthropic refused a paid call: the credit or the spend limit" in emailed
    assert logger.error.call_count == len(admin_alerts.KINDS)
    assert set(admin_alerts.EMAIL_SUBJECTS) == admin_alerts.KINDS - {
        admin_alerts.KIND_COACH_FEEDBACK,
        admin_alerts.KIND_PLAN_ACCEPTED,
    }


def test_a_refused_login_emails_each_source_once(route: list[tuple[str, str]]) -> None:
    logger = Mock()
    admin_alerts._SOURCE_AUTH_ALERTED.clear()
    admin_alerts.source_auth_alert(logger, "garmin", today=NOW.date())
    admin_alerts.source_auth_alert(logger, "hive", today=NOW.date())
    admin_alerts.source_auth_alert(logger, "garmin", today=NOW.date())
    assert len(route) == 2
    assert {body.split("Source: ")[1].split("\n")[0] for _, body in route} == {"garmin", "hive"}
    admin_alerts._SOURCE_AUTH_ALERTED.clear()


def test_the_operator_log_routes_email_too(route: list[tuple[str, str]]) -> None:
    scheduler._log_backup_operator_alert("backup_failed", "backup_b2_http_503")
    scheduler._log_backup_operator_alert("backup_restore_drill_failed", "offsite_proof_unavailable")
    scheduler._log_operator_alert("metric_baselines_stale", "no_baseline_rows")
    scheduler._log_storage_operator_alert("warning", 400_000_000, 380_000_000)
    scheduler._log_egress_operator_alert("warning", 4_000_000_000)
    subjects = [subject for subject, _ in route]
    assert subjects == [
        "[Garmin Coach] Last night's backup failed",
        "[Garmin Coach] The offsite restore proof is missing or failed",
        "[Garmin Coach] Mark's personal baselines stopped refreshing",
        "[Garmin Coach] Database storage reached the warning stage of the free plan's 500 MB",
        "[Garmin Coach] Egress reached the warning stage of the free plan's monthly cap",
    ]
    assert "Reason: backup_b2_http_503" in route[0][1]


@pytest.mark.parametrize(
    ("result", "emailed"),
    [
        (JobResult.degraded("step_failures", failed=1), True),
        (JobResult.failed("unhandled_exception"), True),
        (JobResult.succeeded(), False),
        (JobResult.skipped("nothing_to_do"), False),
    ],
)
def test_a_degraded_or_failed_job_emails_once_a_day(
    route: list[tuple[str, str]], result: JobResult, emailed: bool
) -> None:
    job_runs._email_unhealthy_outcome("post-workout-backstop", result)
    job_runs._email_unhealthy_outcome("post-workout-backstop", result)
    assert len(route) == (1 if emailed else 0)
    if emailed:
        subject, body = route[0]
        assert subject == (
            f"[Garmin Coach] The post-workout-backstop job finished {result.status.value}"
        )
        assert f"Reason: {result.reason}" in body


@pytest.mark.parametrize("job", sorted(job_runs.SELF_ALERTING_JOBS))
def test_a_job_with_its_own_alert_is_not_emailed_twice(
    route: list[tuple[str, str]], job: str
) -> None:
    job_runs._email_unhealthy_outcome(job, JobResult.failed("backup_failed"))
    assert route == []


def _freshness() -> FreshnessReport:
    return FreshnessReport(checked=())


@pytest.mark.parametrize(
    ("job", "runs", "problem"),
    [
        (
            "post-workout-backstop",
            [("degraded", "step_failures")],
            "degraded:post-workout-backstop",
        ),
        ("coach-memory", [("degraded", "x"), ("succeeded", None)], "degraded:coach-memory"),
        ("backup", [("failed", "backup_failed")], "failing:backup"),
        ("hive-poll", [("degraded", "x"), ("succeeded", None)], None),
        ("hive-poll", [("degraded", "x"), ("failed", "y")], "degraded:hive-poll"),
        ("hive-poll", [("failed", "x"), ("failed", "y")], "failing:hive-poll"),
        ("backup", [("succeeded", None), ("failed", "backup_failed")], None),
    ],
)
def test_the_job_report_names_a_degraded_job(
    job: str, runs: list[tuple[str, str | None]], problem: str | None
) -> None:
    problems = watchdog_problems(freshness=_freshness(), recent_runs={job: runs}, brief_failures=[])
    assert problems == ((problem,) if problem else ())


def _toolbox(question: str = "Why didn't the app read yesterday's session?") -> CoachChatToolbox:
    return CoachChatToolbox(None, SimpleNamespace(id=uuid.uuid4()), question)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_pass_on_succeeds_only_after_the_relay_sends(
    route: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(operator_email, "send_pass_on", send)
    monkeypatch.setattr("src.services.brief_chat.admin_alert", Mock())
    toolbox = _toolbox()
    result = await toolbox.execute(
        tool_use_id="one",
        name="pass_to_craig",
        payload={"summary": "Mark asks why a session has no read."},
    )
    assert result.is_error is False and result.content.startswith("Alert succeeded.")
    send.assert_awaited_once_with("Mark asks why a session has no read.")
    assert toolbox.passed_to_craig


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [AsyncMock(return_value=False), AsyncMock(side_effect=OSError)])
async def test_a_pass_on_the_relay_did_not_send_is_never_claimed(
    route: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch, failure: AsyncMock
) -> None:
    monkeypatch.setattr(operator_email, "send_pass_on", failure)
    monkeypatch.setattr("src.services.brief_chat.admin_alert", Mock())
    toolbox = _toolbox()
    result = await toolbox.execute(
        tool_use_id="one", name="pass_to_craig", payload={"summary": "Mark reports a wrong call."}
    )
    assert result.is_error
    assert result.content == "Could not pass this to Craig. Do not claim it was sent."
    assert not toolbox.passed_to_craig


@pytest.mark.asyncio
async def test_without_the_relay_the_pass_on_is_unavailable_even_with_sentry(
    no_route: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sentry_dsn_backend", "https://public@o1.ingest.sentry.io/1")
    alert = Mock()
    monkeypatch.setattr("src.services.brief_chat.admin_alert", alert)
    result = await _toolbox().execute(
        tool_use_id="one", name="pass_to_craig", payload={"summary": "Mark reports a wrong call."}
    )
    assert result.is_error
    assert result.content == "Craig's alert route is unavailable. Do not claim it was sent."
    alert.assert_not_called()


@pytest.mark.asyncio
async def test_the_pass_on_email_carries_the_coachs_summary_not_marks_words(
    route: list[tuple[str, str]], relay: FakeRelay
) -> None:
    sent = await operator_email.send_pass_on("Mark asks why a session has no read.", now=NOW)
    assert sent is True
    (post,) = relay.posts
    assert post["subject"] == (
        "[Garmin Coach] Mark passed something on: Mark asks why a session has no read."
    )
    assert "Mark asks why a session has no read." in post["body"]
    assert "not Mark's own words" in post["body"]
