"""Operator alerts reach Craig by email (Batch 378, Decisions #509 and #511).

Craig chose email on 22 Nov 2026, sent from a Gmail account used only by the app to his
own address. Railway's Hobby plan blocks outbound SMTP (24 Nov: the first test timed out
on port 465), so the app posts over HTTPS to a Google Apps Script web app inside that
Gmail account (``docs/runbooks/gmail-alert-relay.md``). The script checks a shared secret
and sends only to the one address held in its own properties, so even a stolen secret
cannot send mail anywhere else. Before this, every operator alert went to Sentry, where
no rule told him, and the coach's "passed to Craig" reached nobody.

Two ways in:

* ``notify`` — fire and forget, for alerts raised anywhere (sync or async code). The send
  runs on a daemon thread, so a slow relay never holds a job or a request, and one kind
  (with its fingerprint) emails at most once a day while it lasts; billing every six
  hours.
* ``send_pass_on`` — awaited, for the coach's pass-on, whose contract is that the coach
  says it passed something on only after the relay reports the email sent.

Nothing here logs the relay URL, the secret or Mark's words. A pass-on carries the
coach's one-line summary, never Mark's own words (Craig's choice).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit

import httpx
import structlog

from src.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

SUBJECT_PREFIX: Final = "[Garmin Coach]"
SUBJECT_MAX: Final = 150
BODY_MAX: Final = 5000
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


def _relay_url() -> str | None:
    """The configured web-app URL, only if it is an Apps Script ``/exec`` URL."""

    url = settings.alert_email_relay_url.strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "script.google.com"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/macros/s/")
        or not parsed.path.endswith("/exec")
    ):
        return None
    return url


def route_ready() -> bool:
    """Whether the relay is configured: an Apps Script URL and a secret."""

    return bool(_relay_url() and settings.alert_email_relay_secret.strip())


def _client() -> httpx.Client:
    # Apps Script answers a POST with a redirect to the script's output.
    return httpx.Client(timeout=SEND_TIMEOUT_S, follow_redirects=True)


def send_sync(subject: str, body: str) -> bool:
    """Send one email; ``True`` only when the relay reports it sent."""

    url = _relay_url()
    secret = settings.alert_email_relay_secret.strip()
    if url is None or not secret:
        return False
    payload = {
        "secret": secret,
        "subject": " ".join(subject.split())[:SUBJECT_MAX],
        "body": body[:BODY_MAX],
    }
    try:
        with _client() as client:
            response = client.post(url, json=payload)
    except httpx.HTTPError as exc:
        # The class only: an error's text can carry the URL.
        log.warning("operator email failed", error=type(exc).__name__)
        return False
    relay_status: object = None
    if response.status_code == 200:
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if isinstance(answer, dict):
            relay_status = answer.get("status")
    if relay_status != "sent":
        log.warning(
            "operator email not sent by the relay",
            status_code=response.status_code,
            relay_status=relay_status if isinstance(relay_status, str) else None,
        )
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


def _repeat_words(window: timedelta) -> str:
    hours = int(window.total_seconds() // 3600)
    return "day" if hours >= 24 else f"{hours} hours"


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
        window = REPEAT_AFTER.get(kind, DEFAULT_REPEAT_AFTER)
        with _LOCK:
            last = _LAST_SENT.get(key)
            if last is not None and moment - last < window:
                return False
            _LAST_SENT[key] = moment
        lines = [summary, "", f"Kind: {kind}", f"When: {_when(moment)}"]
        for field in DETAIL_FIELDS:
            value = (details or {}).get(field)
            if value not in (None, ""):
                lines.append(f"{field.replace('_', ' ').capitalize()}: {value}")
        lines += [
            "",
            "Production's job report: "
            "https://api-production-e2bc7.up.railway.app/api/v1/health/jobs",
            f"This alert repeats at most every {_repeat_words(window)} while it lasts.",
        ]
        _dispatch(f"{SUBJECT_PREFIX} {summary}", "\n".join(lines))
        return True
    except Exception:
        log.exception("operator email could not be queued", kind=kind)
        return False


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
