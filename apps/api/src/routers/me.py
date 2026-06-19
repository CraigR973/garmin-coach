"""Endpoints scoped to the authenticated player (/api/v1/me)."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.auth import CurrentPlayer

router = APIRouter(prefix="/api/v1/me", tags=["me"])


class ProfileOut(BaseModel):
    id: str
    display_name: str
    role: str
    timezone: str


@router.get("/profile", response_model=ProfileOut)
async def get_profile(player: CurrentPlayer) -> ProfileOut:
    """Return the authenticated player's basic profile."""
    return ProfileOut(
        id=str(player.id),
        display_name=player.display_name,
        role=player.role.value,
        timezone=player.timezone,
    )
