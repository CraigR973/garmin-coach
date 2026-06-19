"""Email delivery via Resend SDK.

All send functions are synchronous (Resend SDK is sync) and designed to be
called from FastAPI BackgroundTasks — failures are logged, never raised.

When RESEND_API_KEY is empty (local dev without email configured) the
functions log a warning and return without sending.
"""

import structlog

from src.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _send(*, to: str, subject: str, html: str) -> None:
    if not settings.resend_api_key:
        log.warning("resend_api_key not configured — skipping email", to=to, subject=subject)
        return
    try:
        import resend

        resend.api_key = settings.resend_api_key
        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html,
            }
        )
        log.info("email sent", to=to, subject=subject)
    except Exception:
        log.exception("failed to send email", to=to, subject=subject)


def send_verification_email(email: str, token: str, frontend_origin: str) -> None:
    verify_url = f"{frontend_origin}/verify-email/{token}"
    html = (
        "<p>Welcome to Garmin Coach!</p>"
        f"<p><a href='{verify_url}'>Verify your email address</a>"
        " to unlock self-service PIN reset.</p>"
        "<p>This link expires in 24 hours.</p>"
        f"<p>Or copy this URL into your browser:<br>{verify_url}</p>"
    )
    _send(to=email, subject="Verify your email — Garmin Coach", html=html)


def send_pin_reset_email(email: str, token: str, frontend_origin: str) -> None:
    reset_url = f"{frontend_origin}/reset-pin/{token}"
    html = (
        "<p>You requested a PIN reset for Garmin Coach.</p>"
        f"<p><a href='{reset_url}'>Reset your PIN</a> — this link expires in 30 minutes.</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
        f"<p>Or copy this URL into your browser:<br>{reset_url}</p>"
    )
    _send(to=email, subject="Reset your PIN — Garmin Coach", html=html)
