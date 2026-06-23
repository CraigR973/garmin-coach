"""JWT creation/verification, bcrypt helpers, and FastAPI auth dependencies."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.models.profile import Profile, UserRole
from src.models.refresh_token import RefreshToken

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)

ACCESS_TTL = timedelta(hours=24)
REFRESH_TTL = timedelta(days=30)
PIN_RESET_TTL = timedelta(minutes=30)
# Passwordless device-token auth (additive — runs alongside PIN login).
ACTIVATION_TTL = timedelta(minutes=30)
DEVICE_TOKEN_TTL = timedelta(days=365)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Bcrypt helpers
# ---------------------------------------------------------------------------


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(pin: str, hashed: str) -> bool:
    return bcrypt.checkpw(pin.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def create_access_token(user_id: uuid.UUID, role: UserRole) -> str:
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "exp": _now() + ACCESS_TTL,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.jwt_access_secret, algorithm="HS256")


def create_refresh_token(user_id: uuid.UUID, token_record_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "jti": str(token_record_id),
        "exp": _now() + REFRESH_TTL,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.jwt_refresh_secret, algorithm="HS256")


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw token string — stored in refresh_tokens.token_hash."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_opaque_token() -> str:
    """32-byte URL-safe random token (used as the raw refresh token)."""
    return secrets.token_urlsafe(32)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_access_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def decode_refresh_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_refresh_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )


def create_pin_reset_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "scope": "pin_reset",
        "exp": _now() + PIN_RESET_TTL,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.jwt_access_secret, algorithm="HS256")


def decode_pin_reset_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_access_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset link expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
    if payload.get("scope") != "pin_reset":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
    return payload


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
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Profile:
    token = credentials.credentials

    # Path 1: a PIN-login JWT access token. A device token is opaque (not a
    # JWT), so jwt.decode raises InvalidTokenError and we fall through to path 2.
    try:
        payload: dict[str, Any] | None = jwt.decode(
            token, settings.jwt_access_secret, algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError:
        # A genuine but expired JWT — tell the client to refresh; do not
        # reinterpret it as a device token.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        payload = None

    if payload is not None:
        user_id = uuid.UUID(payload["sub"])
        result = await db.execute(
            select(Profile).where(
                Profile.id == user_id,
                Profile.deleted_at.is_(None),
                Profile.is_active.is_(True),
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user

    # Path 2: a passwordless device token (opaque, stored hashed in refresh_tokens).
    device_user = await _resolve_device_token(token, db)
    if device_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return device_user


async def require_admin(
    user: Annotated[Profile, Depends(get_current_user)],
) -> Profile:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


CurrentUser = Annotated[Profile, Depends(get_current_user)]
AdminUser = Annotated[Profile, Depends(require_admin)]
