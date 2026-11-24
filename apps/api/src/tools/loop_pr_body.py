"""Check a loop PR's body against its template (Batch 390.6, Decision #512).

The repo is public, so a pull request the self-improving loop opens (a ``claude/``
branch) must describe the fault in the app's own terms and never carry Mark's words or
figures. Its body follows ``.github/loop_pr_template.md``: the four headings in order,
an item id under ``## Item``, and no quoted text. CI runs this on ``claude/`` pull
requests with the body in ``PR_BODY``. Standard library only, so CI needs no install.

This catches structure and quoting, not paraphrase: the loop's own instructions (391)
carry the rule, and this is the backstop.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Sequence

HEADINGS: tuple[str, ...] = ("## Item", "## Fault", "## Change", "## Tests")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: A quoted run of six or more words, in straight or curly double quotes.
_QUOTED = re.compile(r"[\"“]([^\"”\n]+)[\"”]")
QUOTE_WORDS_MAX = 5


def problems(body: str) -> list[str]:
    """Every way ``body`` departs from the loop's template (empty means it passes)."""

    found: list[str] = []
    lines = body.replace("\r\n", "\n").split("\n")
    positions: list[int] = []
    for heading in HEADINGS:
        try:
            positions.append(next(i for i, line in enumerate(lines) if line.strip() == heading))
        except StopIteration:
            found.append(f"missing heading {heading!r}")
    if not found and positions != sorted(positions):
        found.append("headings out of order")
    if not found:
        item_lines = [
            line.strip()
            for line in lines[positions[0] + 1 : positions[1]]
            if line.strip() and not line.strip().startswith("<!--")
        ]
        if len(item_lines) != 1 or not _UUID.fullmatch(item_lines[0]):
            found.append("## Item must hold exactly one item id")
    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith(">"):
            found.append(f"line {number}: a block quote")
        for quoted in _QUOTED.findall(line):
            if len(quoted.split()) > QUOTE_WORDS_MAX:
                found.append(f"line {number}: a quoted passage")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    body = os.environ.get("PR_BODY", "")
    issues = problems(body)
    for issue in issues:
        print(f"loop PR body: {issue}")
    if not issues:
        print("loop PR body: follows the template")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
