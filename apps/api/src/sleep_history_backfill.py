"""Admin-only backfill runner for the 84-night sleep spreadsheet."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.services.sleep_history import SleepHistoryImportService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="Path to the 12 Weeks Sleep Data workbook")
    parser.add_argument(
        "--display-name",
        default="Mark",
        help="Private user display name to backfill (default: Mark)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and diff the workbook without writing any rows",
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Profile).where(
                Profile.display_name == args.display_name,
                Profile.deleted_at.is_(None),
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise SystemExit(f"Profile {args.display_name!r} not found")

        service = SleepHistoryImportService(session)
        summary = await service.import_workbook(profile, args.workbook, dry_run=args.dry_run)

    print(
        "\n".join(
            [
                f"Rows parsed: {summary.rows_parsed}",
                f"Rows skipped: {summary.rows_skipped}",
                f"Dry run: {summary.dry_run}",
                f"Sleep rows created/updated: {summary.sleep_created}/{summary.sleep_updated}",
                "Daily metric rows created/updated: "
                f"{summary.daily_metrics_created}/{summary.daily_metrics_updated}",
                "Baselines created/updated: "
                f"{summary.baselines_created}/{summary.baselines_updated}",
            ]
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
