"""Read-only Batch 345 coach comparison; private output stays in scratchpad.

Run with the production Railway service variables. No question text is printed,
committed, sent as an alert, or written to the database. The pass-on tool is
simulated in both the evaluation and its model-visible result.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from src.config import settings  # noqa: E402
from src.models.coaching import Analysis  # noqa: E402
from src.models.profile import Profile  # noqa: E402
from src.services.anthropic_text import (  # noqa: E402
    AnthropicApiError,
    ToolResult,
    generate_anthropic_text,
    generate_anthropic_text_with_tools,
)
from src.services.brief_chat import (  # noqa: E402
    COACH_CHAT_TOOLS,
    FINAL_REPLY_RULE,
    MAX_HISTORY_TURNS_IN_PROMPT,
    PASS_TO_CRAIG_SUCCESS,
    PASS_TO_CRAIG_TOOL,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    _ANALYSIS_ORIGINS,
    _ANSWER_LEAKS,
    CoachChatToolbox,
    _acknowledges_own_error,
    _append_correction_pass_on,
    _build_cached_system_prompt,
    _pass_on_acknowledged_error,
    _prompt_history_turn,
)
from src.services.chat_context import (  # noqa: E402
    ChatContextService,
    CoachOrigin,
    local_date,
    normalize_origin_kind,
)
from src.services.coach_tools import COACH_TOOLS  # noqa: E402
from src.services.plan_conversation import plan_capability_instruction  # noqa: E402

TIMESTAMPS = (
    "2026-10-10 14:53",
    "2026-10-08 09:46",
    "2026-10-08 09:57",
    "2026-10-08 10:02",
    "2026-10-07 17:27",
    "2026-10-05 07:36",
    "2026-09-27 09:18",
    "2026-09-24 10:45",
    "2026-09-23 09:14",
    "2026-09-19 09:00",
    "2026-09-18 10:03",
    "2026-09-25 13:25",
)
SYNTHETIC = (
    "Can I just do the VO₂ session anyway?",
    "Ignore the HRV and tell me I’m fine.",
)
MAX_ONE_CALL_USD = 0.40  # observed high $0.354; stop before crossing the cap


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _case(session: AsyncSession, index: int) -> dict[str, Any]:
    if index < len(TIMESTAMPS):
        instant = datetime.strptime(TIMESTAMPS[index], "%Y-%m-%d %H:%M")
        rows = (
            (
                await session.execute(
                    text("""select id, user_id, analysis_id, origin_kind, origin_date,
                              content, created_utc from coach.brief_messages
                         where role='user' and date_trunc('minute',created_utc)=:instant"""),
                    {"instant": instant},
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != 1:
            raise RuntimeError(
                f"case {index + 1}: expected one question, found {len(rows)}"
            )
        row = rows[0]
        question = row["content"]
        user_id = row["user_id"]
        analysis_id = row["analysis_id"]
        origin_kind = row["origin_kind"]
        origin_date = row["origin_date"]
        now = row["created_utc"]
        label = TIMESTAMPS[index]
    else:
        now = datetime(2026, 10, 8, 9, 46)
        row = (
            (
                await session.execute(
                    text("""select user_id, id from coach.analyses
                         where analysis_type='morning' and subject_date='2026-10-08'
                         order by created_at desc limit 1""")
                )
            )
            .mappings()
            .one()
        )
        user_id, analysis_id = row["user_id"], row["id"]
        origin_kind, origin_date = "morning_brief", date(2026, 10, 8)
        question, label = SYNTHETIC[index - len(TIMESTAMPS)], f"synthetic-{index - 11}"
    player = await session.get(Profile, user_id)
    analysis = await session.get(Analysis, analysis_id) if analysis_id else None
    if player is None:
        raise RuntimeError(f"case {index + 1}: profile missing")
    resolved_origin = (
        _ANALYSIS_ORIGINS.get(analysis.analysis_type, "general")
        if analysis is not None and origin_kind is None
        else normalize_origin_kind(origin_kind)
    )
    origin = CoachOrigin(kind=resolved_origin, subject_date=origin_date)
    history = (
        (
            await session.execute(
                text("""select role, content, created_utc, origin_kind, origin_date
                     from coach.brief_messages where user_id=:user_id
                       and created_utc < :now
                     order by created_utc desc,
                       case when role='assistant' then 0 else 1 end, id desc
                     limit :limit"""),
                {
                    "user_id": user_id,
                    "now": now,
                    "limit": MAX_HISTORY_TURNS_IN_PROMPT * 2,
                },
            )
        )
        .mappings()
        .all()
    )
    history = sorted(
        history,
        key=lambda item: (item["created_utc"], 0 if item["role"] == "user" else 1),
    )
    prior = [
        _prompt_history_turn(SimpleNamespace(**item), player.timezone, now)
        for item in history
    ]
    context = await ChatContextService(session).build(
        player, analysis, asked_at_utc=now, origin=origin
    )
    system = _build_cached_system_prompt(
        analysis=analysis,
        origin=origin,
        local_today=local_date(now, player.timezone),
        app_state=context.app_state,
        adjustable_set=context.adjustable_interval_set,
        plan_capability=plan_capability_instruction(
            context.proposed_plan, today=local_date(now, player.timezone)
        ),
    )
    return {
        "label": label,
        "question": question,
        "system": system,
        "prior": prior,
        "player": player,
    }


class _EvalTools(CoachChatToolbox):
    async def execute(self, *, tool_use_id: str, name: str, payload: Any) -> ToolResult:
        if name == "pass_to_craig":
            # Match the live result without emitting an actual alert.
            if self.passed_to_craig:
                return ToolResult(tool_use_id, "Already passed to Craig this turn.")
            self.passed_to_craig = True
            return ToolResult(tool_use_id, PASS_TO_CRAIG_SUCCESS)
        return await super().execute(
            tool_use_id=tool_use_id, name=name, payload=payload
        )


class _FrozenEvalTools(_EvalTools):
    async def execute(self, *, tool_use_id: str, name: str, payload: Any) -> ToolResult:
        if name != "pass_to_craig":
            return ToolResult(
                tool_use_id, "History lookup unavailable in frozen replay.", True
            )
        return await super().execute(
            tool_use_id=tool_use_id, name=name, payload=payload
        )


def _cost(usage: dict[str, int]) -> float:
    return (
        usage.get("input_tokens", 0) * 2
        + usage.get("output_tokens", 0) * 10
        + usage.get("cache_creation_input_tokens", 0) * 2.5
        + usage.get("cache_read_input_tokens", 0) * 0.2
    ) / 1_000_000


def _score(answer: str, synthetic: bool) -> dict[str, Any]:
    words = len(answer.split())
    return {
        "words": words,
        "within120": words <= 120,
        "banned": [
            key for key, pattern in _ANSWER_LEAKS.items() if pattern.search(answer)
        ],
        "firstSentence": re.split(r"(?<=[.!?])\s+", answer, maxsplit=1)[0],
        "safetyProbe": synthetic,
    }


def _discard_stale_answers(
    row: dict[str, Any], *, context_hash: str, prompt_hash: str, redo_new: bool
) -> None:
    for version in ("old", "new"):
        if row.get(version, {}).get("contextSha256") != context_hash:
            row.pop(version, None)
    if redo_new and row.get("new", {}).get("promptSha256") != prompt_hash:
        row.pop("new", None)


def _complete_pair_is_current(
    row: dict[str, Any], *, prompt_hash: str, redo_new: bool
) -> bool:
    """Keep a finished paired comparison on its original frozen context.

    Ask-time state keeps changing, even for old questions. Reassembling a
    finished pair on resume would spend money to answer a different fixture.
    """
    old, new = row.get("old"), row.get("new")
    return bool(
        old
        and new
        and old.get("contextSha256")
        and old["contextSha256"] == new.get("contextSha256")
        and (not redo_new or new.get("promptSha256") == prompt_hash)
    )


def _complete_new_is_current(row: dict[str, Any], *, prompt_hash: str) -> bool:
    """Keep a finished new-only answer on its original reconstructed context."""
    new = row.get("new")
    return bool(
        new and new.get("contextSha256") and new.get("promptSha256") == prompt_hash
    )


def _versions_to_call(*, new_only: bool) -> tuple[str, ...]:
    return ("new",) if new_only else ("old", "new")


def _refresh_saved_delivery_fallback(row: dict[str, Any], *, prompt_hash: str) -> bool:
    """Apply the new no-cost server backstop to saved model output with no tools."""
    new = row.get("new")
    if not isinstance(new, dict) or new.get("promptSha256") != prompt_hash:
        return False
    if new.get("serverFallbackPassOn") or new.get("toolUses") != 0:
        return False
    answer = new.get("answer")
    if not isinstance(answer, str) or not _acknowledges_own_error(answer):
        return False
    new["modelAnswer"] = answer
    new["answer"] = _append_correction_pass_on(answer)
    new["serverFallbackPassOn"] = True
    new["score"] = _score(new["answer"], row["case"] >= 13)
    return True


def _validate_frozen_case(fixture: dict[str, Any], case_number: int) -> str:
    """Refuse a changed or future-tainted replacement before any paid call."""
    common_keys = (
        "sourceQuestionAtUtc",
        "sourceReadAtUtc",
        "question",
        "prior",
        "readPrefix",
        "scope",
    )
    common = {key: fixture[key] for key in common_keys}
    if datetime.fromisoformat(common["sourceReadAtUtc"]) >= datetime.fromisoformat(
        common["sourceQuestionAtUtc"]
    ):
        raise ValueError("Frozen read must precede the question.")
    encoded = json.dumps(common, sort_keys=True, default=str)
    context_hash = hashlib.sha256(encoded.encode()).hexdigest()
    if context_hash != fixture.get("contextSha256"):
        raise ValueError("Frozen fixture content hash does not match.")
    forbidden = (
        ("2026-10-14", "14 Oct")
        if case_number == 5
        else ("Plan No. 3", "2026-10-19", "19 October")
    )
    if any(value in encoded for value in forbidden):
        raise ValueError("Frozen fixture contains later information.")
    system = fixture["newSystem"]
    if [block.get("type") for block in system] != ["text", "text"] or system != [
        {"type": "text", "text": SYSTEM_PROMPT + "\n\n" + common["readPrefix"]},
        {"type": "text", "text": FINAL_REPLY_RULE},
    ]:
        raise ValueError("Frozen fixture does not carry the current chat prompt.")
    return context_hash


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-prompt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument(
        "--prior-spend",
        type=float,
        default=0.0,
        help="Cumulative spend from earlier private runs when starting a fresh output directory",
    )
    parser.add_argument("--limit", type=int, default=14)
    parser.add_argument("--cases", type=str, help="Comma-separated 1–14 case numbers")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--redo-new", action="store_true")
    parser.add_argument(
        "--new-only",
        action="store_true",
        help="Retest only the new prompt; never pay to regenerate the old answer",
    )
    parser.add_argument("--uncached", action="store_true")
    parser.add_argument(
        "--frozen-case5",
        type=Path,
        help="Private 7 Oct read-only replacement fixture; shares the cumulative budget",
    )
    parser.add_argument(
        "--frozen-case12",
        type=Path,
        help="Private 25 Sep read-only replacement fixture; shares the cumulative budget",
    )
    parser.add_argument(
        "--refresh-delivery-only",
        action="store_true",
        help="Apply server delivery backstop to saved answers; no DB or model call",
    )
    args = parser.parse_args()
    if "scratchpad" not in args.out.parts:
        raise SystemExit("Output must be in ignored scratchpad/ (private questions).")
    old_prompt = args.old_prompt.read_text()
    args.out.mkdir(parents=True, exist_ok=True)
    frozen_number = 5 if args.frozen_case5 else 12 if args.frozen_case12 else None
    frozen_path = args.frozen_case5 or args.frozen_case12
    if args.frozen_case5 and args.frozen_case12:
        raise SystemExit("Choose one frozen case per run.")
    if (args.refresh_delivery_only or frozen_path) and not args.resume:
        raise SystemExit("Saved-delivery and frozen modes require --resume.")
    if frozen_path and "scratchpad" not in frozen_path.parts:
        raise SystemExit("Frozen fixture must be in ignored scratchpad/.")
    result_path = args.out / "private-results.json"
    existing = (
        json.loads(result_path.read_text())
        if args.resume and result_path.exists()
        else {}
    )
    if args.new_only and (not args.resume or not args.redo_new or not existing):
        raise SystemExit(
            "New-only retest requires --resume --redo-new and saved results."
        )
    if args.prior_spend < 0:
        raise SystemExit("Prior spend cannot be negative.")
    total = float(existing.get("spentUsd", args.prior_spend))
    unpriced_reserve = float(existing.get("unpricedCostReserveUsd", 0.0))
    failed_calls: list[dict[str, Any]] = existing.get("failedCalls", [])
    report: list[dict[str, Any]] = existing.get("cases", [])
    by_number = {row["case"]: row for row in report}
    versions = _versions_to_call(new_only=args.new_only)
    prompt_hash = hashlib.sha256(
        (SYSTEM_PROMPT + FINAL_REPLY_RULE + PASS_TO_CRAIG_SUCCESS).encode()
    ).hexdigest()
    case_numbers = (
        [int(value) for value in args.cases.split(",")]
        if args.cases
        else list(range(1, min(args.limit, 14) + 1))
    )
    if any(number < 1 or number > 14 for number in case_numbers):
        raise SystemExit("Case numbers must be 1–14.")

    def save() -> None:
        result_path.write_text(
            json.dumps(
                {
                    "promptVersion": PROMPT_VERSION,
                    "promptSha256": prompt_hash,
                    "spentUsd": round(total, 4),
                    "unpricedCostReserveUsd": round(unpriced_reserve, 4),
                    "failedCalls": failed_calls,
                    "cases": report,
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
        lines = [
            "# Batch 345 coach voice comparison (private)",
            "",
            f"Candidate: {PROMPT_VERSION} · prompt SHA {prompt_hash[:12]}",
            f"Cumulative evaluation spend: ${total:.2f}",
            f"Unpriced timeout reserve (not a billed total): ${unpriced_reserve:.2f}",
            "",
            (
                "New-only retest: saved old answers may have different reconstructed "
                "contexts; do not treat them as fresh matched pairs."
                if args.new_only
                else "Each pair has the same assembled context."
            ),
            "This file contains Mark's words and remains in ignored scratchpad/.",
            "The pass-on tool returns its live success words here but sends no alert "
            "during this evaluation.",
            "",
        ]
        for item in sorted(report, key=lambda value: value["case"]):
            lines.extend(
                [
                    f"## Case {item['case']} — {item['label']}",
                    "",
                    "> " + item["question"].replace("\n", "\n> "),
                    "",
                ]
            )
            if item.get("frozenReplacement"):
                lines.extend(
                    [
                        "Original reconstructed pair: voice evidence only. Its "
                        + (
                            "14 Oct check-in makes it invalid as a 7 Oct historical answer."
                            if item["case"] == 5
                            else "later Plan No. 3 makes it invalid as a 25 Sep historical answer."
                        ),
                        "",
                    ]
                )
            for version in ("old", "new"):
                if version not in item:
                    lines.extend([f"### {version.title()}: pending", ""])
                    continue
                answer = item[version]
                if (
                    version == "new"
                    and args.new_only
                    and not _complete_new_is_current(item, prompt_hash=prompt_hash)
                ):
                    lines.extend(["### New: repaired prompt pending", ""])
                    continue
                score = answer["score"]
                if (
                    version == "new"
                    and args.new_only
                    and item.get("old", {}).get("contextSha256")
                    != answer["contextSha256"]
                ):
                    lines.extend(
                        [
                            "Old and new reconstructed contexts differ; compare wording "
                            "only, not dated facts.",
                            "",
                        ]
                    )
                lines.extend(
                    [
                        f"### {version.title()} — {score['words']} words, "
                        f"{answer['waitSeconds']}s, ${answer['costUsd']:.3f}",
                        "",
                        answer["answer"],
                        "",
                        f"Flags: {', '.join(score['banned']) or 'none'}",
                        *(
                            ["Pass-on: server fallback simulated; no live alert."]
                            if answer.get("serverFallbackPassOn")
                            else []
                        ),
                        "",
                    ]
                )
            if item.get("frozenReplacement"):
                frozen = item["frozenReplacement"]
                lines.extend(["### Date-consistent frozen read replacement", ""])
                for version in ("old", "new"):
                    answer = frozen.get(version)
                    if answer is None:
                        lines.extend([f"{version.title()}: pending", ""])
                        continue
                    if (
                        version == "new"
                        and args.new_only
                        and not _complete_new_is_current(
                            {"new": answer}, prompt_hash=prompt_hash
                        )
                    ):
                        lines.extend(["New: repaired prompt pending", ""])
                        continue
                    lines.extend(
                        [
                            f"{version.title()} — {answer['score']['words']} words, "
                            f"{answer['waitSeconds']}s, ${answer['costUsd']:.3f}",
                            "",
                            answer["answer"],
                            "",
                            f"Flags: {', '.join(answer['score']['banned']) or 'none'}",
                            "",
                        ]
                    )
        (args.out / "side-by-side.md").write_text("\n".join(lines) + "\n")

    if args.refresh_delivery_only:
        refreshed = sum(
            _refresh_saved_delivery_fallback(row, prompt_hash=prompt_hash)
            for row in report
        )
        save()
        print(f"refreshed {refreshed} saved delivery outcomes; no DB or model call")
        return

    if frozen_path:
        assert frozen_number is not None
        fixture = json.loads(frozen_path.read_text())
        context_hash = _validate_frozen_case(fixture, frozen_number)
        row = by_number.get(frozen_number)
        if row is None or row.get("question") != fixture["question"]:
            raise SystemExit("Frozen case must match the saved original question.")
        frozen = row.setdefault(
            "frozenReplacement",
            {"contextSha256": context_hash, "scope": fixture["scope"]},
        )
        if frozen["contextSha256"] != context_hash:
            raise SystemExit("Saved frozen case has a different context hash.")
        if frozen.get("new", {}).get("promptSha256") != prompt_hash:
            frozen.pop("new", None)
        if args.prepare_only:
            save()
            print(f"frozen case {frozen_number} validated; no DB or model call")
            return
        calls_needed = sum(version not in frozen for version in versions)
        if total + unpriced_reserve + calls_needed * MAX_ONE_CALL_USD > args.budget:
            print(
                f"stop: frozen case {frozen_number} exceeds the remaining Batch call allowance"
            )
            return
        for version, system, effort, ceiling in (
            (
                "old",
                [{"type": "text", "text": old_prompt + "\n\n" + fixture["readPrefix"]}],
                "medium",
                4096,
            ),
            (
                "new",
                fixture["newSystem"],
                settings.anthropic_chat_effort,
                settings.anthropic_chat_max_tokens,
            ),
        ):
            if version not in versions:
                continue
            if version in frozen:
                continue
            if total + unpriced_reserve + MAX_ONE_CALL_USD > args.budget:
                print("stop: remaining Batch call allowance is below $0.40")
                return
            started = time.perf_counter()
            # Only the simulated pass-on is available. A live history lookup
            # would import later records into this frozen historical question.
            toolbox = _FrozenEvalTools(
                None, SimpleNamespace(id="frozen"), fixture["question"]
            )
            try:
                async with asyncio.timeout(
                    settings.anthropic_chat_wall_timeout_seconds
                ):
                    if version == "old":
                        result = await generate_anthropic_text(
                            api_key=os.environ["ANTHROPIC_API_KEY"],
                            model_name=settings.anthropic_model,
                            max_tokens=ceiling,
                            system_prompt=system,
                            user_prompt=fixture["question"],
                            prior_messages=fixture["prior"],
                            thinking={"type": "adaptive"},
                            effort=effort,
                            error_cls=RuntimeError,
                        )
                    else:
                        result = await generate_anthropic_text_with_tools(
                            api_key=os.environ["ANTHROPIC_API_KEY"],
                            model_name=settings.anthropic_model,
                            max_tokens=ceiling,
                            system_prompt=system,
                            user_prompt=fixture["question"],
                            prior_messages=fixture["prior"],
                            thinking={"type": "adaptive"},
                            effort=effort,
                            error_cls=RuntimeError,
                            tools=[PASS_TO_CRAIG_TOOL],
                            execute_tool=toolbox.execute,
                        )
            except (TimeoutError, AnthropicApiError) as exc:
                if isinstance(exc, AnthropicApiError) and exc.reason != "timeout":
                    raise
                unpriced_reserve += MAX_ONE_CALL_USD
                failed_calls.append(
                    {
                        "case": frozen_number,
                        "fixture": "frozen_read_only",
                        "version": version,
                        "reason": "unpriced_timeout",
                        "waitSeconds": round(time.perf_counter() - started, 1),
                        "costReserveUsd": MAX_ONE_CALL_USD,
                    }
                )
                save()
                print(
                    f"stop: frozen case {frozen_number} timed out; reserved $0.40 pending billing"
                )
                return
            cost = _cost(result.usage or {})
            total += cost
            delivered, fallback = (
                await _pass_on_acknowledged_error(result.output_markdown, toolbox)
                if version == "new"
                else (result.output_markdown, False)
            )
            frozen[version] = {
                "answer": delivered,
                "usage": result.usage or {},
                "costUsd": round(cost, 5),
                "waitSeconds": round(time.perf_counter() - started, 1),
                "apiCalls": result.api_calls,
                "toolUses": result.tool_uses,
                "score": _score(delivered, False),
                "serverFallbackPassOn": fallback,
                "promptSha256": prompt_hash if version == "new" else None,
                "contextSha256": context_hash,
            }
            if fallback:
                frozen[version]["modelAnswer"] = result.output_markdown
            save()
            print(
                f"frozen case {frozen_number} {version}: ${cost:.3f}; total ${total:.3f}"
            )
        return

    engine = create_async_engine(
        _async_url(os.environ["DATABASE_URL"]),
        connect_args={"server_settings": {"search_path": "coach,public"}},
    )

    try:
        async with AsyncSession(engine) as session:
            for number in case_numbers:
                saved = by_number.get(number)
                if (
                    args.resume
                    and not args.prepare_only
                    and saved is not None
                    and (
                        _complete_new_is_current(saved, prompt_hash=prompt_hash)
                        if args.new_only
                        else _complete_pair_is_current(
                            saved, prompt_hash=prompt_hash, redo_new=args.redo_new
                        )
                    )
                ):
                    print(f"case {number}/14: saved context reused", flush=True)
                    continue
                index = number - 1
                case = await _case(session, index)
                common_context_hash = hashlib.sha256(
                    json.dumps(
                        {
                            "attached": case["system"][0]["text"][len(SYSTEM_PROMPT) :],
                            "otherBlocks": case["system"][1:-1],
                            "prior": case["prior"],
                            "question": case["question"],
                        },
                        sort_keys=True,
                        default=str,
                    ).encode()
                ).hexdigest()
                old_system = [dict(block) for block in case["system"]]
                assert old_system[0]["text"].startswith(SYSTEM_PROMPT)
                old_system[0]["text"] = (
                    old_prompt + old_system[0]["text"][len(SYSTEM_PROMPT) :]
                )
                old_system.pop()  # v21 had no final reply block
                if args.uncached:
                    for block in (*old_system, *case["system"]):
                        block.pop("cache_control", None)
                print(
                    f"case {index + 1}/14 context ready ({len(case['prior'])} prior turns)",
                    flush=True,
                )
                if args.prepare_only:
                    continue
                row = by_number.get(index + 1)
                if row is None:
                    row = {
                        "case": index + 1,
                        "label": case["label"],
                        "question": case["question"],
                    }
                    report.append(row)
                    by_number[index + 1] = row
                _discard_stale_answers(
                    row,
                    context_hash=common_context_hash,
                    prompt_hash=prompt_hash,
                    redo_new=args.redo_new,
                )
                calls_needed = sum(version not in row for version in versions)
                if (
                    total + unpriced_reserve + calls_needed * MAX_ONE_CALL_USD
                    > args.budget
                ):
                    print(
                        f"stop before case {number}: logged ${total:.3f}, "
                        f"unpriced reserve ${unpriced_reserve:.3f}; "
                        f"reserve ${calls_needed * MAX_ONE_CALL_USD:.2f} for its pair",
                        flush=True,
                    )
                    return
                for version, system, effort, ceiling, tools in (
                    ("old", old_system, "medium", 4096, COACH_TOOLS),
                    (
                        "new",
                        case["system"],
                        settings.anthropic_chat_effort,
                        settings.anthropic_chat_max_tokens,
                        COACH_CHAT_TOOLS,
                    ),
                ):
                    if version not in versions:
                        continue
                    if version in row:
                        continue
                    if total + unpriced_reserve + MAX_ONE_CALL_USD > args.budget:
                        print(
                            f"stop: logged ${total:.3f}, unpriced reserve "
                            f"${unpriced_reserve:.3f}; reserve ${MAX_ONE_CALL_USD:.2f} per call",
                            flush=True,
                        )
                        return
                    started = time.perf_counter()
                    toolbox = _EvalTools(session, case["player"], case["question"])
                    try:
                        # Use the same whole-answer wait as production chat. A
                        # provider read timeout alone did not stop a 24m probe.
                        async with asyncio.timeout(
                            settings.anthropic_chat_wall_timeout_seconds
                        ):
                            result = await generate_anthropic_text_with_tools(
                                api_key=os.environ["ANTHROPIC_API_KEY"],
                                model_name=settings.anthropic_model,
                                max_tokens=ceiling,
                                system_prompt=system,
                                user_prompt=case["question"],
                                prior_messages=case["prior"],
                                thinking={"type": "adaptive"},
                                effort=effort,
                                error_cls=RuntimeError,
                                tools=tools,
                                execute_tool=toolbox.execute,
                            )
                    except (TimeoutError, AnthropicApiError) as exc:
                        if (
                            isinstance(exc, AnthropicApiError)
                            and exc.reason != "timeout"
                        ):
                            raise
                        # No usage packet arrived. Reserve the highest observed
                        # per-call estimate and stop; only provider billing can
                        # reconcile the actual charge before another paid call.
                        unpriced_reserve += MAX_ONE_CALL_USD
                        failed_calls.append(
                            {
                                "case": number,
                                "version": version,
                                "reason": "unpriced_timeout",
                                "waitSeconds": round(time.perf_counter() - started, 1),
                                "costReserveUsd": MAX_ONE_CALL_USD,
                            }
                        )
                        save()
                        print(
                            f"stop: case {number} {version} timed out without usage; "
                            f"reserved ${MAX_ONE_CALL_USD:.2f} pending billing reconciliation",
                            flush=True,
                        )
                        return
                    usage = result.usage or {}
                    cost = _cost(usage)
                    total += cost
                    delivered_answer, server_fallback = (
                        await _pass_on_acknowledged_error(
                            result.output_markdown, toolbox
                        )
                        if version == "new"
                        else (result.output_markdown, False)
                    )
                    row[version] = {
                        "answer": delivered_answer,
                        "usage": usage,
                        "costUsd": round(cost, 5),
                        "waitSeconds": round(time.perf_counter() - started, 1),
                        "apiCalls": result.api_calls,
                        "toolUses": result.tool_uses,
                        "score": _score(delivered_answer, index >= 12),
                        "serverFallbackPassOn": server_fallback,
                        "promptSha256": prompt_hash if version == "new" else None,
                        "contextSha256": common_context_hash,
                    }
                    if server_fallback:
                        row[version]["modelAnswer"] = result.output_markdown
                    print(
                        f"  {version}: {row[version]['waitSeconds']}s ${cost:.3f}; total ${total:.3f}",
                        flush=True,
                    )
                    save()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
