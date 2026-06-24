"""Admin-only runner: (re)compute ``metric_baselines`` from stored DB history.

Derives Mark's morning "Metrics vs Baselines" statistical baselines (mean /
median / quartiles / stddev per metric) from the ``daily_metrics`` + ``sleep``
history already in the DB — no xlsx — honouring the #45 SpO2/HRV reliability
cutoff (pre-2026-06-11 SpO2/HRV excluded, surfaced as ``excluded_sample_count``).
Idempotent: re-running recomputes + upserts the ``db_history`` baseline rows.

Usage (prod — run via ``railway run`` so ``DATABASE_URL`` points at prod
Supabase; this reads + writes only our DB, no Garmin/Hive egress):

    railway run --service api python -m src.metric_baselines_backfill --dry-run
    # then drop --dry-run to write
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.services.metric_baselines import DEFAULT_WINDOW_DAYS, MetricBaselineBackfillService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-name", default="Mark", help="Private user (default: Mark)")
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=(
            f"Trailing nights to summarise (default {DEFAULT_WINDOW_DAYS}; "
            "0 or --all uses all available history)"
        ),
    )
    parser.add_argument(
        "--all",
        dest="all_history",
        action="store_true",
        help="Use all available history (overrides --window-days)",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO date for the window end (default: latest available history date)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + diff without writing any rows",
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    use_all = args.all_history or args.window_days <= 0
    window_days: int | None = None if use_all else args.window_days

    async with AsyncSessionLocal() as session:
        profile = (
            await session.execute(
                select(Profile).where(
                    Profile.display_name == args.display_name,
                    Profile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise SystemExit(f"Profile {args.display_name!r} not found")

        print(
            f"{'DRY RUN: ' if args.dry_run else ''}computing metric baselines for "
            f"{args.display_name!r} "
            f"(window: {'all history' if window_days is None else f'{window_days} nights'})\n"
        )
        service = MetricBaselineBackfillService(session)
        result = await service.rebuild(
            profile, window_days=window_days, as_of=as_of, dry_run=args.dry_run
        )

    print(result.render())


if __name__ == "__main__":
    asyncio.run(_main())
