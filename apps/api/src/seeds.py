"""Small admin-only seed helpers.

These functions are intentionally boring: private users are created directly by
an operator, not through a public signup flow.
"""

import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import hash_pin
from src.database import AsyncSessionLocal
from src.models.profile import PlayerRole, Profile

MARK_DISPLAY_NAME = "Mark"
MARK_TIMEZONE = "Europe/London"
MARK_GARMIN_USER_PROFILE_PK = 9048542
MARK_HIVE_HOME_ID = "aa1fbb37-6b65-4622-b609-5d75534fafd3"
KILMARNOCK_LATITUDE = 55.6045
KILMARNOCK_LONGITUDE = -4.5249


def _validate_pin(pin: str) -> None:
    if len(pin) != 4 or not pin.isdecimal():
        raise ValueError("MARK_PIN must be exactly four digits")


def build_mark_profile(pin: str) -> Profile:
    _validate_pin(pin)
    return Profile(
        display_name=MARK_DISPLAY_NAME,
        pin_hash=hash_pin(pin),
        role=PlayerRole.admin,
        timezone=MARK_TIMEZONE,
        garmin_user_profile_pk=MARK_GARMIN_USER_PROFILE_PK,
        hive_home_id=MARK_HIVE_HOME_ID,
        latitude=KILMARNOCK_LATITUDE,
        longitude=KILMARNOCK_LONGITUDE,
        is_active=True,
    )


async def seed_mark_profile(db: AsyncSession, pin: str) -> Profile:
    """Create or update Mark's private admin profile."""

    _validate_pin(pin)
    result = await db.execute(
        select(Profile).where(
            Profile.display_name == MARK_DISPLAY_NAME,
            Profile.deleted_at.is_(None),
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = build_mark_profile(pin)
        db.add(profile)
    else:
        profile.pin_hash = hash_pin(pin)
        profile.role = PlayerRole.admin
        profile.timezone = MARK_TIMEZONE
        profile.garmin_user_profile_pk = MARK_GARMIN_USER_PROFILE_PK
        profile.hive_home_id = MARK_HIVE_HOME_ID
        profile.latitude = KILMARNOCK_LATITUDE
        profile.longitude = KILMARNOCK_LONGITUDE
        profile.is_active = True
    await db.commit()
    await db.refresh(profile)
    return profile


async def _main() -> None:
    pin = os.environ.get("MARK_PIN")
    if pin is None:
        raise SystemExit("Set MARK_PIN to Mark's four-digit PIN before running this seed.")

    async with AsyncSessionLocal() as db:
        profile = await seed_mark_profile(db, pin)
        print(f"Seeded profile {profile.display_name} ({profile.id})")


if __name__ == "__main__":
    asyncio.run(_main())
