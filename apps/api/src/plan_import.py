"""Admin-only runner: load a reviewed training-plan JSON as Mark's owned plan.

Usage (from the api venv, with the DB env available e.g. via ``railway run``)::

    python -m src.plan_import apps/api/data/plans/plan_no2.json --dry-run
    python -m src.plan_import apps/api/data/plans/plan_no2.json          # apply

See ``src.services.plan_import`` / DECISIONS #102 for the why + the JSON shape.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.services.plan_import import DEFAULT_BLOCK_PREFIX, import_plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="Path to the reviewed plan JSON")
    parser.add_argument("--display-name", default="Mark", help="Owner (default: Mark)")
    parser.add_argument(
        "--start-date",
        default=None,
        help="Override the plan's Monday start (YYYY-MM-DD); must be a Monday",
    )
    parser.add_argument("--block-prefix", default=DEFAULT_BLOCK_PREFIX)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + preview the change counts without writing any rows",
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    start = date.fromisoformat(args.start_date) if args.start_date else None

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

        summary = await import_plan(
            session,
            profile.id,
            plan,
            start_date=start,
            block_prefix=args.block_prefix,
            dry_run=args.dry_run,
        )

    print(
        "\n".join(
            [
                f"Plan: {plan.get('name', '(unnamed)')}  ->  {args.display_name}",
                f"Start (Monday): {summary.start_date}  |  dry_run={summary.dry_run}",
                f"Removed prior import: {summary.prior_import_blocks_removed} blocks / "
                f"{summary.prior_import_workouts_removed} workouts",
                f"Removed forward seed: {summary.forward_blocks_removed} blocks / "
                f"{summary.forward_workouts_removed} workouts",
                f"Inserted: {summary.blocks_inserted} blocks / "
                f"{summary.workouts_inserted} workouts",
            ]
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
