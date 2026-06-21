"""Endpoints scoped to the authenticated user (/api/v1/me)."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.auth import CurrentUser

router = APIRouter(prefix="/api/v1/me", tags=["me"])


class ProfileOut(BaseModel):
    id: str
    display_name: str
    role: str
    timezone: str


@router.get("/profile", response_model=ProfileOut)
async def get_profile(user: CurrentUser) -> ProfileOut:
    """Return the authenticated user's basic profile."""
    return ProfileOut(
        id=str(user.id),
        display_name=user.display_name,
        role=user.role.value,
        timezone=user.timezone,
    )
