"""A repair call's reply wrapped whole in one code block is stored as the markdown inside it
(Decision #501).

On 10 Nov 2026 a ride read's repair call (Batch 382) took out "packet" and sent the read back
as "```markdown … ```". Every check passed (no word left, every figure unchanged), so it was
stored as it came, and the page showed the whole read as raw markdown in a code box. The
behaviour cases failed on ``main`` first. Invented wording throughout.
"""

from __future__ import annotations

import pytest

from src.services.plain_words_repair import (
    OUTCOME_REJECTED,
    OUTCOME_REPAIRED,
    repair_brief,
    repair_internal_words,
    repair_statistics_words,
)
from tests.test_batch_318_brief_leads import GOOD, PACKET
from tests.test_batch_369_plain_words import LEAKY as LEAKY_STATISTICS
from tests.test_batch_382_internal_words import LEAKY as LEAKY_BRIEF
from tests.test_batch_382_internal_words import LEAKY_RIDE, RIDE, RIDE_PACKET, _call

#: 369's repair of its leaky read: the same figures, the word said plainly.
FIXED_STATISTICS = "## Today's call\nEasy spin.\n\nYour readiness is usually 63, against 74 before."


def _fenced(text: str, info: str = "markdown") -> str:
    """``text`` as the 10 Nov reply came: a fence line first and a closing fence last."""

    return f"```{info}\n{text.strip()}\n```"


# -- every repair stores the markdown, not the code block ----------------------------------


async def test_the_post_session_repair_stores_the_read_not_the_code_block() -> None:
    _seen, call = _call(_fenced(RIDE))
    text, record = await repair_internal_words(LEAKY_RIDE, RIDE_PACKET, call=call)
    assert (text, record["outcome"]) == (RIDE, OUTCOME_REPAIRED)
    assert record.get("unfenced") is True


async def test_the_statistics_repair_stores_the_read_not_the_code_block() -> None:
    _seen, call = _call(_fenced(FIXED_STATISTICS))
    text, record = await repair_statistics_words(LEAKY_STATISTICS, call=call)
    assert (text, record["outcome"]) == (FIXED_STATISTICS, OUTCOME_REPAIRED)
    assert record.get("unfenced") is True


async def test_the_brief_repair_stores_the_brief_not_the_code_block() -> None:
    _seen, call = _call(_fenced(GOOD))
    text, record = await repair_brief(PACKET, LEAKY_BRIEF, call=call)
    assert (text, record["outcome"]) == (GOOD.strip(), OUTCOME_REPAIRED)
    assert record.get("unfenced") is True


async def test_a_reply_without_a_code_block_is_recorded_as_before() -> None:
    _seen, call = _call(RIDE)
    text, record = await repair_internal_words(LEAKY_RIDE, RIDE_PACKET, call=call)
    assert (text, record["outcome"]) == (RIDE, OUTCOME_REPAIRED)
    assert "unfenced" not in record


async def test_the_markdown_inside_still_has_to_pass_every_check() -> None:
    # The words are still there inside the fence: the original stands.
    _seen, call = _call(_fenced(LEAKY_RIDE))
    text, record = await repair_internal_words(LEAKY_RIDE, RIDE_PACKET, call=call)
    assert (text, record["outcome"]) == (LEAKY_RIDE, OUTCOME_REJECTED)
    # A figure changed inside the fence: the original stands.
    _seen, call = _call(_fenced(RIDE.replace("3.1%", "3.8%")))
    text, record = await repair_internal_words(LEAKY_RIDE, RIDE_PACKET, call=call)
    assert (text, record["outcome"], record["figuresChanged"]) == (
        LEAKY_RIDE,
        OUTCOME_REJECTED,
        True,
    )


# -- only a wrapper round the whole reply comes off ---------------------------------------


@pytest.mark.parametrize("info", ["markdown", "md", "", "Markdown", "markdown "])
def test_one_fence_round_the_whole_reply_comes_off(info: str) -> None:
    from src.services.plain_words_repair import unfenced

    assert unfenced(f"\n  {_fenced(RIDE, info)}  \n") == RIDE


@pytest.mark.parametrize(
    "reply",
    [
        # A code block inside the read stays where it is.
        "Before it.\n\n```\nnot a wrapper\n```\n\nAfter it.",
        # Two blocks one after the other are not one wrapper.
        "```markdown\nOne.\n```\n\n```markdown\nTwo.\n```",
        # Words outside the fence: the reply is not wholly inside it.
        "```markdown\n" + RIDE + "\n```\n\nA line after the fence.",
        "A line before the fence.\n\n```markdown\n" + RIDE + "\n```",
        # A fence for anything but markdown is left as it came.
        "```python\nprint('hello')\n```",
        # No closing fence.
        "```markdown\n" + RIDE,
    ],
)
def test_anything_else_is_only_stripped(reply: str) -> None:
    from src.services.plain_words_repair import unfenced

    assert unfenced(f"  {reply}\n\n") == reply
