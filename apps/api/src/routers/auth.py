"""Passwordless device activation, identity, and revocation endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    DEVICE_TOKEN_TTL,
    CurrentUser,
    generate_opaque_token,
    hash_token,
)
from src.database import get_db
from src.models.profile import Profile
from src.models.refresh_token import RefreshToken
from src.rate_limit import limiter

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=True)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PlayerInfo(BaseModel):
    id: str
    display_name: str
    role: str
    timezone: str


class ActivateRequest(BaseModel):
    code: str = Field(min_length=10, max_length=128)


class ActivateResponse(BaseModel):
    device_token: str
    player: PlayerInfo


class ProfileUpdateRequest(BaseModel):
    timezone: str = Field(..., min_length=1, max_length=64)


@router.post("/activate", response_model=ActivateResponse)
@limiter.limit("10/hour")
async def activate(
    request: Request,
    body: ActivateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ActivateResponse:
    """Exchange a single-use activation code for a long-lived device token."""
    code_record = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(body.code),
                RefreshToken.purpose == "activation",
                RefreshToken.used_at.is_(None),
                RefreshToken.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if code_record is None or code_record.expires_at < _now():
        log.info("activation failed — invalid or expired code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired activation code",
        )

    user = (
        await db.execute(
            select(Profile).where(
                Profile.id == code_record.user_id,
                Profile.deleted_at.is_(None),
                Profile.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired activation code",
        )

    code_record.used_at = _now()
    raw_token = generate_opaque_token()
    device_hint = request.headers.get("User-Agent", "")[:100]
    db.add(
        RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_token(raw_token),
            purpose="device",
            device_hint=device_hint,
            expires_at=_now() + DEVICE_TOKEN_TTL,
        )
    )
    await db.commit()

    log.info("device activated", user_id=str(user.id))
    return ActivateResponse(
        device_token=raw_token,
        player=PlayerInfo(
            id=str(user.id),
            display_name=user.display_name,
            role=user.role.value,
            timezone=user.timezone,
        ),
    )


@router.post("/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_current_device(
    user: CurrentUser,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoke the opaque device credential used for this request."""
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.token_hash == hash_token(credentials.credentials),
            RefreshToken.purpose == "device",
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    await db.commit()
    log.info("device token revoked", user_id=str(user.id))


@router.get("/me", response_model=PlayerInfo)
async def me(user: CurrentUser) -> PlayerInfo:
    return PlayerInfo(
        id=str(user.id),
        display_name=user.display_name,
        role=user.role.value,
        timezone=user.timezone,
    )


@router.patch("/me", response_model=PlayerInfo)
async def update_profile(
    body: ProfileUpdateRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
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
