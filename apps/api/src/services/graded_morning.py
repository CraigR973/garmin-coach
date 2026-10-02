"""A morning is stored when it is graded; its written brief arrives later (Batch 302).

The colour, the floors, the plan lines and the ride changes are deterministic and are
worked out before the paid call. They used to be stored only if that call succeeded: on
21 Jul 2026 Mark checked in at 08:35 UTC and had no colour until 18:07, on a Red day,
because Anthropic's credit had run out.

So the ``morning`` row is now written first, with its prose empty, and the brief is
written into it. Every reader of the colour reads the row as before; a reader of the
prose asks :func:`brief_is_written` first.

This is a leaf: the envelope, the chat and the coach's read tool all need the test, and
none of them should import the morning service to get it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

#: ``analyses.output_markdown`` before the brief is written. The column is ``NOT NULL``,
#: so "not written yet" is the empty string, as the monthly analyst's pending row is.
BRIEF_NOT_WRITTEN = ""

#: Where a written brief's own time is kept in ``raw_response``. ``generated_at_utc`` is
#: when the morning was graded and first shown, and never moves.
BRIEF_WRITTEN_AT_KEY = "briefWrittenAtUtc"

__all__ = [
    "BRIEF_NOT_WRITTEN",
    "BRIEF_WRITTEN_AT_KEY",
    "brief_is_written",
    "brief_written_at",
    "stamp_brief_written_at",
]


class _HasProse(Protocol):
    @property
    def output_markdown(self) -> str: ...


def brief_is_written(analysis: _HasProse | None) -> bool:
    """Does this stored morning carry its written brief?"""

    return analysis is not None and bool((analysis.output_markdown or "").strip())


def stamp_brief_written_at(raw_response: dict[str, Any], *, now: datetime | None = None) -> None:
    """Record when the brief was written, beside the provider's response."""

    written = now or datetime.now(UTC).replace(tzinfo=None)
    raw_response[BRIEF_WRITTEN_AT_KEY] = written.replace(microsecond=0).isoformat() + "Z"


def brief_written_at(raw_response: Any) -> str | None:
    """When the brief was written, or ``None`` for a brief stored before Batch 302."""

    value = raw_response.get(BRIEF_WRITTEN_AT_KEY) if isinstance(raw_response, dict) else None
    return value if isinstance(value, str) else None
