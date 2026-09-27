"""Batch 264 — the change a coach answer carries, without a database.

The DB-backed half of this lives in ``test_brief_chat.py``; these are the pure
decisions underneath it, which is where the 2026-09-08 failure actually was.
Nothing about that morning needed a database to go wrong: the coach composed
"2×10 min blocks of 35s work / 25s recovery at 125%" in prose, and the only
thing under the button was ``propose``, which rebuilds the stored session.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from src.services.brief_chat import (
    PROMPT_VERSION,
    PROPOSAL_MARKER_CLOSE,
    PROPOSAL_MARKER_OPEN,
    _capability_instruction,
    _extract_proposal,
    _proposed_change,
)
from src.services.interval_workout_editor import (
    EditableIntervalBlock,
    IntervalLeg,
    block_from_proposal,
    editable_snapshot_for,
    format_interval_block,
)

#: Mark's 2026-09-08 VO2 session exactly as ``plan_no2_import`` wrote it.
SEPTEMBER_EIGHTH_VO2: dict[str, object] = {
    "format": "bike",
    "summary": "WarmUp v1.3 · Main 2 × 10-rep blocks of 40s/20s @125% · CoolDown 10 min ramp",
    "steps": [
        {"label": "Warm-up ramp 55→80%", "ramp": [55, 80], "minutes": 10},
        {
            "label": "Primer 2×30s @100% / 55%",
            "target": "100%",
            "pattern": "2 x 30s / 30s @55%",
            "cadenceRpm": 95,
        },
        {"label": "Warm-up @72%", "target": "72%", "minutes": 3},
        {
            "label": "40s/20s @125% block 1",
            "target": "125%",
            "pattern": "10 x 40s / 20s @55%",
            "cadenceRpm": 95,
        },
        {"label": "Recover between blocks", "target": "60%", "minutes": 4},
        {
            "label": "40s/20s @125% block 2",
            "target": "125%",
            "pattern": "10 x 40s / 20s @55%",
            "cadenceRpm": 95,
        },
        {"label": "Cool-down ramp", "ramp": [70, 45], "minutes": 10},
    ],
}

INTENSITY = "VO₂ (see prescription)"


def _snapshot():  # type: ignore[no-untyped-def]
    snapshot = editable_snapshot_for(SEPTEMBER_EIGHTH_VO2, INTENSITY)
    assert snapshot is not None
    return snapshot


def _marker(payload: str) -> str:
    return f"{PROPOSAL_MARKER_OPEN}{payload}{PROPOSAL_MARKER_CLOSE}"


def _change(payload: str | None, snapshot=None):  # type: ignore[no-untyped-def]
    return _proposed_change(
        payload=payload,
        adjustable_set=_snapshot() if snapshot is None else snapshot,
        workout_id=uuid.UUID("1795a107-d43f-4985-a92e-f9f097842f28"),
        workout_version=1,
    )


def test_the_agreed_change_is_the_one_mark_asked_for() -> None:
    change = _change('{"repeat": 10, "workSec": 35, "workPct": 125, "restSec": 25, "restPct": 55}')

    assert change["status"] == "proposed"
    assert change["currentLabel"] == "10 × 40s/20s @ 125%/55%"
    assert change["changeToLabel"] == "10 × 35s/25s @ 125%/55%"
    assert change["matchingSets"] == 2
    assert change["heldConstant"] == [
        "Warm-up ramp 55→80%",
        "Primer 2×30s @100% / 55%",
        "Warm-up @72%",
        "Recover between blocks",
        "Cool-down ramp",
    ]


def test_cadence_is_carried_forward_rather_than_composed() -> None:
    """One fewer number for the model to invent.

    Every prescribed block already carries a cadence and Mark has never
    negotiated one in conversation, so it is not among the five numbers the
    coach may supply — it comes off the session it is changing.
    """
    change = _change('{"repeat": 10, "workSec": 35, "workPct": 125, "restSec": 25, "restPct": 55}')

    assert change["changeTo"]["work"]["cadenceRpm"] == 95
    assert change["current"]["work"]["cadenceRpm"] == 95


def _payload(**fields: int) -> str:
    numbers = {"repeat": 10, "workSec": 35, "workPct": 125, "restSec": 25, "restPct": 55}
    numbers.update(fields)
    return "{" + ", ".join(f'"{key}": {value}' for key, value in numbers.items()) + "}"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        # Above the editor's own 200% ceiling: a coach-composed change gets no
        # wider authority than a number Mark types into the editor himself.
        (_payload(workPct=260), "out_of_range"),
        (_payload(repeat=40), "out_of_range"),
        # Below the 10-second work floor Batch 263 set for the neuromuscular set.
        (_payload(workSec=4), "out_of_range"),
        ('{"repeat": 10, "workSec": 35, "workPct": 125}', "malformed"),
        ("{not json at all}", "malformed"),
        ("[1, 2, 3]", "malformed"),
        (None, "malformed"),
        # The session already prescribes this, so there is nothing to confirm.
        (_payload(workSec=40, restSec=20), "unchanged"),
    ],
)
def test_an_offer_the_app_cannot_carry_says_so(payload: str | None, reason: str) -> None:
    assert _change(payload) == {"status": "unavailable", "reason": reason}


def test_no_editable_session_means_no_offer_whatever_the_answer_claimed() -> None:
    assert _proposed_change(
        payload='{"repeat": 10, "workSec": 35, "workPct": 125, "restSec": 25, "restPct": 55}',
        adjustable_set=None,
        workout_id=None,
        workout_version=None,
    ) == {"status": "unavailable", "reason": "not_editable"}


def test_the_marker_never_reaches_mark_with_or_without_a_payload() -> None:
    payload = '{"repeat": 10, "workSec": 35, "workPct": 125, "restSec": 25, "restPct": 55}'
    carried, raw, offered = _extract_proposal(f"Confirm below.\n\n{_marker(payload)}")
    assert carried == "Confirm below."
    assert raw == payload
    assert offered is True

    # The v14 shape: a bare flag whose offer lived only in the prose above it.
    bare, raw_bare, offered_bare = _extract_proposal(
        "I'll get that queued up. [[PROPOSE_WORKOUT_ADJUSTMENT]]"
    )
    assert "PROPOSE_WORKOUT_ADJUSTMENT" not in bare
    assert raw_bare is None
    assert offered_bare is True

    plain, raw_plain, offered_plain = _extract_proposal("Seven hours, mostly unbroken.")
    assert plain == "Seven hours, mostly unbroken."
    assert raw_plain is None
    assert offered_plain is False


def test_the_capability_line_states_what_can_be_changed_and_what_cannot() -> None:
    instruction = _capability_instruction(_snapshot())

    assert "main interval set is 10 × 40s/20s @ 125%/55%" in instruction
    assert "repeats that set 2 times" in instruction
    assert "give the numbers for ONE set" in instruction
    assert "including cadence" in instruction
    assert "cannot move the session to another day" in instruction
    assert "repeats 1-20" in instruction
    assert "effort 10-7200 seconds" in instruction
    assert "both percentages 40-200" in instruction
    assert "never say you have queued, applied, changed, scheduled or uploaded" in instruction


def test_the_capability_line_refuses_outright_when_nothing_is_editable() -> None:
    instruction = _capability_instruction(None)

    assert "no session you can change today" in instruction
    assert "Do not say the app can propose, queue, confirm, upload, or change" in instruction
    assert "PROPOSE_WORKOUT_ADJUSTMENT" not in instruction


def test_a_single_set_session_does_not_claim_matching_siblings() -> None:
    single = {
        "format": "bike",
        "steps": [
            {"label": "Warm-up ramp", "ramp": [55, 80], "minutes": 10},
            {
                "label": "VO₂ 5×3min @119%",
                "target": "119%",
                "pattern": "5 x 180s / 210s @60%",
                "cadenceRpm": 95,
            },
            {"label": "Cool-down ramp", "ramp": [70, 45], "minutes": 10},
        ],
    }
    snapshot = editable_snapshot_for(single, "119% FTP intervals")
    assert snapshot is not None

    assert "matching" not in _capability_instruction(snapshot)
    assert (
        _change(
            '{"repeat": 6, "workSec": 180, "workPct": 119, "restSec": 210, "restPct": 60}',
            snapshot=snapshot,
        )["matchingSets"]
        == 1
    )


def test_a_session_with_no_bike_block_is_not_editable() -> None:
    assert editable_snapshot_for({"segments": []}, None) is None
    assert editable_snapshot_for(None, None) is None


def test_block_from_proposal_rejects_a_leg_the_editor_would_reject() -> None:
    current = EditableIntervalBlock(
        repeat=10,
        work=IntervalLeg(duration_sec=40, power_pct=125, cadence_rpm=95),
        rest=IntervalLeg(duration_sec=20, power_pct=55, cadence_rpm=None),
    )
    with pytest.raises(HTTPException):
        block_from_proposal(
            {"repeat": 10, "workSec": "thirty-five", "workPct": 125, "restSec": 25, "restPct": 55},
            current=current,
        )
    assert format_interval_block(current) == "10 × 40s/20s @ 125%/55%"


def test_the_prompt_version_moved_with_the_capability() -> None:
    """Batch 238/255's lesson: a capability the prompt does not name is closed.

    ``brief_chat`` is UNFILTERED in ``prompt_artifacts`` with no analysis types,
    so this bump withdraws no stored artifact — a past answer stays what was said.
    Batch 289 moved it again (v16), for the same reason and with the same contract.
    """
    assert PROMPT_VERSION == "coach-chat-v16-2026-09-26"
