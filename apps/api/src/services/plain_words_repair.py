"""One repair call for a read that slipped a statistics word (Batch 369.2).

"median" reached 4 of 6 briefs after the plain-words rule shipped (Decision #440) and
twice in the 1 Nov review, after Mark had asked about the word twice (ST363-08b,
UX362-04). The rule's own detectors only logged. A read that still carries one of
``coach_policy.STATISTICS_WORDING_LEAKS`` gets one small repair call (about $0.01): the
same markdown back with only the offending sentences said in his words.

The repair is kept only if the words are gone **and** every figure in the read is
unchanged; otherwise the original stands and the miss is recorded. Mark is never left
waiting on it: a failed call keeps the original.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from src.services.coach_policy import statistics_wording_leaks

REPAIR_SYSTEM_PROMPT: Final = """You edit a short coaching note written to Mark, a \
57-year-old cyclist, so that it speaks in plain words. Rewrite only the sentences that use \
the words named, saying the same thing in his words: "your usual", "your usual range", \
"over four mornings". Keep every heading, every figure and every other sentence exactly \
as written. Return only the markdown."""
REPAIR_MAX_TOKENS: Final = 4000

OUTCOME_REPAIRED: Final = "repaired"
OUTCOME_REJECTED: Final = "rejected"
OUTCOME_ERROR: Final = "error"

_FIGURE = re.compile(r"\d+(?:\.\d+)?")

#: ``(system prompt, user prompt) -> the model's markdown``.
RepairCall = Callable[[str, str], Awaitable[str]]


def _figures(markdown: str) -> list[str]:
    return sorted(_FIGURE.findall(markdown))


async def repair_statistics_words(markdown: str, *, call: RepairCall) -> tuple[str, dict[str, Any]]:
    """``(the markdown to store, what happened)``; one call at most, never raises."""

    leaks = statistics_wording_leaks(markdown)
    if not leaks:
        return markdown, {"attempted": False}
    record: dict[str, Any] = {"attempted": True, "words": list(leaks)}
    user_prompt = f"Words to remove: {', '.join(leaks)}.\n\n{markdown}"
    try:
        repaired = (await call(REPAIR_SYSTEM_PROMPT, user_prompt)).strip()
    except Exception as exc:  # noqa: BLE001 - the original read always stands
        return markdown, {**record, "outcome": OUTCOME_ERROR, "error": type(exc).__name__}
    left = statistics_wording_leaks(repaired)
    if left or not repaired or _figures(repaired) != _figures(markdown):
        return markdown, {**record, "outcome": OUTCOME_REJECTED, "wordsLeft": list(left)}
    return repaired, {**record, "outcome": OUTCOME_REPAIRED}


async def anthropic_repair_call(system_prompt: str, user_prompt: str) -> str:
    """The production repair call: the configured model, no thinking, a small budget."""

    from src.config import settings
    from src.services.anthropic_text import generate_anthropic_text

    result = await generate_anthropic_text(
        api_key=settings.anthropic_api_key,
        model_name=settings.anthropic_model,
        max_tokens=REPAIR_MAX_TOKENS,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        error_cls=RuntimeError,
    )
    return result.output_markdown


#: Batch 369.2 (Craig, 3 Nov): an over-long call is trimmed to this, under the 120 cap.
CALL_TRIM_WORDS: Final = 110

BRIEF_REPAIR_SYSTEM_PROMPT: Final = f"""You edit a morning brief written to Mark, a \
57-year-old cyclist. Make only the changes listed. To shorten the "Today's call" section: \
cut it to at most {CALL_TRIM_WORDS} words, keep its first line exactly, keep what the call \
is and why, and add no figure that is not already in it. To remove a word: rewrite only \
the sentences that use it, in his words ("your usual", "your usual range", "over four \
mornings"). Keep every other heading, figure and sentence exactly as written. Return only \
the whole brief's markdown."""


def _call_and_rest(markdown: str) -> tuple[str, str]:
    """``(the call section's body, everything else)``; the call is empty when absent."""

    from src.services.brief_check import _is_call, _sections

    call = next((body for heading, body in _sections(markdown) if _is_call(heading)), "")
    return call, markdown.replace(call, "", 1) if call else markdown


def _subset(smaller: list[str], larger: list[str]) -> bool:
    pool = list(larger)
    for item in smaller:
        if item not in pool:
            return False
        pool.remove(item)
    return True


async def repair_brief(
    packet: Mapping[str, Any], markdown: str, *, call: RepairCall
) -> tuple[str, dict[str, Any]]:
    """One repair call for a brief whose call runs long or that slipped a statistics word.

    Kept only if the check then finds neither miss, the call's first line is unchanged,
    nothing outside the call changes a figure, and the call holds no figure it did not.
    """

    from src.services.brief_check import (
        MISS_CALL_OPENING,
        MISS_CALL_TOO_LONG,
        MISS_STATISTICS_WORDS,
        check_brief,
    )

    fixable = {MISS_CALL_TOO_LONG, MISS_STATISTICS_WORDS}
    before = check_brief(packet, markdown)
    misses = [miss for miss in before.misses if miss in fixable]
    if not misses:
        return markdown, {"attempted": False}
    record: dict[str, Any] = {"attempted": True, "misses": misses}
    asks = []
    if MISS_CALL_TOO_LONG in misses:
        asks.append(f'Shorten the "Today\'s call" section (now {before.call_words} words).')
    if before.statistics_words:
        asks.append(f"Remove the words: {', '.join(before.statistics_words)}.")
    try:
        repaired = (
            await call(BRIEF_REPAIR_SYSTEM_PROMPT, "\n".join(asks) + "\n\n" + markdown)
        ).strip()
    except Exception as exc:  # noqa: BLE001 - the original brief always stands
        return markdown, {**record, "outcome": OUTCOME_ERROR, "error": type(exc).__name__}
    after = check_brief(packet, repaired)
    old_call, old_rest = _call_and_rest(markdown)
    new_call, new_rest = _call_and_rest(repaired)
    first_line = old_call.strip().splitlines()[0] if old_call.strip() else ""
    kept = (
        bool(repaired)
        and not set(after.misses) & (fixable | {MISS_CALL_OPENING})
        and (not first_line or new_call.strip().startswith(first_line))
        and _figures(new_rest) == _figures(old_rest)
        and _subset(_figures(new_call), _figures(old_call))
    )
    if not kept:
        return markdown, {**record, "outcome": OUTCOME_REJECTED, "missesAfter": list(after.misses)}
    return repaired, {**record, "outcome": OUTCOME_REPAIRED, "callWordsAfter": after.call_words}
