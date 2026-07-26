"""Small admin-only seed helpers.

These functions are intentionally boring: private users are created directly by
an operator, not through a public signup flow.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models.profile import Profile, UserRole

MARK_DISPLAY_NAME = "Mark"
MARK_TIMEZONE = "Europe/London"
MARK_GARMIN_USER_PROFILE_PK = 9048542
MARK_HIVE_HOME_ID = "aa1fbb37-6b65-4622-b609-5d75534fafd3"
KILMARNOCK_LATITUDE = 55.6045
KILMARNOCK_LONGITUDE = -4.5249


def build_mark_profile() -> Profile:
    return Profile(
        display_name=MARK_DISPLAY_NAME,
        role=UserRole.admin,
        timezone=MARK_TIMEZONE,
        garmin_user_profile_pk=MARK_GARMIN_USER_PROFILE_PK,
        hive_home_id=MARK_HIVE_HOME_ID,
        latitude=KILMARNOCK_LATITUDE,
        longitude=KILMARNOCK_LONGITUDE,
        is_active=True,
    )


async def seed_mark_profile(db: AsyncSession) -> Profile:
    """Create or update Mark's private admin profile."""

    result = await db.execute(
        select(Profile).where(
            Profile.display_name == MARK_DISPLAY_NAME,
            Profile.deleted_at.is_(None),
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = build_mark_profile()
        db.add(profile)
    else:
        profile.role = UserRole.admin
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
    async with AsyncSessionLocal() as db:
        profile = await seed_mark_profile(db)
        print(f"Seeded profile {profile.display_name} ({profile.id})")


if __name__ == "__main__":
    asyncio.run(_main())
