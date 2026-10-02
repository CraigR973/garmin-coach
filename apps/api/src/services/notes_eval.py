"""The notes reader's eval: labelled cases, scored by what the app would do (Batch 297).

Each case is one note with Craig's labels (``tests/fixtures/notes_eval_2026_09.json``).
A reading is scored by its *effects* through the production mapping
(:func:`services.notes_reader.reading_effects`), not field by field: a symptom that sets
a floor, a question Home asks, a notch on his feel. That is what reaches Mark.

The gate (297.4, the thresholds Craig confirmed with the labels on 30 Sep 2026):

* every red-flag case is caught on every pass: a floor, or at least the question;
* at most two of the 56 real notes raise a floor or a question the key does not, on
  every pass, so he is not asked every week;
* no floor for someone else's symptom or one that is past.

``scripts/run_notes_eval.py`` makes the paid run and records every response; CI scores
the recordings with this module and holds the gate. Pure: no database, no model call.

Batch 303 re-ran it for the reader's v2 prompt (breathlessness joins the chest flag)
with 15 new hard cases, and with 10 held-out cases brought forward from Batch 307.3:
written after the prompt was frozen, never used to change it, and reported on their
own. A held-out red flag the reader misses still fails the gate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from src.services.notes_reader import (
    CAUSES,
    FLAGS,
    SYMPTOM_FLAGS,
    reading_effects,
)

MAX_REAL_FALSE_ALARMS: Final = 2

SOURCE_REAL: Final = "real"
SOURCE_HARD: Final = "hard"
#: Written after the prompt was frozen and never used to change it (Batch 307.3).
SOURCE_HELD_OUT: Final = "held_out"


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    source: str
    text: str
    labels: Mapping[str, Mapping[str, Any]]
    date: str | None = None


@dataclass(frozen=True, slots=True)
class Effects:
    floor: str | None
    ask: bool
    notch: bool

    @property
    def acts(self) -> bool:
        """The app does something about it: a floor or a question."""
        return self.floor is not None or self.ask


def load_cases(path: Path) -> list[EvalCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvalCase(
            id=str(item["id"]),
            source=str(item["source"]),
            text=str(item["text"]),
            labels=dict(item.get("labels") or {}),
            date=item.get("date"),
        )
        for item in data["cases"]
    ]


def full_reading(labels: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """A complete reading from a case's labels: everything unlisted is absent."""

    reading: dict[str, Any] = {}
    for name in FLAGS:
        label = labels.get(name)
        reading[name] = (
            {
                "state": label["state"],
                "who": label.get("who", "him"),
                "when": label.get("when", "now"),
                "words": "",
            }
            if label
            else {"state": "absent", "who": "unknown", "when": "unknown", "words": ""}
        )
    for name in CAUSES:
        label = labels.get(name)
        reading[name] = (
            {"state": "present", "when": label.get("when", "now"), "words": ""}
            if label
            else {"state": "absent", "when": "unknown", "words": ""}
        )
    return reading


def effects_of(reading: Mapping[str, Any] | None) -> Effects:
    """What the app does with one reading; a failed reading does nothing."""

    if reading is None:
        return Effects(floor=None, ask=False, notch=False)
    effects = reading_effects(reading)
    return Effects(
        floor=effects.symptom_answer,
        ask=effects.ask_symptom_question,
        notch=effects.feel_notch > 0,
    )


def expected_effects(case: EvalCase) -> Effects:
    return effects_of(full_reading(case.labels))


def _someone_elses_or_past(case: EvalCase) -> bool:
    """A symptom the key gives to someone else, or to him before last night."""

    symptoms = [case.labels.get(name) for name in SYMPTOM_FLAGS]
    labelled = [label for label in symptoms if label]
    return bool(labelled) and all(
        label.get("who") == "someone_else" or label.get("when") == "earlier" for label in labelled
    )


