"""Passwordless device-token helpers and FastAPI auth dependencies."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.profile import Profile, UserRole
from src.models.refresh_token import RefreshToken

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)

ACTIVATION_TTL = timedelta(minutes=30)
DEVICE_TOKEN_TTL = timedelta(days=365)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw token string — stored in refresh_tokens.token_hash."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_opaque_token() -> str:
    """Return a 256-bit URL-safe bearer token or one-time activation code."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def _resolve_device_token(raw_token: str, db: AsyncSession) -> Profile | None:
    """Resolve an opaque device token to its active Profile, or None.

    Matches an unrevoked, unexpired ``refresh_tokens`` row with ``purpose='device'``
    by SHA-256 hash and joins to an active, non-deleted profile.
    """
    result = await db.execute(
        select(Profile)
        .join(RefreshToken, RefreshToken.user_id == Profile.id)
        .where(
            RefreshToken.token_hash == hash_token(raw_token),
            RefreshToken.purpose == "device",
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > _now(),
            Profile.deleted_at.is_(None),
            Profile.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Profile:
    token = credentials.credentials

    user = await _resolve_device_token(token, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    request.state.current_user_id = str(user.id)
    return user


async def require_admin(
    user: Annotated[Profile, Depends(get_current_user)],
) -> Profile:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


CurrentUser = Annotated[Profile, Depends(get_current_user)]
AdminUser = Annotated[Profile, Depends(require_admin)]
