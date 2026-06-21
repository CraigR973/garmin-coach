"""VO2 progression toolkit — selectable interval protocols for the Tue VO2 day.

Batch 14 (14.3) makes the VO2 progression a single, inspectable toolkit so both
the plan seed (``coaching_state``) and the dynamic weekly restructurer agree on
which protocol a given build week should use.

The headline protocol is **Rønnestad 30/15** (Decision #33): the best-evidenced,
age-appropriate VO2max progression of his Tuesday VO2 day. Its documented
constraints are encoded here so the emitted workout always carries them:

  * used in **build weeks from ~Week 7 onward** (``RONNESTAD_FROM_WEEK``);
  * **ERG off** — the 30 s surges arrive faster than a smart trainer's ERG loop
    can react, so the rider holds power manually;
  * **even-paced ~105-110 % FTP** work with **15 s easy** floats between reps.

Earlier build weeks use the gentler 30/30 micro-interval. The emitted dict is the
same ``structured_workout`` shape stored on ``planned_workouts`` (and consumed by
``build_structured_workout_ir``); the extra ``vo2Protocol`` / ``ergMode`` keys are
metadata and are ignored by the delivery IR builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VO2_PROTOCOL_30_30 = "30/30"
VO2_PROTOCOL_RONNESTAD_30_15 = "ronnestad_30_15"

# Rønnestad 30/15 is a late-build progression — see Decision #33.
RONNESTAD_FROM_WEEK = 7

# Shared VO2 work target. Even-paced (not ramped) to match the protocol intent.
VO2_WORK_TARGET = "105-110% FTP"


@dataclass(frozen=True)
class Vo2Protocol:
    """A selectable VO2 interval protocol and the workout it emits."""

    key: str
    title: str
    main_repeats: int
    main_pattern: str
    erg_mode: str  # "off" for both micro-interval protocols (surge lag)
    intensity_target: str


_PROTOCOL_30_30 = Vo2Protocol(
    key=VO2_PROTOCOL_30_30,
    title="VO2 Max 30/30",
    main_repeats=3,
    main_pattern="5x 30s on / 30s off",
    erg_mode="off",
    intensity_target="105-110% FTP, ERG off",
)
_PROTOCOL_RONNESTAD_30_15 = Vo2Protocol(
    key=VO2_PROTOCOL_RONNESTAD_30_15,
    title="VO2 Max Ronnestad 30/15",
    main_repeats=3,
    main_pattern="13x 30s on / 15s easy",
    erg_mode="off",
    intensity_target="105-110% FTP even-paced, 15s easy, ERG off",
)


def select_vo2_protocol(week_number: int, *, block_type: str = "build") -> Vo2Protocol:
    """Choose the VO2 protocol for a build week.

    Build weeks from ``RONNESTAD_FROM_WEEK`` onward progress to Rønnestad 30/15;
    earlier weeks stay on the gentler 30/30. Non-build blocks fall back to 30/30
    — taper/consolidation sharpeners are defined by their own block templates.
    """
    if block_type == "build" and week_number >= RONNESTAD_FROM_WEEK:
        return _PROTOCOL_RONNESTAD_30_15
    return _PROTOCOL_30_30


def build_vo2_structured_workout(
    week_number: int,
    *,
    block_type: str = "build",
) -> dict[str, Any]:
    """Return the ``structured_workout`` dict for a build week's VO2 session."""
    protocol = select_vo2_protocol(week_number, block_type=block_type)
    return {
        "format": "bike",
        "vo2Protocol": protocol.key,
        "ergMode": protocol.erg_mode,
        "steps": [
            {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
            {
                "label": "Main set",
                "repeats": protocol.main_repeats,
                "pattern": protocol.main_pattern,
                "target": VO2_WORK_TARGET,
            },
            {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
        ],
    }
