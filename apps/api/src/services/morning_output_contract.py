"""Packet-derived structure for a complete morning brief (Batch 244)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MorningOutputSection:
    """One markdown section required by the evidence in a morning packet."""

    section_id: str
    heading: str
    instruction: str

    def to_packet(self) -> dict[str, str]:
        return {
            "id": self.section_id,
            "heading": self.heading,
            "instruction": self.instruction,
        }


_SLEEP_STAGE_FIELDS = {
    "remSleepMin": "REM",
    "deepSleepMin": "deep sleep",
    "lightSleepMin": "light sleep",
    "awakeSleepMin": "awake time",
}


def required_morning_output_sections(
    context_packet: Mapping[str, Any],
) -> tuple[MorningOutputSection, ...]:
    """Derive the output contract from the sections the packet actually carries.

    The old prompt named four sections permanently. That was correct when the
    packet had four jobs, then became a silent deletion instruction as experiment
    results and chronic actions were added. This contract grows and shrinks with
    the packet instead: a holiday packet with no bedroom review does not demand
    one, while a packet carrying active experiments cannot silently omit them.
    """

    sections: list[MorningOutputSection] = []
    sleep = _mapping(context_packet.get("sleep"))
    if sleep:
        stage_labels = [
            label for field, label in _SLEEP_STAGE_FIELDS.items() if sleep.get(field) is not None
        ]
        stage_instruction = ""
        if stage_labels:
            stage_instruction = (
                " Include the recorded stage detail for "
                + ", ".join(stage_labels)
                + "; do not collapse it into the total or score."
            )
        sections.append(
            MorningOutputSection(
                section_id="sleep_and_recovery",
                heading="Sleep and recovery",
                instruction=(
                    "Summarise last night's recorded sleep and recovery evidence."
                    f"{stage_instruction}"
                ),
            )
        )

    metrics = context_packet.get("metricsVsBaselines")
    if _non_empty_sequence(metrics):
        sections.append(
            MorningOutputSection(
                section_id="metrics_vs_baselines",
                heading="Metrics vs baselines",
                instruction="Compare the supplied current values with their supplied baselines.",
            )
        )

    environment = _mapping(context_packet.get("environment"))
    if environment.get("thermalReview") is not None:
        sections.append(
            MorningOutputSection(
                section_id="thermal_environment",
                heading="Thermal / environment",
                instruction="Explain the supplied sleep-period room and pre-cool evidence.",
            )
        )

    experiments = _mapping(context_packet.get("experimentLoop")).get("experiments")
    if _non_empty_sequence(experiments):
        sections.append(
            MorningOutputSection(
                section_id="experiment_update",
                heading="Experiment update",
                instruction=(
                    "Report the relevant deterministic experiment evaluations, including the "
                    "supplied reason and evidence still needed when a result is inconclusive."
                ),
            )
        )

    chronic_items = _mapping(context_packet.get("chronicSuggestions")).get("items")
    if _non_empty_sequence(chronic_items):
        sections.append(
            MorningOutputSection(
                section_id="chronic_pattern_actions",
                heading="Chronic pattern actions",
                instruction=(
                    "Explain each supplied chronic suggestion and include every action it carries; "
                    "do not invent or replace an action."
                ),
            )
        )

    if _mapping(context_packet.get("verdict")):
        sections.append(
            MorningOutputSection(
                section_id="todays_verdict",
                heading="Today's verdict",
                instruction=(
                    "State and explain the deterministic Green/Amber/Red workout verdict without "
                    "softening or relitigating it."
                ),
            )
        )

    return tuple(sections)


def morning_output_contract_packet(context_packet: Mapping[str, Any]) -> list[dict[str, str]]:
    """Serializable contract stored beside the other prompt metadata."""

    return [section.to_packet() for section in required_morning_output_sections(context_packet)]


def morning_output_contract_prompt(context_packet: Mapping[str, Any]) -> str:
    """Render exact, inspectable markdown requirements for the generation prompt."""

    sections = required_morning_output_sections(context_packet)
    lines = [
        "Required output contract:",
        "Include every section below in this order, using each exact `##` heading. Do not merge "
        "or omit a required section.",
    ]
    lines.extend(f"- `## {section.heading}`: {section.instruction}" for section in sections)
    return "\n".join(lines)


def missing_morning_output_sections(
    context_packet: Mapping[str, Any], output_markdown: str
) -> tuple[str, ...]:
    """Return required section ids absent from generated markdown.

    This is deliberately structural rather than an LLM judge. Exact headings are
    part of the generation contract, so the check is cheap, deterministic and
    suitable for an operator warning on every generation.
    """

    headings = {
        _normalize_heading(match.group("heading"))
        for match in re.finditer(
            r"^\s{0,3}#{1,6}\s+(?P<heading>.+?)\s*#*\s*$",
            output_markdown,
            flags=re.MULTILINE,
        )
    }
    missing: list[str] = []
    for section in required_morning_output_sections(context_packet):
        required = _normalize_heading(section.heading)
        if not any(actual == required or actual.startswith(f"{required} ") for actual in headings):
            missing.append(section.section_id)
    return tuple(missing)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _non_empty_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and bool(value)


def _normalize_heading(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold().replace("’", "'"))
    return " ".join(words)
