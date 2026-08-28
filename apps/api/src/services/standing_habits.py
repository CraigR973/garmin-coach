"""Habits Mark already keeps, so the app stops asking about them (Batch 231).

The REM experiment compares nights an intervention was applied against nights it
was not, and needs at least :data:`experiment_evaluation.REM_MIN_PER_RESPONSE`
of each. A lever he *always* keeps can never accumulate a not-applied night, so
the question is asked every week and the experiment can never conclude. **A lever
he already complies with is not an intervention, it is a description.**

This is a deterministic, human-set knowledge-base section — not something the
coach infers. Batch 151's ``learned_context`` already holds model-extracted
statements, but Decision #228 defines those as quoted data that must never
change coaching logic, and in production it has stayed empty (no proposal has
ever been created). A habit that suppresses an issued lever is a coaching
decision, so it gets its own section that a human writes.

Shape::

    {"habits": [
        {"id": "rarely-drinks",
         "statement": "Rarely drinks — a couple of social occasions a year.",
         "interventionIds": ["alcohol_free_evenings"],
         "recordedOn": "2026-08-28",
         "source": "coach chat 2026-08-08"}
    ]}

Only ``interventionIds`` is load-bearing; the rest is provenance so a future
session can see why a lever stopped being offered and who said so.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SECTION = "standing_habits"


def standing_habits_content() -> dict[str, Any]:
    """The seeded default: nothing recorded, so nothing is suppressed."""
    return {"habits": []}


def complied_intervention_ids(section: Mapping[str, Any] | None) -> frozenset[str]:
    """Intervention ids Mark already keeps, so they are never issued as levers."""
    if not section:
        return frozenset()
    habits = section.get("habits")
    if not isinstance(habits, list):
        return frozenset()
    ids: set[str] = set()
    for habit in habits:
        if not isinstance(habit, Mapping):
            continue
        intervention_ids = habit.get("interventionIds")
        if not isinstance(intervention_ids, list):
            continue
        ids.update(item for item in intervention_ids if isinstance(item, str) and item.strip())
    return frozenset(ids)


def habit_statements(section: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The recorded habits in his own terms, for surfaces that explain a gap."""
    if not section:
        return ()
    habits = section.get("habits")
    if not isinstance(habits, list):
        return ()
    statements: list[str] = []
    for habit in habits:
        if not isinstance(habit, Mapping):
            continue
        statement = habit.get("statement")
        if isinstance(statement, str) and statement.strip():
            statements.append(statement.strip())
    return tuple(statements)
