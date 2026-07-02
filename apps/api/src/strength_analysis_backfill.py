"""One-off backfill for historical post-strength analyses."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.services.post_strength_analysis import PostStrengthAnalysisService


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return datetime(parsed.year, parsed.month, parsed.day)


async def run_backfill(*, since: datetime | None, commit: bool) -> None:
    async with AsyncSessionLocal() as session:
        profiles = (
            (
                await session.execute(
                    select(Profile).where(
                        Profile.is_active.is_(True),
                        Profile.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        service = PostStrengthAnalysisService(session)
        generated = 0
        existing = 0
        pending_count = 0
        for profile in profiles:
            if commit:
                results = await service.generate_for_pending_strength(
                    profile,
                    since=since,
                    commit=False,
                )
                generated += sum(1 for result in results if result.generated)
                existing += sum(1 for result in results if not result.generated)
            else:
                pending_count += len(
                    await service.pending_strength_activities(profile.id, since=since)
                )

        if commit:
            await session.commit()
        else:
            await session.rollback()

    mode = "committed" if commit else "dry-run"
    print(
        f"post-strength backfill {mode}: profiles={len(profiles)} "
        f"pending={pending_count} generated={generated} existing={existing}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill post-strength analyses.")
    parser.add_argument(
        "--since",
        help="Earliest activity date to consider (YYYY-MM-DD). Defaults to the service window.",
    )
    parser.add_argument("--commit", action="store_true", help="Write analyses instead of dry-run.")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    asyncio.run(run_backfill(since=_parse_since(args.since), commit=args.commit))


if __name__ == "__main__":
    main()
