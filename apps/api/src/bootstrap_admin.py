"""Bootstrap the first admin player.

This is an operator-only script. It replaces the manual SQL step in
docs/runbooks/deploy.md (Step 8): the join endpoint can only create
``player``-role profiles, and there is intentionally no env-driven path
to admin. Run this once per environment after migrations + seeding.

Two modes:

* **create** (default): inserts a new admin profile + notification
  prefs row. Equivalent to the join flow but bypassing the invite and
  with ``role=admin``.
* **--promote**: finds an existing player by display_name and flips
  their role to ``admin``. Use this if you already joined via an invite
  and want to promote yourself.

Run from apps/api/ with:

    PYTHONPATH=. DATABASE_URL=<url> \\
      python -m src.bootstrap_admin --display-name "Craig" --timezone "Europe/London"

    PYTHONPATH=. DATABASE_URL=<url> \\
      python -m src.bootstrap_admin --promote --display-name "Craig"

Exit codes: 0 on success, 1 on validation / state error.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import hash_pin
from src.database import AsyncSessionLocal
from src.models.prediction import NotificationPreferences
from src.models.profile import PlayerRole, Profile, SiteRole

MAX_PLAYERS = 15  # mirrors src/routers/auth.py


class BootstrapError(Exception):
    """Operator-facing failure (duplicate name, league full, etc.)."""


async def _find_profile_by_name(session: AsyncSession, display_name: str) -> Profile | None:
    result = await session.execute(
        select(Profile).where(
            Profile.display_name == display_name,
            Profile.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _active_profile_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(Profile).where(Profile.deleted_at.is_(None))
    )
    return int(result.scalar() or 0)


async def create_admin(
    session: AsyncSession,
    *,
    display_name: str,
    pin: str,
    timezone: str,
    email: str | None = None,
) -> Profile:
    """Insert a new admin Profile (+ default NotificationPreferences row).

    Raises BootstrapError if the display name is already taken or the
    league is at MAX_PLAYERS.
    """
    if not pin:
        raise BootstrapError("PIN is required")

    existing = await _find_profile_by_name(session, display_name)
    if existing is not None:
        raise BootstrapError(
            f"Display name {display_name!r} already exists "
            f"(role={existing.role.value}). "
            f"Use --promote to flip an existing player to admin."
        )

    if (await _active_profile_count(session)) >= MAX_PLAYERS:
        raise BootstrapError(f"League is full ({MAX_PLAYERS} active players)")

    _parts = display_name.strip().split()
    _first = _parts[0] if _parts else display_name
    _last = _parts[-1].rstrip(".") if len(_parts) > 1 else _first
    _slug = display_name.lower().replace(" ", "-")
    _email = email or f"pending+{_slug}@steele.invalid"

    profile = Profile(
        id=uuid.uuid4(),
        display_name=display_name,
        pin_hash=hash_pin(pin),
        role=PlayerRole.admin,
        timezone=timezone,
        failed_login_count=0,
        locked_until=None,
        deleted_at=None,
        email=_email,
        first_name=_first,
        last_name=_last,
        site_role=SiteRole.superadmin,
    )
    session.add(profile)
    await session.flush()  # commit profile row before FK-dependent insert
    session.add(NotificationPreferences(player_id=profile.id))
    await session.flush()
    return profile


async def promote_existing(
    session: AsyncSession,
    *,
    display_name: str,
) -> Profile:
    """Flip an existing player's role to admin.

    Raises BootstrapError if the player doesn't exist or is already admin.
    """
    profile = await _find_profile_by_name(session, display_name)
    if profile is None:
        raise BootstrapError(f"No active player with display_name {display_name!r}")
    if profile.role == PlayerRole.admin:
        raise BootstrapError(f"{display_name!r} is already an admin")

    profile.role = PlayerRole.admin
    await session.flush()
    return profile


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--display-name", required=True, help="The player's display name")
    parser.add_argument(
        "--email", help="Admin's real email (optional; pending placeholder used if omitted)"
    )
    parser.add_argument("--timezone", default="UTC", help="IANA timezone (default: UTC)")
    parser.add_argument(
        "--pin",
        help="PIN (insecure — prompt is used if omitted). Ignored with --promote.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Flip an existing player to admin instead of creating a new profile",
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        try:
            if args.promote:
                profile = await promote_existing(session, display_name=args.display_name)
                action = "promoted"
            else:
                pin = args.pin or getpass.getpass("PIN: ").strip()
                profile = await create_admin(
                    session,
                    display_name=args.display_name,
                    pin=pin,
                    timezone=args.timezone,
                    email=getattr(args, "email", None),
                )
                action = "created"
            await session.commit()
        except BootstrapError as e:
            await session.rollback()
            print(f"error: {e}", file=sys.stderr)
            return 1

    print(f"{action} admin {profile.display_name!r} (id={profile.id})")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_async_main(_parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
