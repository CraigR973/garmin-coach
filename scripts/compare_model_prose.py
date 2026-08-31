"""Batch 233.8 — diff the morning brief's prose across two models, on real data.

Why this exists as a script rather than a test: no unit test can tell you whether
a brief still says what Mark needs. Sonnet 5 interprets instructions more
literally than Sonnet 4.6, so holdover style directives land at face value —
``morning_analysis.py``'s "Return concise markdown with…" halves the brief's
length on the same packet (8,482 chars → 3,806). Whether that is a better brief
or a lossy one is a judgement made by reading both.

The method matters: **exactly one variable moves.** It reads the stored
``context_packet`` from a real analysis, rebuilds the user prompt from it with
the app's own builder, and generates against the *current* settings. The stored
brief beside it was produced from that identical packet, so any difference is
the model and the generation settings, never the input.

Read-only: it writes two files to ``--out`` and nothing to the database.

Usage (needs ANTHROPIC_API_KEY and DATABASE_URL — `railway run` supplies both):

    railway run --service api apps/api/.venv/bin/python \\
        scripts/compare_model_prose.py --out /tmp/prose

Costs a real generation (~$0.21/run at effort=high). The account has a spend cap;
a rejection reads "You have reached your specified API usage limits" and arrives
as an HTTP 400, so check for it before assuming the code is at fault.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from src.config import settings  # noqa: E402
from src.services.morning_analysis import (  # noqa: E402
    PROMPT_VERSION,
    AnthropicMorningAnalysisClient,
    build_morning_user_prompt,
)


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="directory for the two .md files")
    parser.add_argument(
        "--prompt-version",
        default=PROMPT_VERSION,
        help="only compare briefs written by this prompt version (default: current)",
    )
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(_async_url(os.environ["DATABASE_URL"]))
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        """
                    select subject_date, context_packet, output_markdown,
                           raw_response->>'model' as model,
                           (raw_response->'usage'->>'output_tokens')::int as output_tokens
                    from coach.analyses
                    where analysis_type = 'morning' and prompt_version = :pv
                    order by subject_date desc
                    limit 1
                    """
                    ),
                    {"pv": args.prompt_version},
                )
            )
            .mappings()
            .one()
        )
    await engine.dispose()

    stored = out / f"brief_{row['model']}.md"
    stored.write_text(row["output_markdown"])
    print(f"day {row['subject_date']}  prompt {args.prompt_version}")
    print(
        f"  stored : {row['model']:<20} {len(row['output_markdown']):>6} chars  "
        f"{row['output_tokens']} output tokens  -> {stored}"
    )

    result = await AnthropicMorningAnalysisClient().generate(
        context_packet=row["context_packet"],
        user_prompt=build_morning_user_prompt(row["context_packet"]),
    )
    usage = result.raw_response.get("usage", {})
    thinking = (usage.get("output_tokens_details") or {}).get("thinking_tokens")
    fresh = out / f"brief_{result.model_name}_{settings.anthropic_effort}.md"
    fresh.write_text(result.output_markdown)
    print(
        f"  fresh  : {result.model_name:<20} {len(result.output_markdown):>6} chars  "
        f"{usage.get('output_tokens')} output tokens "
        f"({thinking} thinking, effort={settings.anthropic_effort})  -> {fresh}"
    )
    print(f"\n  diff {stored} {fresh}")


if __name__ == "__main__":
    asyncio.run(main())
