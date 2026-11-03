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
from collections.abc import Awaitable, Callable
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
