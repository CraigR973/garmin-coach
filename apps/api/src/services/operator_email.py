"""Operator alerts reach Craig by email (Batch 378, Decision #509).

Craig chose email on 22 Nov 2026: the app sends from a Gmail account used only by the
app (an app password in ``ALERT_EMAIL_APP_PASSWORD``) to his own address
(``ALERT_EMAIL_TO``). Before this, every operator alert went to Sentry, where no rule
told him, and the coach's "passed to Craig" reached nobody.

Two ways in:

* ``notify`` — fire and forget, for alerts raised anywhere (sync or async code). The send
  runs on a daemon thread, so a slow mail server never holds a job or a request, and one
  kind (with its fingerprint) emails at most once a day while it lasts; billing every six
  hours.
* ``send_pass_on`` — awaited, for the coach's pass-on, whose contract is that the coach
  says it passed something on only after the mail server accepted it.

Nothing here logs the password, either address or Mark's words. A pass-on carries the
coach's one-line summary, never Mark's own words (Craig's choice).
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Final

import structlog

from src.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

SUBJECT_PREFIX: Final = "[Garmin Coach]"
SUBJECT_MAX: Final = 150
SEND_TIMEOUT_S: Final = 20.0
#: How long one kind waits before it may email again while the problem lasts.
DEFAULT_REPEAT_AFTER: Final = timedelta(days=1)
REPEAT_AFTER: Final[Mapping[str, timedelta]] = {"billing": timedelta(hours=6)}
#: The only fields an alert email may carry: codes and dates, never words or figures.
DETAIL_FIELDS: Final = (
    "reason",
    "artifact",
    "subject_date",
    "source",
    "step",
    "stage",
    "job",
    "status",
)

_LAST_SENT: dict[tuple[str, str], datetime] = {}
_LOCK = threading.Lock()


def route_ready() -> bool:
    """Whether the email route is configured (all three settings present)."""

    return bool(
        settings.alert_email_from.strip()
        and settings.alert_email_app_password.strip()
        and settings.alert_email_to.strip()
    )


def _message(subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.alert_email_from.strip()
    message["To"] = settings.alert_email_to.strip()
    message["Subject"] = " ".join(subject.split())[:SUBJECT_MAX]
    message.set_content(body)
    return message


def send_sync(subject: str, body: str) -> bool:
    """Send one email; ``True`` only when the mail server accepted it for Craig."""

    if not route_ready():
        return False
    message = _message(subject, body)
    try:
        with smtplib.SMTP_SSL(
            settings.alert_email_smtp_host,
            settings.alert_email_smtp_port,
            timeout=SEND_TIMEOUT_S,
            context=ssl.create_default_context(),
        ) as smtp:
            smtp.login(settings.alert_email_from.strip(), settings.alert_email_app_password.strip())
            refused = smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        # The class only: a server's reply can echo the address or the login.
        log.warning("operator email failed", error=type(exc).__name__)
        return False
    if refused:
        log.warning("operator email refused by the server", refused=len(refused))
        return False
    log.info("operator email sent")
    return True


async def send(subject: str, body: str) -> bool:
    """``send_sync`` off the event loop."""

    return await asyncio.to_thread(send_sync, subject, body)


def _dispatch(subject: str, body: str) -> None:
    threading.Thread(
        target=send_sync, args=(subject, body), name="operator-email", daemon=True
    ).start()


def _when(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")


def notify(
    kind: str,
    summary: str,
    *,
    fingerprint: str = "",
    details: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> bool:
    """Email Craig about ``kind`` unless the same alert emailed within its repeat window.

    Returns whether a send was started. Never raises and never blocks the caller.
    """

    try:
        if not route_ready():
            return False
        moment = now or datetime.now(UTC)
        key = (kind, fingerprint)
        with _LOCK:
            last = _LAST_SENT.get(key)
            if last is not None and moment - last < REPEAT_AFTER.get(kind, DEFAULT_REPEAT_AFTER):
                return False
            _LAST_SENT[key] = moment
        lines = [summary, "", f"Kind: {kind}", f"When: {_when(moment)}"]
        for field in DETAIL_FIELDS:
            value = (details or {}).get(field)
            if value not in (None, ""):
                lines.append(f"{field.replace('_', ' ').capitalize()}: {value}")
        repeat = REPEAT_AFTER.get(kind, DEFAULT_REPEAT_AFTER)
        lines += [
            "",
            "Production's job report: "
            "https://api-production-e2bc7.up.railway.app/api/v1/health/jobs",
            f"This alert repeats at most every {_repeat_words(repeat)} while it lasts.",
        ]
        _dispatch(f"{SUBJECT_PREFIX} {summary}", "\n".join(lines))
        return True
    except Exception:
        log.exception("operator email could not be queued", kind=kind)
        return False


def _repeat_words(window: timedelta) -> str:
    hours = int(window.total_seconds() // 3600)
    return "day" if hours >= 24 else f"{hours} hours"


async def send_pass_on(coach_summary: str, *, now: datetime | None = None) -> bool:
    """Email the coach's one-line summary of what Mark asked it to pass on."""

    moment = now or datetime.now(UTC)
    body = "\n".join(
        [
            "The coach passed this on from Mark:",
            "",
            coach_summary,
            "",
            f"When: {_when(moment)}",
            "This is the coach's summary, not Mark's own words. His message is in the "
            "app's coach chat.",
        ]
    )
    return await send(f"{SUBJECT_PREFIX} Mark passed something on: {coach_summary}", body)


def reset_for_tests() -> None:
    with _LOCK:
        _LAST_SENT.clear()
