"""One-off post-workout ride analysis backfill runner (Batch 44).

Dry-run by default. Use ``--commit`` to regenerate post-ride analyses for recent
structured rides through the interval-resolved packet. Because
``pending_ride_activities`` is prompt-version aware, rides whose latest analysis
predates the current ``PROMPT_VERSION`` are picked up automatically — no ``force``
needed. Precedent: the #51 outdoor-ride backfill and the Batch 40 mobility backfill.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.services.post_workout_analysis import PostWorkoutAnalysisService


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

        service = PostWorkoutAnalysisService(session)
        since_dt = datetime.combine(since, time.min)
        pending = await service.pending_ride_activities(player.id, since=since_dt)
        if not commit:
            print(
                f"Dry run: {len(pending)} ride(s) pending post-workout analysis "
                f"for {display_name} since {since.isoformat()}."
            )
            for activity in pending[:20]:
                print(
                    f"- {activity.start_utc.date().isoformat()} "
                    f"{activity.activity_name} ({activity.activity_type})"
                )
            if len(pending) > 20:
                print(f"... {len(pending) - 20} more")
            return

        results = await service.generate_for_pending_rides(player, since=since_dt)
        generated = sum(1 for result in results if result.generated)
        existing = sum(1 for result in results if not result.generated)
        print(f"Generated {generated} post-workout analyses; {existing} already current.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-name", default="Mark")
    parser.add_argument("--since", type=_parse_date, required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(display_name=args.display_name, since=args.since, commit=args.commit))


if __name__ == "__main__":
    main()
