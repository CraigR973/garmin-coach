"""Admin CLI for minting one-time activation links."""

import argparse
import asyncio
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import select, update

from src.auth import ACTIVATION_TTL, generate_opaque_token, hash_token
from src.config import settings
from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.models.refresh_token import RefreshToken


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _activation_url(code: str) -> str:
    return f"{settings.frontend_origin.rstrip('/')}/activate#code={quote(code, safe='')}"


async def mint_activation_link(profile_name: str) -> str:
    async with AsyncSessionLocal() as db:
        profile = (
            await db.execute(
                select(Profile).where(
                    Profile.display_name == profile_name,
                    Profile.deleted_at.is_(None),
                    Profile.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise SystemExit(f"Active profile not found: {profile_name}")

        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == profile.id,
                RefreshToken.purpose == "activation",
                RefreshToken.used_at.is_(None),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )

        code = generate_opaque_token()
        db.add(
            RefreshToken(
                id=uuid.uuid4(),
                user_id=profile.id,
                token_hash=hash_token(code),
                purpose="activation",
                device_hint="cli-activation-link",
                expires_at=_now() + ACTIVATION_TTL,
            )
        )
        await db.commit()
        return _activation_url(code)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mint a one-time Garmin Coach activation link.")
    parser.add_argument("--profile", required=True, help="Exact display name of the profile")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    print(await mint_activation_link(args.profile))


if __name__ == "__main__":
    asyncio.run(_main())
