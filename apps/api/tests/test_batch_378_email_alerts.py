"""Batch 378 (Decision #509): every alert reaches Craig by email.

Craig chose email on 22 Nov 2026, sent from a Gmail account used only by the app to his
own address. Before this, alerts went to Sentry, where no rule told him: on 22 Nov a
pass-on from Mark, an overnight Anthropic credit outage and a failed backup all reached
nobody.
"""

from __future__ import annotations

import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from src import scheduler
from src.config import settings
from src.services import admin_alerts, job_runs, operator_email
from src.services.brief_chat import CoachChatToolbox
from src.services.job_ledger_freshness import FreshnessReport, watchdog_problems
from src.services.job_runs import JobResult

NOW = datetime(2026, 11, 22, 16, 0, tzinfo=UTC)
APP_PASSWORD = "abcd efgh ijkl mnop"


@pytest.fixture
def route(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """A configured route whose sends are captured instead of leaving the process."""

    monkeypatch.setattr(settings, "alert_email_from", "app-sender@example.com")
    monkeypatch.setattr(settings, "alert_email_app_password", APP_PASSWORD)
    monkeypatch.setattr(settings, "alert_email_to", "craig@example.com")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        operator_email, "_dispatch", lambda subject, body: sent.append((subject, body))
    )
    operator_email.reset_for_tests()
    yield sent
    operator_email.reset_for_tests()


@pytest.fixture
def no_route(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    for name in ("alert_email_from", "alert_email_app_password", "alert_email_to"):
        monkeypatch.setattr(settings, name, "")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        operator_email, "_dispatch", lambda subject, body: sent.append((subject, body))
    )
    operator_email.reset_for_tests()
    return sent


class FakeSMTP:
    """Stands in for ``smtplib.SMTP_SSL``; records what the app asked of the server."""

    instances: list[FakeSMTP] = []
    fail_with: Exception | None = None
    refuse: dict[str, Any] = {}

    def __init__(self, host: str, port: int, *, timeout: float, context: Any) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.logins: list[tuple[str, str]] = []
        self.messages: list[Any] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with
        self.logins.append((user, password))

    def send_message(self, message: Any) -> dict[str, Any]:
        self.messages.append(message)
        return FakeSMTP.refuse


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances, FakeSMTP.fail_with, FakeSMTP.refuse = [], None, {}
    monkeypatch.setattr(operator_email.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_the_route_needs_all_three_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("alert_email_from", "alert_email_app_password", "alert_email_to"):
        monkeypatch.setattr(settings, name, "set")
    assert operator_email.route_ready()
    for name in ("alert_email_from", "alert_email_app_password", "alert_email_to"):
        monkeypatch.setattr(settings, name, " ")
        assert not operator_email.route_ready()
        monkeypatch.setattr(settings, name, "set")


def test_a_send_logs_in_with_the_app_password_and_mails_craig(
    route: list[tuple[str, str]], smtp: type[FakeSMTP]
) -> None:
    assert operator_email.send_sync("[Garmin Coach] Last night's backup failed", "Body") is True
    (server,) = smtp.instances
    assert (server.host, server.port, server.timeout) == ("smtp.gmail.com", 465, 20.0)
    assert server.logins == [("app-sender@example.com", APP_PASSWORD)]
    (message,) = server.messages
    assert message["From"] == "app-sender@example.com"
    assert message["To"] == "craig@example.com"
    assert message["Subject"] == "[Garmin Coach] Last night's backup failed"
    assert message.get_content().strip() == "Body"


@pytest.mark.parametrize(
    "failure",
    [smtplib.SMTPAuthenticationError(535, b"bad"), TimeoutError("slow"), OSError("down")],
)
def test_a_failed_send_returns_false_and_logs_only_the_error_class(
    route: list[tuple[str, str]],
    smtp: type[FakeSMTP],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    smtp.fail_with = failure
    logger = Mock()
    monkeypatch.setattr(operator_email, "log", logger)
    assert operator_email.send_sync("subject", "body") is False
    logger.warning.assert_called_once_with("operator email failed", error=type(failure).__name__)
    logged = repr(logger.mock_calls)
    assert APP_PASSWORD not in logged and "example.com" not in logged


def test_a_refused_recipient_is_not_a_send(
    route: list[tuple[str, str]], smtp: type[FakeSMTP]
) -> None:
    smtp.refuse = {"craig@example.com": (550, b"no")}
    assert operator_email.send_sync("subject", "body") is False


def test_no_route_sends_nothing(no_route: list[tuple[str, str]], smtp: type[FakeSMTP]) -> None:
    assert operator_email.send_sync("subject", "body") is False
    assert operator_email.notify("billing", "x", now=NOW) is False
    assert smtp.instances == [] and no_route == []


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
async def test_the_pass_on_succeeds_only_after_the_mail_server_accepts(
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
async def test_a_pass_on_the_mail_server_did_not_take_is_never_claimed(
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
async def test_without_the_email_route_the_pass_on_is_unavailable_even_with_sentry(
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
    route: list[tuple[str, str]], smtp: type[FakeSMTP]
) -> None:
    sent = await operator_email.send_pass_on("Mark asks why a session has no read.", now=NOW)
    assert sent is True
    (message,) = smtp.instances[0].messages
    assert message["Subject"] == (
        "[Garmin Coach] Mark passed something on: Mark asks why a session has no read."
    )
    body = message.get_content()
    assert "Mark asks why a session has no read." in body
    assert "not Mark's own words" in body
