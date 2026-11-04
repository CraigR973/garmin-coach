"""The morning brief's eval: prepare, cost, run and report (Batch 318.4).

``prepare`` and ``cost`` spend nothing: ``prepare`` reads production read-only, and
``cost`` uses Anthropic's free token count. ``run`` is PAID (one brief per case per pass)
and refuses without ``--go``, which stands for Craig's go in writing.

From the repo root, with production's environment:

    PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python \\
        scripts/run_brief_eval.py prepare
    PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python \\
        scripts/run_brief_eval.py cost
    PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python \\
        scripts/run_brief_eval.py run --go --passes 1 --budget 2
    PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/run_brief_eval.py report

The packets and the written briefs carry Mark's health data, so they are kept in the
git-ignored ``scratchpad/brief-eval/``. Only scores, usage and the prompt's fingerprint
go into ``apps/api/tests/fixtures/brief_eval_recorded/<model>.json``, which CI checks.
"""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "scratchpad" / "brief-eval"
CASES = WORK / "cases.json"

#: US dollars per million tokens, in and out (as ``run_notes_eval.PRICES``).
PRICES: dict[str, tuple[float, float]] = {"claude-sonnet-5": (2.0, 10.0)}


async def prepare(count: int, dates: list[str] | None = None) -> None:
    """Pick stored graded mornings, read-only, and keep them in the scratchpad.

    Batch 369: ``dates`` picks those mornings instead, and each one's readiness trend is
    recomputed with today's code (plain figures, days away, the say flag chained from
    the case before), so a replay sees the packet the current prompt is written for.
    """

    from sqlalchemy import desc, event, select, text

    from src import database
    from src.models.coaching import Analysis
    from src.models.profile import Profile
    from src.services.brief_eval import select_cases

    @event.listens_for(database.engine.sync_engine, "connect")
    def _read_only(dbapi_connection: Any, _record: Any) -> None:
        # Supavisor drops startup settings, so the DBAPI flag is set on each connection.
        dbapi_connection.readonly = True

    async with database.AsyncSessionLocal() as session:
        if await session.scalar(text("SHOW transaction_read_only")) != "on":
            raise SystemExit("refusing to read: the session is not read-only")
        player = await session.scalar(
            select(Profile)
            .where(Profile.is_active.is_(True))
            .order_by(Profile.created_at)
        )
        if player is None:
            raise SystemExit("no active profile")
        refreshed: dict[str, dict[str, Any]] = {}
        if dates:
            refreshed = await _refreshed_readiness(session, player, sorted(dates))
        rows = (
            await session.execute(
                select(
                    Analysis.subject_date,
                    Analysis.context_packet,
                    Analysis.raw_response,
                )
                .where(
                    Analysis.user_id == player.id,
                    Analysis.analysis_type == "morning",
                    Analysis.output_markdown.is_not(None),
                )
                .order_by(desc(Analysis.subject_date), desc(Analysis.generated_at_utc))
                .limit(120)
            )
        ).all()
        await session.rollback()
    latest: dict[str, dict[str, Any]] = {}
    for subject_date, packet, raw in rows:
        verdict = (packet or {}).get("verdict") or {}
        if verdict.get("engine") != "graded" or subject_date.isoformat() in latest:
            continue
        if not (packet or {}).get("todaysCall"):
            # Stored before Batch 313: the call section's instruction has nothing to quote.
            continue
        usage = (raw or {}).get("usage") or {}
        if subject_date.isoformat() in refreshed:
            packet = _with_readiness(packet, refreshed[subject_date.isoformat()])
        latest[subject_date.isoformat()] = {
            "id": subject_date.isoformat(),
            "todaysCall": (packet or {}).get("todaysCall") or {},
            "packet": packet,
            "outputTokens": usage.get("output_tokens"),
        }
    chosen = (
        [latest[day] for day in sorted(dates) if day in latest]
        if dates
        else select_cases(list(latest.values()), count)
    )
    WORK.mkdir(parents=True, exist_ok=True)
    CASES.write_text(json.dumps(chosen, default=str), encoding="utf-8")
    keys = sorted({str(case["todaysCall"].get("key")) for case in chosen})
    print(f"{len(chosen)} cases, calls: {', '.join(keys)}; kept in {CASES}")