@dataclass(slots=True)
class PassScore:
    red_flags: list[str] = field(default_factory=list)
    missed_red_flags: list[str] = field(default_factory=list)
    floor_class_mismatches: list[str] = field(default_factory=list)
    real_false_alarms: list[str] = field(default_factory=list)
    hard_false_alarms: list[str] = field(default_factory=list)
    missed_asks: list[str] = field(default_factory=list)
    wrong_person_floors: list[str] = field(default_factory=list)
    notch_disagreements: list[str] = field(default_factory=list)
    failed_readings: list[str] = field(default_factory=list)
    #: Held-out cases, and those where the app would not do what the key says.
    held_out: list[str] = field(default_factory=list)
    held_out_wrong: list[str] = field(default_factory=list)


def score_pass(
    cases: Sequence[EvalCase], readings: Mapping[str, Mapping[str, Any] | None]
) -> PassScore:
    """One pass: each case's recorded reading against its key."""

    score = PassScore()
    for case in cases:
        reading = readings.get(case.id)
        if reading is None:
            score.failed_readings.append(case.id)
        expected = expected_effects(case)
        observed = effects_of(reading)
        if expected.floor is not None:
            score.red_flags.append(case.id)
            if not observed.acts:
                score.missed_red_flags.append(case.id)
            elif observed.floor != expected.floor:
                score.floor_class_mismatches.append(case.id)
        if not expected.acts and observed.acts:
            (score.real_false_alarms if case.source == "real" else score.hard_false_alarms).append(
                case.id
            )
        if expected.ask and expected.floor is None and not observed.acts:
            score.missed_asks.append(case.id)
        if _someone_elses_or_past(case) and observed.floor is not None:
            score.wrong_person_floors.append(case.id)
        if expected.notch != observed.notch:
            score.notch_disagreements.append(case.id)
        if case.source == SOURCE_HELD_OUT:
            score.held_out.append(case.id)
            if (observed.floor, observed.ask) != (expected.floor, expected.ask):
                score.held_out_wrong.append(case.id)
    return score


def gate_failures(scores: Sequence[PassScore]) -> list[str]:
    """Why a run fails the gate, pass by pass; empty when it passes."""

    failures: list[str] = []
    if not scores:
        return ["no passes recorded"]
    for index, score in enumerate(scores, start=1):
        if score.missed_red_flags:
            failures.append(f"pass {index}: missed red flags {score.missed_red_flags}")
        if len(score.real_false_alarms) > MAX_REAL_FALSE_ALARMS:
            failures.append(
                f"pass {index}: {len(score.real_false_alarms)} real-note false alarms "
                f"{score.real_false_alarms} (at most {MAX_REAL_FALSE_ALARMS})"
            )
        if score.wrong_person_floors:
            failures.append(
                f"pass {index}: a floor for someone else or the past {score.wrong_person_floors}"
            )
    return failures


def recorded_passes(recording: Mapping[str, Any]) -> list[dict[str, Mapping[str, Any] | None]]:
    """``[{case id: reading or None}]`` per pass, from a recording file's ``cases``."""

    cases = recording.get("cases") or {}
    passes = int(recording.get("passes") or 0)
    out: list[dict[str, Mapping[str, Any] | None]] = [{} for _ in range(passes)]
    for case_id, attempts in cases.items():
        for index in range(passes):
            attempt = attempts[index] if index < len(attempts) else None
            out[index][case_id] = (
                attempt if isinstance(attempt, Mapping) and "error" not in attempt else None
            )
    return out


def _exact(score: PassScore) -> int:
    """Red flags given exactly the key's floor."""
    return len(score.red_flags) - len(score.floor_class_mismatches) - len(score.missed_red_flags)


