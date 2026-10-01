"""Batch 301: the notice the web shows before a brief is the server's notice.

The 999, 111, GP and no-training notices reached Mark only inside the stored morning,
which is written only after the paid brief succeeds. In an Anthropic outage a "Chest or
heart" answer showed "Couldn't finish your brief" and no advice. The check-in screen and
the pre-brief card now show the answer's notice from
``apps/web/src/lib/symptomNotices.json``, because they must work when no brief, and so no
packet, exists.

That file is a copy, so this test keeps the server the one source of truth: for every
answer that sets a floor, the copy must equal what the acute rail itself writes into a
morning's escalations — the words, and the level that sets the card's heading. A reworded
notice in ``services/symptom_check.SYMPTOM_FLOORS`` fails here until the copy follows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.services.morning_verdict import _acute_physiology_rail
from src.services.symptom_check import SYMPTOM_ANSWERS, SYMPTOM_FLOORS, SYMPTOMS_NONE

WEB_LIB = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib"
WEB_NOTICES = WEB_LIB / "symptomNotices.json"
WEB_SYMPTOMS = WEB_LIB / "symptoms.ts"


def _web_notices() -> dict[str, Any]:
    notices: dict[str, Any] = json.loads(WEB_NOTICES.read_text(encoding="utf-8"))
    return notices


def _rail_escalations(answer: str) -> list[dict[str, Any]]:
    """The escalations the real acute rail writes for a tapped answer, data or none."""

    rail = _acute_physiology_rail(
        daily_metric=None,
        sleep=None,
        baselines={},
        recent_daily_metrics=[],
        recent_sleeps=[],
        symptom_answer=answer,
        symptom_source="tap",
    )
    return [escalation for escalation in rail["escalations"] if escalation["kind"] == "symptoms"]


def test_the_web_shows_the_servers_words_and_heading_for_every_floor_answer() -> None:
    server = {}
    for answer in SYMPTOM_ANSWERS:
        if answer not in SYMPTOM_FLOORS:
            continue
        [escalation] = _rail_escalations(answer)
        server[answer] = {"level": escalation["level"], "notice": escalation["message"]}

    assert _web_notices() == server


def test_the_web_lists_the_floor_answers_in_the_questions_order() -> None:
    assert list(_web_notices()) == [
        answer for answer in SYMPTOM_ANSWERS if answer in SYMPTOM_FLOORS
    ]


def test_none_sets_no_notice_on_either_side() -> None:
    assert SYMPTOMS_NONE not in _web_notices()
    assert _rail_escalations(SYMPTOMS_NONE) == []


def test_the_web_reads_its_notices_from_the_pinned_file() -> None:
    # A notice typed into a component instead would escape this test entirely.
    assert "import symptomNotices from './symptomNotices.json';" in WEB_SYMPTOMS.read_text(
        encoding="utf-8"
    )