async def _refreshed_readiness(
    session: Any, player: Any, dates: list[str]
) -> dict[str, dict[str, Any]]:
    """Each date's readiness trend under today's code, the say flag chained (Batch 369)."""

    from datetime import date as date_type
    from datetime import timedelta

    from src.services.holiday_pause import HolidayPauseService
    from src.services.morning_analysis import MorningAnalysisService
    from src.services.personal_baselines import (
        readiness_baseline_trend,
        readiness_trend_say,
    )

    windows = await HolidayPauseService(session).get_windows(player)
    away = {
        window.start_date + timedelta(days=offset)
        for window in windows
        for offset in range((window.end_date - window.start_date).days + 1)
    }
    service = MorningAnalysisService(session)
    previous: dict[str, Any] | None = None
    out: dict[str, dict[str, Any]] = {}
    for day_text in dates:
        day = date_type.fromisoformat(day_text)
        history = await service._readiness_history(player.id, day)
        trend = readiness_baseline_trend(history, as_of=day, away_days=away)
        trend["say"] = readiness_trend_say(trend, previous, day)
        previous = trend
        out[day_text] = trend
    return out


def _with_readiness(packet: dict[str, Any], trend: dict[str, Any]) -> dict[str, Any]:
    """``packet`` with its readiness trend, and the trend's reason, replaced."""

    verdict = dict(packet.get("verdict") or {})
    old = verdict.get("readinessBaselineTrend") or {}
    verdict["readinessBaselineTrend"] = {**old, **trend}
    for key in ("firstHalfMedian", "secondHalfMedian"):
        verdict["readinessBaselineTrend"].pop(key, None)
    old_reason = old.get("reason")
    if isinstance(verdict.get("reasons"), list) and old_reason:
        verdict["reasons"] = [
            trend.get("reason") if reason == old_reason else reason
            for reason in verdict["reasons"]
            if not (reason == old_reason and trend.get("reason") is None)
        ]
    return {**packet, "verdict": verdict}


async def cost(model: str, passes: int) -> None:
    """Count the input tokens of every case under today's prompt, for free."""

    from anthropic import AsyncAnthropic

    from src.config import settings
    from src.services.anthropic_text import configured_thinking
    from src.services.brief_eval import estimated_cost_usd
    from src.services.morning_analysis import SYSTEM_PROMPT, build_morning_user_prompt

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)
    thinking = configured_thinking()
    total_in = 0
    for case in cases:
        params: dict[str, Any] = {
            "model": model,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": build_morning_user_prompt(case["packet"])}
            ],
        }
        if thinking:
            params["thinking"] = thinking
        counted = await client.messages.count_tokens(**params)
        total_in += int(counted.input_tokens)
    seen_out = [int(case["outputTokens"]) for case in cases if case.get("outputTokens")]
    per_out = int(statistics.median(seen_out)) if seen_out else 4000
    total_out = per_out * len(cases)
    one_pass = estimated_cost_usd(total_in, total_out, PRICES[model])
    print(
        f"{len(cases)} cases: {total_in:,} input tokens a pass (counted, free); output "
        f"estimated at {per_out:,} a case (the median of the stored briefs, thinking "
        f"included); about ${one_pass:.2f} a pass, ${one_pass * passes:.2f} for {passes}."
    )


