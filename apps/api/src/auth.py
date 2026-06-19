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
from src.models.profile import PlayerRole, Profile

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)

ACCESS_TTL = timedelta(hours=24)
REFRESH_TTL = timedelta(days=30)
EMAIL_VERIFY_TTL = timedelta(hours=24)
PIN_RESET_TTL = timedelta(minutes=30)
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


def create_access_token(player_id: uuid.UUID, role: PlayerRole) -> str:
    payload = {
        "sub": str(player_id),
        "role": role.value,
        "exp": _now() + ACCESS_TTL,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.jwt_access_secret, algorithm="HS256")


def create_refresh_token(player_id: uuid.UUID, token_record_id: uuid.UUID) -> str:
    payload = {
        "sub": str(player_id),
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


def create_email_verify_token(email: str) -> str:
    payload = {
        "sub": email.lower(),
        "scope": "email_verify",
        "exp": _now() + EMAIL_VERIFY_TTL,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.jwt_access_secret, algorithm="HS256")


def decode_email_verify_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_access_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Verification link expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
    if payload.get("scope") != "email_verify":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
    return payload


def create_pin_reset_token(player_id: uuid.UUID) -> str:
    payload = {
        "sub": str(player_id),
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


async def get_current_player(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Profile:
    payload = decode_access_token(credentials.credentials)
    player_id = uuid.UUID(payload["sub"])

    result = await db.execute(
        select(Profile).where(
            Profile.id == player_id,
            Profile.deleted_at.is_(None),
            Profile.is_active.is_(True),
        )
    )
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Player not found")
    return player


async def require_admin(
    player: Annotated[Profile, Depends(get_current_player)],
) -> Profile:
    if player.role != PlayerRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return player


CurrentPlayer = Annotated[Profile, Depends(get_current_player)]
AdminPlayer = Annotated[Profile, Depends(require_admin)]
