"""Replay stored mornings through the graded verdict (Batches 295, 308).

Read-only: it loads projected rows and packet sections, rolls its session back, and
writes nothing to the database. Run against production from a checkout:

    PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python \
        scripts/replay_verdicts.py --out docs/reviews/verdict-replay-YYYY-MM-DD.md

With ``--start``/``--end`` it replays a window; with neither, every stored morning.
Each is compared with what Mark was shown (since Batch 308 the ladder is gone). With
``--compare-without RULE`` (a ``GradingInputs`` flag, as Batch 310 used
``hrv_holiday_catch_up``) it also grades every morning without that rule and appends
the mornings the rule changes. With ``--rule-effect RULE`` (Batch 316) it grades every
morning with the rule forced on and again forced off, whatever each morning stored, and
appends every morning the rule would change: graded mornings stored before a rule replay
without it, so ``--compare-without`` alone cannot show what it changes on them.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.profile import Profile
from src.tools.verdict_replay import (
    VerdictReplayService,
    render_markdown,
    render_rule_comparison,
)


async def main(
    start: date | None,
    end: date | None,
    out: Path | None,
    compare_without: list[str],
    rule_effect: list[str],
) -> None:
    async with AsyncSessionLocal() as session:
        player = await session.scalar(
            select(Profile)
            .where(Profile.is_active.is_(True))
            .order_by(Profile.created_at)
            .limit(1)
        )
        if player is None:
            raise SystemExit("no active profile")
        report = await VerdictReplayService(session).replay(
            player, start=start, end=end
        )
        without = (
            await VerdictReplayService(session).replay(
                player, start=start, end=end, rules_off=compare_without
            )
            if compare_without
            else None
        )
        forced = (
            (
                await VerdictReplayService(session).replay(
                    player, start=start, end=end, rules_on=rule_effect
                ),
                await VerdictReplayService(session).replay(
                    player, start=start, end=end, rules_off=rule_effect
                ),
            )
            if rule_effect
            else None
        )
        await session.rollback()
    generated = datetime.now(UTC).strftime("Generated %-d %b %Y %H:%M UTC")
    text = render_markdown(report, generated=generated)
    if without is not None:
        text += "\n" + render_rule_comparison(
            report, without, rules_off=compare_without
        )
    if forced is not None:
        forced_on, forced_off = forced
        text += "\n" + render_rule_comparison(
            forced_on, forced_off, rules_off=rule_effect
        )
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
    parser.add_argument("--compare-without", action="append", default=[])
    parser.add_argument("--rule-effect", action="append", default=[])
    args = parser.parse_args()
    asyncio.run(
        main(args.start, args.end, args.out, args.compare_without, args.rule_effect)
    )