async def run(model: str, passes: int, budget: float) -> None:
    """PAID. Write every case again under today's prompt and record its scores."""

    from src.services.anthropic_text import thinking_tokens
    from src.services.brief_check import check_brief
    from src.services.morning_output_contract import strip_readiness_line
    from src.services.plain_words_repair import anthropic_repair_result, finish_brief
    from src.services.brief_eval import (
        estimated_cost_usd,
        prompt_fingerprint,
        recording_path,
    )
    from src.services.morning_analysis import (
        PROMPT_VERSION,
        AnthropicMorningAnalysisClient,
        build_morning_user_prompt,
    )

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    results: dict[str, list[dict[str, Any]]] = {case["id"]: [] for case in cases}
    spent = 0.0
    done = 0
    # Batch 369: the fix-up call's tokens, so the recorded cost is the whole cost.
    repair_usage: list[dict[str, int]] = []

    async def repair_call(system_prompt: str, user_prompt: str) -> str:
        result = await anthropic_repair_result(system_prompt, user_prompt)
        repair_usage.append(result.usage or {})
        return result.output_markdown

    for index in range(passes):
        for case in cases:
            client = AnthropicMorningAnalysisClient(model_name=model)
            try:
                generation = await client.generate(
                    context_packet=case["packet"],
                    user_prompt=build_morning_user_prompt(case["packet"]),
                )
            except Exception as exc:  # noqa: BLE001 — record the failure, keep going
                results[case["id"]].append(
                    {"error": f"{type(exc).__name__}: {exc}"[:300]}
                )
                continue
            usage = generation.raw_response.get("usage") or {}
            spent += estimated_cost_usd(
                int(usage.get("input_tokens") or 0),
                int(usage.get("output_tokens") or 0),
                PRICES[model],
            )
            # Batch 369.2: the same one fix-up call a real brief gets, so the eval scores
            # what Mark would read; the misses before it are kept beside. Batch 377.1: and
            # the same finish, the app's readiness line placed by the app.
            before = check_brief(case["packet"], generation.output_markdown).to_packet()
            repair_usage.clear()
            markdown, repaired = await finish_brief(
                case["packet"], generation.output_markdown, call=repair_call
            )
            for counts in repair_usage:
                spent += estimated_cost_usd(
                    counts.get("input_tokens", 0),
                    counts.get("output_tokens", 0),
                    PRICES[model],
                )
                repaired["usage"] = {
                    "inputTokens": counts.get("input_tokens"),
                    "outputTokens": counts.get("output_tokens"),
                    "thinkingTokens": counts.get("thinking_tokens"),
                }
            (WORK / f"{case['id']}-pass{index + 1}.md").write_text(
                markdown, encoding="utf-8"
            )
            result = check_brief(case["packet"], markdown).to_packet()
            result["missesBeforeRepair"] = before["misses"]
            # Batch 377.1: whether the brief still wrote the app's line itself.
            result["wroteReadinessLine"] = (
                strip_readiness_line(case["packet"], generation.output_markdown)
                != generation.output_markdown
            )
            result["repair"] = repaired
            result["usage"] = {
                "inputTokens": usage.get("input_tokens"),
                "outputTokens": usage.get("output_tokens"),
                # Batch 369.4 (AI358-06): thinking is adaptive, so a prompt change that
                # also flips it cannot be told apart from the prompt change unless kept.
                "thinkingTokens": thinking_tokens(usage),
            }
            results[case["id"]].append(result)
        done = index + 1
        print(f"pass {done}: ${spent:.2f} so far")
        if spent + spent / done > budget and done < passes:
            print(f"stopping: another pass would pass the ${budget:.2f} budget")
            break
    recording = {
        "model": model,
        "promptVersion": PROMPT_VERSION,
        "promptFingerprint": prompt_fingerprint(),
        "passes": done,
        "recordedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "costUsd": round(spent, 4),
        "cases": results,
    }
    path = recording_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recording, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {path}")


def report(model: str) -> None:
    from src.services.brief_eval import (
        gate_failures,
        load_recording,
        stale_recording_reason,
    )

    recording = load_recording(model)
    if recording is None:
        print("No recording yet: the run is Craig's go.")
        return
    print(f"{model}, {recording['passes']} pass(es), ${recording['costUsd']:.2f}")
    print("stale:", stale_recording_reason(recording) or "no")
    for case_id, passes in sorted(recording["cases"].items()):
        print(case_id, [item.get("misses", item.get("error")) for item in passes])
    print("gate:", gate_failures(recording) or "holds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--count", type=int, default=10)
    prep.add_argument(
        "--dates", help="comma-separated mornings, e.g. 2026-10-28,2026-10-29"
    )
    cost_parser = sub.add_parser("cost")
    cost_parser.add_argument(
        "--model", default="claude-sonnet-5", choices=sorted(PRICES)
    )
    cost_parser.add_argument("--passes", type=int, default=1)
    run_parser = sub.add_parser("run")
    run_parser.add_argument(
        "--model", default="claude-sonnet-5", choices=sorted(PRICES)
    )
    run_parser.add_argument("--passes", type=int, default=1)
    run_parser.add_argument("--budget", type=float, required=True)
    run_parser.add_argument("--go", action="store_true", help="Craig's go, in writing")
    report_parser = sub.add_parser("report")
    report_parser.add_argument(
        "--model", default="claude-sonnet-5", choices=sorted(PRICES)
    )
    args = parser.parse_args()
    faulthandler.dump_traceback_later(1800, exit=True)
    if args.command == "prepare":
        asyncio.run(prepare(args.count, args.dates.split(",") if args.dates else None))
    elif args.command == "cost":
        asyncio.run(cost(args.model, args.passes))
    elif args.command == "run":
        if not args.go:
            raise SystemExit("run is paid: pass --go only with Craig's go in writing")
        asyncio.run(run(args.model, args.passes, args.budget))
    else:
        report(args.model)


if __name__ == "__main__":
    main()
