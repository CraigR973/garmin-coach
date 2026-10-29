"""The morning brief's eval: stored mornings rewritten, scored by the brief's own check (318.4).

About ten stored graded mornings, chosen to cover different calls, are written again under
today's prompt and scored by :func:`services.brief_check.check_brief`, the check every
written brief now gets. The recording holds the scores, the usage and the prompt it
answered, **never the prose or the packets**: the repo is public and both carry Mark's
health data, so they stay in the git-ignored ``scratchpad/``.

As with the notes reader (Batch 307), the recording is pinned to the prompt it answered:
CI fails once the prompt's version, its system text or the call section's instruction
moves without a new run. Until the first run there is no recording, and CI says so
rather than failing: the run is paid and is Craig's go (``RUN_THE_EVAL``).

The gate (provisional, Decision #453): no case quotes a colour word or a figure the
morning does not hold, on any pass, and at least nine in ten cases pass every check.

Pure: no database, no model call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from src.services import morning_analysis
from src.services.brief_check import MISS_COLOUR_WORDS, MISS_UNKNOWN_FIGURES
from src.services.morning_output_contract import TODAYS_CALL_INSTRUCTION

RECORD_DIR: Final = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "brief_eval_recorded"
)
PRODUCTION_MODEL: Final = "claude-sonnet-5"

#: Misses that fail the gate on any case, on any pass.
HARD_MISSES: Final = frozenset({MISS_COLOUR_WORDS, MISS_UNKNOWN_FIGURES})
#: The share of cases that must pass every check on every pass.
MIN_CLEAN_SHARE: Final = 0.9

RUN_THE_EVAL: Final = (
    "Run the brief eval on the production model, which is paid and needs Craig's go: "
    "PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python "
    "scripts/run_brief_eval.py prepare, then cost (free), then run --go --budget <usd>, "
    "then report."
)


def prompt_fingerprint() -> str:
    """The words a run is sent that this eval answers for: system text and call instruction."""

    text = "\n\n".join(
        (morning_analysis.PROMPT_VERSION, morning_analysis.SYSTEM_PROMPT, TODAYS_CALL_INSTRUCTION)
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def recording_path(model: str = PRODUCTION_MODEL) -> Path:
    return RECORD_DIR / f"{model}.json"


def load_recording(model: str = PRODUCTION_MODEL) -> dict[str, Any] | None:
    path = recording_path(model)
    if not path.exists():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def stale_recording_reason(recording: Mapping[str, Any]) -> str | None:
    """Why a recording no longer answers the prompt the brief sends, or ``None``."""

    version = recording.get("promptVersion")
    if version != morning_analysis.PROMPT_VERSION:
        return (
            f"The recording was made under {version}, and the brief now sends "
            f"{morning_analysis.PROMPT_VERSION}."
        )
    if recording.get("promptFingerprint") != prompt_fingerprint():
        return "The prompt text has changed under the same version since the recording."
    return None


def gate_failures(recording: Mapping[str, Any]) -> list[str]:
    """What fails the gate, in words; empty when it holds."""

    cases = recording.get("cases")
    if not isinstance(cases, Mapping) or not cases:
        return ["The recording holds no cases."]
    failures: list[str] = []
    clean = 0
    for case_id, passes in sorted(cases.items()):
        results = [item for item in passes if isinstance(item, Mapping)] if passes else []
        misses = [set(item.get("misses") or ()) for item in results]
        if any("error" in item for item in results) or not results:
            failures.append(f"{case_id}: no answer on every pass.")
            continue
        hard = sorted(set().union(*misses) & HARD_MISSES)
        if hard:
            failures.append(f"{case_id}: {', '.join(hard)}.")
        if all(not found for found in misses):
            clean += 1
    if clean < MIN_CLEAN_SHARE * len(cases):
        failures.append(
            f"{clean} of {len(cases)} cases passed every check; at least "
            f"{MIN_CLEAN_SHARE:.0%} must."
        )
    return failures


def select_cases(mornings: Sequence[Mapping[str, Any]], count: int = 10) -> list[Mapping[str, Any]]:
    """About ``count`` stored mornings that cover different calls, newest first.

    ``mornings`` are newest first, each with ``todaysCall.key``. One of each call first,
    then the newest of the rest, so a run sees every state his recent mornings reached.
    """

    chosen: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for morning in mornings:
        key = str((morning.get("todaysCall") or {}).get("key") or "")
        if key not in seen:
            seen.add(key)
            chosen.append(morning)
        if len(chosen) >= count:
            return chosen
    for morning in mornings:
        if len(chosen) >= count:
            break
        if morning not in chosen:
            chosen.append(morning)
    return chosen


def estimated_cost_usd(input_tokens: int, output_tokens: int, prices: tuple[float, float]) -> float:
    """US dollars for one run, at ``prices`` (in, out) per million tokens."""

    price_in, price_out = prices
    return input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out
