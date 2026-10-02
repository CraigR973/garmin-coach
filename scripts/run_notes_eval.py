"""Run the notes reader over the labelled eval cases, and record every response (Batch 297).

PAID: every case is one Anthropic call per pass. Craig's go, 30 Sep 2026: up to $5 in
all, Sonnet 5 and Haiku 4.5, three passes each. ``--budget`` stops the run after the
pass that would take it over, so a run never spends more than its budget plus one pass.

Batch 303 (Craig's go, 2 Oct 2026: up to $5) re-ran it for the reader's v2 prompt on
the production model only: 125 cases, two passes, $2.23.

From the repo root, with production's key:

    PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python \
        scripts/run_notes_eval.py run --model claude-sonnet-5 --passes 3 --budget 3.5

    PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/run_notes_eval.py report

``run`` writes ``apps/api/tests/fixtures/notes_eval_recorded/<model>.json``; CI scores the
production model's recording against the gate (``services.notes_eval``). ``report``
renders every recording into ``docs/reviews/notes-reader-eval-<date>.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.services.notes_eval import (
    gate_failures,
    load_cases,
    recorded_passes,
    render_report,
    score_pass,
    stale_recording_reason,
)
from src.services.notes_reader import (
    PROMPT_VERSION,
    AnthropicNotesReaderClient,
    prompt_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "apps/api/tests/fixtures/notes_eval_2026_09.json"
RECORD_DIR = ROOT / "apps/api/tests/fixtures/notes_eval_recorded"

#: What happened before the recorded runs, kept in the report so it is not overstated.
HISTORY: tuple[str, ...] = (
    "**Batch 297, 30 Sep 2026: the v1 prompt.** A 2-cent smoke (2 notes per model) "
    "confirmed both models answer the strict schema.",
    "The first Sonnet 5 run (3 passes, $2.53) missed H04 and H43 on 2 and 3 passes: it read "
    '"since yesterday" as past, because the prompt defined earlier as "before last night". '
    "The prompt now says a symptom still going on is now, however long ago it started. Its "
    'examples name "since yesterday", the phrase in both misses, so those two cases are no '
    "longer unseen. Nothing else changed.",
    "The recorded runs below are after that fix. Total spend on the eval: $4.89 of Craig's $5.",
    "Both models caught every red flag. Haiku 4.5 set no floor for H07 (chest tightness on "
    "the stairs) on either pass, only the question, where Sonnet 5 set the chest floor; "
    "and its real-note false alarms sat at the limit on both passes.",
    "**Batch 303, 2 Oct 2026: the v2 prompt.** Breathlessness that is unusual for him joins "
    "the chest flag, with two rules for what is not one (his breathing exercises, and "
    "breathing hard in a hard effort). 25 cases were added and confirmed by Craig before "
    "the run: 15 on breathlessness (B01-B15) and 10 held out (X01-X10), written after the "
    "prompt was frozen.",
    "A 2-cent smoke (B02 and B08) confirmed the v2 prompt answers the schema. The recorded "
    "run is the first and only v2 run: Sonnet 5, 2 passes, $2.23. The prompt was not changed "
    "after it. Total spend on this re-run: $2.25 of Craig's $5.",
    "Every red flag was caught on both passes, the 10 new ones included. B03 (woke gasping "
    "in the night) set the chest floor on one pass and only asked on the other; since Batch "
    "303 that question also eases a hard session until he answers. The two real notes that "
    "mention his breathing exercises (R33, R42) stayed quiet on both passes, and the "
    "real-note false alarms are the same two notes as under v1 (R29, R35).",
    "One held-out note raised a question it should not have, on one pass of two: X07, a "
    "stitch in his side on a walk, read as a possible chest symptom. The prompt was not "
    "changed to fit it. One tap of None on Home clears it.",
    "Haiku 4.5 was not re-run: it is not the production model. Its v1 recording is kept and "
    "named below, not scored.",
)

#: US dollars per million tokens, in and out (docs/claude-api-review.md, 31 Aug 2026).
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


async def run(
    model: str, passes: int, budget: float, concurrency: int, reasoning: str
) -> None:
    cases = load_cases(FIXTURE)
    price_in, price_out = PRICES[model]
    results: dict[str, list[Any]] = {case.id: [] for case in cases}
    ledger = {"inputTokens": 0, "outputTokens": 0, "costUsd": 0.0}
    gate = asyncio.Semaphore(concurrency)

    async def one(case_id: str, text: str) -> Any:
        async with gate:
            client = AnthropicNotesReaderClient(
                model_name=model, use_configured_reasoning=reasoning == "configured"
            )
            try:
                outcome: Any = await client.read(text)
            except Exception as exc:  # noqa: BLE001 — record the failure, keep going
                outcome = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            usage = client.last_usage
            tokens_in = int(usage.get("input_tokens") or 0)
            tokens_out = int(usage.get("output_tokens") or 0)
            ledger["inputTokens"] += tokens_in
            ledger["outputTokens"] += tokens_out
            ledger["costUsd"] += (
                tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
            )
            return outcome

    done = 0
    for index in range(passes):
        outcomes = await asyncio.gather(*(one(case.id, case.text) for case in cases))
        for case, outcome in zip(cases, outcomes, strict=True):
            results[case.id].append(outcome)
        done = index + 1
        per_pass = ledger["costUsd"] / done
        print(f"pass {done}: ${ledger['costUsd']:.2f} so far (${per_pass:.2f} a pass)")
        if ledger["costUsd"] + per_pass > budget and done < passes:
            print(f"stopping: another pass would pass the ${budget:.2f} budget")
            break

    recording = {
        "model": model,
        "promptVersion": PROMPT_VERSION,
        # Batch 307: the words this run was sent, so CI can tell when they change.
        "promptSha256": prompt_sha256(),
        "reasoning": reasoning,
        "passes": done,
        "recordedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "usage": {**ledger, "costUsd": round(float(ledger["costUsd"]), 4)},
        "cases": results,
    }
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    out = RECORD_DIR / f"{model}.json"
    out.write_text(json.dumps(recording, indent=1, ensure_ascii=False) + "\n")
    scores = [score_pass(cases, readings) for readings in recorded_passes(recording)]
    failures = gate_failures(scores)
    print(f"wrote {out.relative_to(ROOT)}; gate {'met' if not failures else 'NOT MET'}")
    for failure in failures:
        print(f"  {failure}")


def report() -> None:
    cases = load_cases(FIXTURE)
    labelled_by = str(json.loads(FIXTURE.read_text(encoding="utf-8"))["labelledBy"])
    runs = []
    not_rerun = []
    for path in sorted(RECORD_DIR.glob("*.json")):
        recording = json.loads(path.read_text(encoding="utf-8"))
        # Batch 303: a recording answers the prompt it was made under. One made under
        # an earlier prompt is named in the report, not scored against today's cases.
        if stale_recording_reason(recording) is not None:
            not_rerun.append(recording)
            continue
        runs.append(
            (
                recording,
                [
                    score_pass(cases, readings)
                    for readings in recorded_passes(recording)
                ],
            )
        )
    now = datetime.now(UTC)
    text = render_report(
        cases,
        runs,
        generated=now.strftime("Generated %-d %b %Y %H:%M UTC"),
        history=HISTORY,
        labelled_by=labelled_by,
        not_rerun=not_rerun,
    )
    out = ROOT / f"docs/reviews/notes-reader-eval-{now:%Y-%m-%d}.md"
    out.write_text(text + "\n")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--model", required=True, choices=sorted(PRICES))
    run_parser.add_argument("--passes", type=int, default=3)
    run_parser.add_argument("--budget", type=float, required=True)
    run_parser.add_argument("--concurrency", type=int, default=5)
    run_parser.add_argument(
        "--reasoning", choices=("configured", "none"), default="configured"
    )
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(
            run(args.model, args.passes, args.budget, args.concurrency, args.reasoning)
        )
    else:
        report()
