"""One-off post-walk analysis backfill runner.

Dry-run by default. Use ``--commit`` to generate analyses for qualifying
historical deliberate walks.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.services.post_walk_analysis import PostWalkAnalysisService


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


async def _run(*, display_name: str, since: date, commit: bool) -> None:
    async with AsyncSessionLocal() as session:
        player = await session.scalar(
            select(Profile)
            .where(Profile.display_name == display_name, Profile.deleted_at.is_(None))
            .limit(1)
        )
        if player is None:
            raise SystemExit(f"Profile not found: {display_name}")

        service = PostWalkAnalysisService(session)
        since_dt = datetime.combine(since, time.min)
        pending = await service.pending_walk_activities(player.id, since=since_dt)
        if not commit:
            print(
                f"Dry run: {len(pending)} qualifying deliberate walk(s) pending "
                f"for {display_name} since {since.isoformat()}."
            )
            for activity in pending[:20]:
                print(
                    f"- {activity.start_utc.date().isoformat()} "
                    f"{activity.activity_name} "
                    f"{round((activity.duration_sec or 0) / 60)} min "
                    f"{round((activity.distance_m or 0) / 1000, 2)} km"
                )
            if len(pending) > 20:
                print(f"... {len(pending) - 20} more")
            return

        results = await service.generate_for_pending_walks(player, since=since_dt)
        generated = sum(1 for result in results if result.generated)
        existing = sum(1 for result in results if not result.generated)
        print(f"Generated {generated} post-walk analyses; {existing} already current.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-name", default="Mark")
    parser.add_argument("--since", type=_parse_date, required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(display_name=args.display_name, since=args.since, commit=args.commit))


if __name__ == "__main__":
    main()
