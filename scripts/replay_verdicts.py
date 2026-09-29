"""Replay stored mornings through today's ladder and the graded verdict (Batch 295).

Read-only: it loads projected rows and packet sections, rolls its session back, and
writes nothing to the database. Run against production from a checkout:

    PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python \
        scripts/replay_verdicts.py --out docs/reviews/verdict-replay-YYYY-MM-DD.md

With ``--start``/``--end`` it replays a window; with neither, every stored morning.
Batch 296 uses the same service to compare the two verdicts each morning.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.services.verdict_replay import VerdictReplayService, render_markdown


async def main(start: date | None, end: date | None, out: Path | None) -> None:
    async with AsyncSessionLocal() as session:
        player = await session.scalar(
            select(Profile).where(Profile.is_active.is_(True)).order_by(Profile.created_at).limit(1)
        )
        if player is None:
            raise SystemExit("no active profile")
        report = await VerdictReplayService(session).replay(player, start=start, end=end)
        await session.rollback()
    generated = datetime.now(UTC).strftime("Generated %-d %b %Y %H:%M UTC")
    text = render_markdown(report, generated=generated)
    if out is None:
        print(text)
    else:
        out.write_text(text + "\n")
        print(f"wrote {out} ({len(report.mornings)} mornings)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end, args.out))
