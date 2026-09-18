"""Deterministic periodisation audit shared by plan import and weekly review.

The canonical 13-week shape is deliberately advisory for imported plans. Mark
authors those plans, so a divergence is evidence to surface, never a reason to
rewrite or reject his schedule. Reviewed plan JSON may acknowledge a deliberate
divergence; the acknowledgement is durable provenance, not a bypass flag.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

BLOCK_SEQUENCE = [
    "build",
    "build",
    "recovery",
    "build",
    "build",
    "recovery",
    "build",
    "build",
    "recovery",
    "build",
    "build",
    "consolidation",
    "taper",
]

ACKNOWLEDGEMENTS_KEY = "periodisation_acknowledgements"

_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
}


@dataclass(frozen=True, slots=True)
class PeriodisationAcknowledgement:
    code: str
    confirmed_by: str
    confirmed_on: str
    reason: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PeriodisationAcknowledgement:
        fields = {
            name: str(value.get(name, "")).strip()
            for name in ("code", "confirmed_by", "confirmed_on", "reason")
        }
        missing = [name for name, field_value in fields.items() if not field_value]
        if missing:
            raise ValueError(
                "periodisation acknowledgement requires non-empty " + ", ".join(missing)
            )
        try:
            date.fromisoformat(fields["confirmed_on"])
        except ValueError as exc:
            raise ValueError(
                "periodisation acknowledgement confirmed_on must be an ISO date"
            ) from exc
        return cls(
            code=fields["code"],
            confirmed_by=fields["confirmed_by"],
            confirmed_on=fields["confirmed_on"],
            reason=fields["reason"],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "confirmed_by": self.confirmed_by,
            "confirmed_on": self.confirmed_on,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class BuildRun:
    start_week: int
    end_week: int
    length_weeks: int

    def contains(self, week_number: int) -> bool:
        return self.start_week <= week_number <= self.end_week


@dataclass(frozen=True, slots=True)
class PeriodisationDivergence:
    code: str
    week_number: int
    expected_block_type: str
    actual_block_type: str
    summary: str
    acknowledgement: PeriodisationAcknowledgement | None = None

    @property
    def acknowledged(self) -> bool:
        return self.acknowledgement is not None

    def to_packet(self) -> dict[str, object]:
        return {
            "code": self.code,
            "weekNumber": self.week_number,
            "expectedBlockType": self.expected_block_type,
            "actualBlockType": self.actual_block_type,
            "acknowledged": self.acknowledged,
            "acknowledgement": (
                self.acknowledgement.to_dict() if self.acknowledgement is not None else None
            ),
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class PeriodisationAudit:
    divergences: tuple[PeriodisationDivergence, ...]
    long_build_runs: tuple[BuildRun, ...]
    acknowledgements: tuple[PeriodisationAcknowledgement, ...]

    @property
    def unacknowledged_divergences(self) -> tuple[PeriodisationDivergence, ...]:
        return tuple(item for item in self.divergences if not item.acknowledged)

    def to_packet(self, *, focus_week_number: int | None) -> dict[str, object]:
        focus_run = next(
            (
                run
                for run in self.long_build_runs
                if focus_week_number is not None and run.contains(focus_week_number)
            ),
            None,
        )
        focus_packet: dict[str, object] | None = None
        if focus_run is not None and focus_week_number is not None:
            position = focus_week_number - focus_run.start_week + 1
            length_word = _NUMBER_WORDS.get(focus_run.length_weeks, str(focus_run.length_weeks))
            focus_packet = {
                "startWeek": focus_run.start_week,
                "endWeek": focus_run.end_week,
                "lengthWeeks": focus_run.length_weeks,
                "position": position,
                "summary": (
                    f"This is week {position} of an unbroken {length_word}-week build run "
                    f"(weeks {focus_run.start_week}–{focus_run.end_week})."
                ),
            }
        return {
            "status": "divergent" if self.divergences else "conforming",
            "canonicalPattern": "2 build / 1 recovery",
            "canonicalMaxBuildWeeks": _canonical_max_build_run(),
            "divergences": [item.to_packet() for item in self.divergences],
            "longBuildRuns": [
                {
                    "startWeek": run.start_week,
                    "endWeek": run.end_week,
                    "lengthWeeks": run.length_weeks,
                }
                for run in self.long_build_runs
            ],
            "focusWeekNumber": focus_week_number,
            "focusBuildRun": focus_packet,
        }


def divergence_code(*, week_number: int, expected: str, actual: str) -> str:
    return f"week-{week_number}-{actual}-instead-of-{expected}"


def _canonical_max_build_run() -> int:
    longest = current = 0
    for block_type in BLOCK_SEQUENCE:
        if block_type == "build":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _build_runs(actual_by_week: Mapping[int, str]) -> tuple[BuildRun, ...]:
    runs: list[BuildRun] = []
    start: int | None = None
    previous: int | None = None
    for week_number in sorted(actual_by_week):
        block_type = actual_by_week[week_number]
        consecutive = previous is not None and week_number == previous + 1
        if block_type == "build":
            if start is None or not consecutive:
                if start is not None and previous is not None:
                    runs.append(BuildRun(start, previous, previous - start + 1))
                start = week_number
        elif start is not None and previous is not None:
            runs.append(BuildRun(start, previous, previous - start + 1))
            start = None
        previous = week_number
    if start is not None and previous is not None:
        runs.append(BuildRun(start, previous, previous - start + 1))
    return tuple(runs)


def _parse_acknowledgements(
    values: Sequence[Mapping[str, Any]],
) -> tuple[PeriodisationAcknowledgement, ...]:
    return tuple(PeriodisationAcknowledgement.from_mapping(value) for value in values)


def audit_plan_periodisation(
    weeks: Sequence[tuple[int, str]],
    *,
    acknowledgements: Sequence[Mapping[str, Any]] = (),
) -> PeriodisationAudit:
    """Compare a reviewed sequence with the canonical shape without gating it."""

    actual_by_week = {int(week): str(block_type).lower() for week, block_type in weeks}
    parsed_acknowledgements = _parse_acknowledgements(acknowledgements)
    acknowledgements_by_code = {item.code: item for item in parsed_acknowledgements}
    build_runs = _build_runs(actual_by_week)
    long_build_runs = tuple(
        run for run in build_runs if run.length_weeks > _canonical_max_build_run()
    )

    divergences: list[PeriodisationDivergence] = []
    for week_number, expected in enumerate(BLOCK_SEQUENCE, start=1):
        actual = actual_by_week.get(week_number)
        if actual is None or actual == expected:
            continue
        code = divergence_code(week_number=week_number, expected=expected, actual=actual)
        containing_run = next(
            (run for run in long_build_runs if run.contains(week_number)),
            None,
        )
        if expected == "recovery" and actual == "build" and containing_run is not None:
            summary = (
                f"Week {week_number} is a build week where the 2121 slate has recovery. "
                f"That makes weeks {containing_run.start_week}–{containing_run.end_week} "
                f"{_NUMBER_WORDS.get(containing_run.length_weeks, containing_run.length_weeks)} "
                "unbroken build weeks."
            )
        else:
            summary = f"Week {week_number} is {actual}, while the 2121 slate has {expected}."
        divergences.append(
            PeriodisationDivergence(
                code=code,
                week_number=week_number,
                expected_block_type=expected,
                actual_block_type=actual,
                summary=summary,
                acknowledgement=acknowledgements_by_code.get(code),
            )
        )

    return PeriodisationAudit(
        divergences=tuple(divergences),
        long_build_runs=long_build_runs,
        acknowledgements=parsed_acknowledgements,
    )