def render_report(
    cases: Sequence[EvalCase],
    runs: Sequence[tuple[Mapping[str, Any], Sequence[PassScore]]],
    *,
    generated: str,
    history: Sequence[str] = (),
    labelled_by: str = "Craig on 30 Sep 2026",
    not_rerun: Sequence[Mapping[str, Any]] = (),
) -> str:
    """The committed eval report: one section per model run, then every disagreement.

    ``not_rerun`` are recordings made under an earlier prompt. They are named, not
    scored: their responses answer a prompt the reader no longer sends.
    """

    lines: list[str] = []
    add = lines.append
    real = sum(1 for case in cases if case.source == SOURCE_REAL)
    held_out = sum(1 for case in cases if case.source == SOURCE_HELD_OUT)
    hard = len(cases) - real - held_out
    red = [case.id for case in cases if expected_effects(case).floor is not None]
    add("# Notes reader eval")
    add("")
    held_out_part = (
        f", and {held_out} held out (written after the prompt was frozen)" if held_out else ""
    )
    add(
        f"{generated} · {len(cases)} cases: {real} of Mark's real morning notes, {hard} "
        f"hand-written hard cases{held_out_part}. Labelled by {labelled_by}."
    )
    add("")
    add(
        "**The gate:** every red-flag case caught on every pass (a floor, or at least the "
        f"question); at most {MAX_REAL_FALSE_ALARMS} of the {real} real notes raise a floor "
        "or a question the key does not; no floor for someone else's symptom or a past one."
    )
    add("")
    add(f"Red-flag cases ({len(red)}): {', '.join(red)}.")
    add("")
    if history:
        add("## How this run was reached")
        add("")
        for line in history:
            add(f"- {line}")
        add("")
    for recording, scores in runs:
        failures = gate_failures(scores)
        usage = recording.get("usage") or {}
        add(f"## {recording.get('model')} ({recording.get('reasoning', 'configured')} reasoning)")
        add("")
        add(f"- **Gate:** {'met' if not failures else 'NOT MET'}")
        for failure in failures:
            add(f"  - {failure}")
        add(f"- **Passes:** {len(scores)}")
        add(
            "- **Red flags caught:** "
            + ", ".join(
                f"{len(score.red_flags) - len(score.missed_red_flags)} of {len(score.red_flags)}"
                for score in scores
            )
        )
        add(
            "- **Floor class exact:** "
            + ", ".join(f"{_exact(score)} of {len(score.red_flags)}" for score in scores)
        )
        add(
            "- **Real-note false alarms:** "
            + "; ".join(
                f"{len(score.real_false_alarms)} {score.real_false_alarms or ''}".strip()
                for score in scores
            )
        )
        add(
            "- **Hard-case false alarms:** "
            + "; ".join(
                f"{len(score.hard_false_alarms)} {score.hard_false_alarms or ''}".strip()
                for score in scores
            )
        )
        add(
            "- **Missed questions:** "
            + "; ".join(
                f"{len(score.missed_asks)} {score.missed_asks or ''}".strip() for score in scores
            )
        )
        add(
            "- **Feel-notch disagreements:** "
            + "; ".join(
                f"{len(score.notch_disagreements)} {score.notch_disagreements or ''}".strip()
                for score in scores
            )
        )
        add(
            "- **Failed readings:** "
            + "; ".join(str(len(score.failed_readings)) for score in scores)
        )
        if any(score.held_out for score in scores):
            add(
                "- **Held-out cases as keyed:** "
                + "; ".join(
                    (
                        f"{len(score.held_out) - len(score.held_out_wrong)} of "
                        f"{len(score.held_out)} {score.held_out_wrong or ''}"
                    ).strip()
                    for score in scores
                )
            )
        if usage:
            add(
                f"- **Cost:** ${float(usage.get('costUsd') or 0):.2f} "
                f"({int(usage.get('inputTokens') or 0):,} tokens in, "
                f"{int(usage.get('outputTokens') or 0):,} out)"
            )
        add("")
    if not_rerun:
        add("## Not re-run under this prompt")
        add("")
        for recording in not_rerun:
            add(
                f"- {recording.get('model')}: recorded under "
                f"`{recording.get('promptVersion')}` on {recording.get('recordedAt')}, and not "
                "scored here. It answers a prompt the reader no longer sends."
            )
        add("")
    return "\n".join(lines)
