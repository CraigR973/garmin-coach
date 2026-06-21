"""Auth endpoints: login, refresh, logout, me, pin change, pin reset."""

import uuid
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import bcrypt as _bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    REFRESH_TTL,
    CurrentUser,
    create_access_token,
    create_pin_reset_token,
    create_refresh_token,
    decode_pin_reset_token,
    decode_refresh_token,
    hash_pin,
    hash_token,
    verify_pin,
)
from src.database import get_db
from src.models.profile import Profile
from src.models.refresh_token import RefreshToken
from src.rate_limit import limiter, login_key, per_user_key, refresh_token_key

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Pre-computed dummy hash for constant-time login response when user not found.
_DUMMY_HASH: str = _bcrypt.hashpw(b"dummy-timing-guard", _bcrypt.gensalt()).decode()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    display_name: str
    pin: str = Field(pattern=r"^\d{4}$")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    player: "PlayerInfo"


class PlayerInfo(BaseModel):
    id: str
    display_name: str
    role: str
    timezone: str


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ChangePinRequest(BaseModel):
    current_pin: str = Field(pattern=r"^\d{4}$")
    new_pin: str = Field(pattern=r"^\d{4}$")


class PinResetRequestBody(BaseModel):
    display_name: str


class PinResetConfirm(BaseModel):
    token: str
    new_pin: str = Field(pattern=r"^\d{4}$")


_PIN_RESET_GENERIC = {
    "message": "If that display name is registered, an admin will be notified to reset your PIN."
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _issue_token_pair(
    user: Profile,
    db: AsyncSession,
    device_hint: str | None = None,
) -> tuple[str, str]:
    """Create a new refresh token record and return (access_token, refresh_token)."""
    record_id = uuid.uuid4()
    refresh_jwt = create_refresh_token(user.id, record_id)

    token_record = RefreshToken(
        id=record_id,
        user_id=user.id,
        token_hash=hash_token(refresh_jwt),
        device_hint=device_hint,
        expires_at=_now() + REFRESH_TTL,
    )
    db.add(token_record)
    await db.commit()

    access = create_access_token(user.id, user.role)
    return access, refresh_jwt


# ---------------------------------------------------------------------------
# Endpoints — login / refresh / logout
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/15 minutes", key_func=login_key)
async def login(
    request: Request,
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    result = await db.execute(
        select(Profile).where(
            Profile.display_name == body.display_name,
            Profile.deleted_at.is_(None),
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        verify_pin(body.pin, _DUMMY_HASH)
        log.info("login failed — user not found")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_pin(body.pin, user.pin_hash):
        log.info("login failed — wrong pin", user_id=str(user.id))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    await db.commit()
    await db.refresh(user)

    device_hint = request.headers.get("User-Agent", "")[:100]
    access, refresh = await _issue_token_pair(user, db, device_hint)

    log.info(
        "login successful",
        user_id=str(user.id),
        role=user.role.value,
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        player=PlayerInfo(
            id=str(user.id),
            display_name=user.display_name,
            role=user.role.value,
            timezone=user.timezone,
        ),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
@limiter.limit("60/hour", key_func=refresh_token_key)
async def refresh(
    request: Request,
    body: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccessTokenResponse:
    payload = decode_refresh_token(body.refresh_token)
    jti = uuid.UUID(payload["jti"])
    user_id = uuid.UUID(payload["sub"])

    token_hash = hash_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.id == jti,
            RefreshToken.user_id == user_id,
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
    )
    token_record = result.scalar_one_or_none()
    if token_record is None or token_record.expires_at < _now():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    token_record.revoked_at = _now()
    await db.commit()

    user_result = await db.execute(
        select(Profile).where(Profile.id == user_id, Profile.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    device_hint = token_record.device_hint
    access, new_refresh = await _issue_token_pair(user, db, device_hint)

    log.info("tokens refreshed", user_id=str(user_id))
    return AccessTokenResponse(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        payload = decode_refresh_token(body.refresh_token)
        jti = uuid.UUID(payload["jti"])
        token_hash = hash_token(body.refresh_token)
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.id == jti,
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
        )
        token_record = result.scalar_one_or_none()
        if token_record:
            token_record.revoked_at = _now()
            await db.commit()
            log.info("logout — token revoked", jti=str(jti))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Endpoints — me, pin change, pin reset
# ---------------------------------------------------------------------------


@router.get("/me", response_model=PlayerInfo)
async def me(user: CurrentUser) -> PlayerInfo:
    return PlayerInfo(
        id=str(user.id),
        display_name=user.display_name,
        role=user.role.value,
        timezone=user.timezone,
    )


class ProfileUpdateRequest(BaseModel):
    timezone: str = Field(..., min_length=1, max_length=64)


@router.patch("/me", response_model=PlayerInfo)
async def update_profile(
    body: ProfileUpdateRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PlayerInfo:
    """Update the authenticated user's mutable profile fields."""
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid IANA timezone identifier",
        )
    await db.execute(update(Profile).where(Profile.id == user.id).values(timezone=body.timezone))
    await db.commit()
    return PlayerInfo(
        id=str(user.id),
        display_name=user.display_name,
        role=user.role.value,
        timezone=body.timezone,
    )


@router.put("/me/pin", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/hour", key_func=per_user_key)
async def change_pin(
    request: Request,
    body: ChangePinRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if not verify_pin(body.current_pin, user.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current PIN is incorrect"
        )
    user.pin_hash = hash_pin(body.new_pin)
    await db.commit()
    log.info("pin changed", user_id=str(user.id))


@router.post("/pin/reset-request")
@limiter.limit("3/hour")
async def pin_reset_request(
    request: Request,
    body: PinResetRequestBody,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    result = await db.execute(
        select(Profile).where(
            Profile.display_name == body.display_name,
            Profile.deleted_at.is_(None),
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        return _PIN_RESET_GENERIC

    # Admin-only reset: log the token for the admin to use manually.
    reset_token = create_pin_reset_token(user.id)
    log.info(
        "pin reset requested — token generated for admin",
        user_id=str(user.id),
        token=reset_token,
    )
    return _PIN_RESET_GENERIC


@router.post("/pin/reset", status_code=status.HTTP_204_NO_CONTENT)
async def pin_reset(
    body: PinResetConfirm,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    payload = decode_pin_reset_token(body.token)
    user_id = uuid.UUID(payload["sub"])

    result = await db.execute(
        select(Profile).where(Profile.id == user_id, Profile.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    user.pin_hash = hash_pin(body.new_pin)
    user.failed_login_count = 0
    user.locked_until = None

    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
    log.info("pin reset complete — all tokens revoked", user_id=str(user_id))
