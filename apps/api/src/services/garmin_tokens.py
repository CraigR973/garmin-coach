"""Keep each Garmin login garminconnect renews (Batch 365.3, Decision #462).

garminconnect refreshes Garmin's token itself: its access token lives about a day, and
``login`` refreshes it from the refresh token when it is close to expiry. The app threw
every new token away. Each poll built a new client and logged in from the deployed
``GARMIN_TOKENSTORE_B64``, so on 1 Nov 2026 it was still refreshing with 21 Jun's token
when Garmin refused it, and any token Garmin rotates would have been lost the same way.

So the newest token is remembered in the process (:func:`remember`, called by the client
after every successful login and fetch) and kept in ``provider_tokens``
(:func:`persist`), encrypted. The next process starts from it (:func:`restore`). The
deployed variable stays the fallback: the client tries it whenever the kept token is
refused, and re-minting the variable makes the kept token unreadable, because its key
comes from the variable. A database read alone therefore never yields a usable token.

The variable is never written: changing a Railway variable is Craig's.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Final

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.operations import ProviderToken

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

PROVIDER_GARMIN: Final = "garmin"

_lock = threading.Lock()
_latest: str | None = None
_persisted: str | None = None
_restored = False


def _deployed() -> str:
    return settings.garmin_tokenstore_b64 or ""


def fingerprint(deployed: str) -> str:
    """Names the deployed variable a kept token was keyed from, never the token."""

    return hashlib.sha256(b"garmin-token-source:" + deployed.encode()).hexdigest()[:32]


def _fernet(deployed: str) -> Fernet:
    key = hashlib.sha256(b"garmin-token-store:" + deployed.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _usable(tokens: str | None) -> bool:
    """A garminconnect token store with a refresh token in it."""

    if not tokens:
        return False
    try:
        data = json.loads(tokens)
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("di_refresh_token"))


def current() -> str | None:
    """The newest renewed token this process has seen, if any."""

    with _lock:
        return _latest


def remember(tokens: str | None) -> None:
    """Hold the client's tokens after a successful login or fetch."""

    global _latest
    if not _usable(tokens):
        return
    with _lock:
        _latest = tokens


def forget(tokens: str | None) -> None:
    """Drop a kept token Garmin refused, so the deployed variable is tried next."""

    global _latest
    with _lock:
        if tokens is not None and _latest == tokens:
            _latest = None


async def restore(session: AsyncSession) -> bool:
    """Start from the kept token, once per process. True when one was restored."""

    global _latest, _persisted, _restored
    if _restored:
        return False
    _restored = True
    deployed = _deployed()
    if not deployed:
        return False
    row = await session.get(ProviderToken, PROVIDER_GARMIN)
    if row is None or row.source_fingerprint != fingerprint(deployed):
        # Nothing kept, or kept under an earlier variable: the variable wins.
        return False
    try:
        tokens = _fernet(deployed).decrypt(row.ciphertext.encode()).decode()
    except InvalidToken:
        log.warning("kept garmin token unreadable", reason="invalid_token")
        return False
    if not _usable(tokens):
        return False
    with _lock:
        _latest = tokens
        _persisted = tokens
    log.info("garmin token restored", source="provider_tokens")
    return True


async def persist(session: AsyncSession) -> bool:
    """Keep the newest renewed token, encrypted, when it changed. True when written.

    Commits on its own: callers run it after their own work has committed.
    """

    global _persisted
    deployed = _deployed()
    tokens = current()
    if not deployed or tokens is None or tokens == _persisted:
        return False
    row = await session.get(ProviderToken, PROVIDER_GARMIN)
    if row is None:
        row = ProviderToken(provider=PROVIDER_GARMIN)
        session.add(row)
    row.ciphertext = _fernet(deployed).encrypt(tokens.encode()).decode()
    row.source_fingerprint = fingerprint(deployed)
    row.updated_at_utc = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    with _lock:
        _persisted = tokens
    log.info("garmin token kept", source="provider_tokens")
    return True


async def restore_safely(session: AsyncSession) -> None:
    """:func:`restore`, which never fails a poll; the variable is the fallback."""

    try:
        await restore(session)
    except Exception:
        await session.rollback()
        log.warning("kept garmin token not restored", reason="restore_failed")


async def persist_safely(session: AsyncSession) -> None:
    """:func:`persist`, which never fails a poll; the next poll tries again."""

    try:
        await persist(session)
    except Exception:
        await session.rollback()
        log.warning("renewed garmin token not kept", reason="persist_failed")


def _reset_for_tests() -> None:
    global _latest, _persisted, _restored
    with _lock:
        _latest = None
        _persisted = None
        _restored = False
