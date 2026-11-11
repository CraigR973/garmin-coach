"""Batch 308 — the ladder goes.

The rule ladder that set the morning colour until Batch 296, its v50 prompt and the
``VERDICT_ENGINE`` switch are deleted. What these tests pin:

* the brief's prompt is v61's text exactly, now written out as its own instead of being
  built at import by rewriting the ladder's (CR327-03), so no version moved;
* nothing in the code still names the ladder's colour path or the switch;
* the morning packet's verdict is an allow-list: a field reaches the packet, the brief
  and the coach only when it is named (CR327-03);
* a morning stored before the switch still renders (308.3), read as the ladder left it;
* the replay still reads those mornings, compares the graded verdict with what Mark was
  shown, and every rule switch it can force still works (308.3, Decision #449).
"""

from __future__ import annotations

import ast
import hashlib
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings, settings
from src.models.coaching import Analysis
from src.services import morning_analysis, morning_verdict
from src.services.age_norms import REM_FRAMING_RULE
from src.services.daily_loop_envelope import _serialize_analysis
from src.services.executable_coaching import MorningContext, morning_ir
from src.services.morning_verdict import (
    CONTEXT_FIELDS,
    graded_verdict_packet,
    verdict_context,
)
from src.services.todays_call import todays_call
from src.services.verdict_grading import (
    ENGINE_LADDER,
    GradingInputs,
    grade,
    stored_actions,
    stored_engine,
)
from src.services.verdict_scaling import adjust_ir_for_verdict
from src.services.workout_delivery import build_structured_workout_ir
from src.tools.verdict_replay import (
    FORCEABLE_RULES,
    RULE_FLAGS,
    ReplayReport,
    floor_violations,
    render_markdown,
    render_rule_comparison,
)
from tests.test_batch_295_verdict_grading import _load_fixture, _replayed
from tests.test_executable_coaching import ENDURANCE_STRUCTURED, _planned_workout
from tests.test_morning_verdict import _graded_packet, _metric, _sleep

SRC = Path(__file__).resolve().parents[1] / "src"

#: SHA-256 of the brief's system prompt at v61, as ``main`` built it from the ladder's
#: v50 before this batch (``_graded_system_prompt(LADDER_SYSTEM_PROMPT)``).
V61_PROMPT_SHA256 = "d561a8e1fa1e9e27d5729ecadc79d9af6a02a63729a11f54c8a0ff6b3d5c0f1a"

#: A morning stored before the switch (29 Sep 2026's shape): the ladder's colour and its
#: working, no engine, no graded section. Stored mornings are never rewritten.
PRE_SWITCH_PACKET: dict[str, Any] = {
    "plannedWorkouts": [
        {"id": "w-1", "workoutType": "bike_sweet_spot", "status": "planned", "title": "SS"}
    ],
    "restDay": {"isRestDay": False},
    "verdict": {
        "status": "Amber",
        "reasons": ["Garmin readiness is Low without complete recovery evidence."],
        "planAdjustments": ["Cut the bike to 45 min; hold Zone 2, ease harder intervals."],
        "readinessInterpretation": None,
        "hrvGradedResponse": {"tier": "ease"},
        "trainingLoadCap": {"triggered": False, "applied": False},
        "sleepCreditCeiling": {"applied": False},
        "cumulativeEscalation": {"applied": False},
        "acutePhysiology": {
            "status": "clear",
            "statusBeforeCap": "Amber",
            "statusAfterCap": "Amber",
            "verdictCapApplied": False,
            "requiresBikeRest": False,
            "requiresTrainingRest": False,
            "escalations": [],
        },
        "isRestDay": False,
    },
}


# -- the prompt --------------------------------------------------------------------------


V61_READINESS_LINE = (
    "When verdict.readinessBaselineTrend triggers, state plainly that his usual readiness\n"
    """over the last six weeks has fallen below the six weeks before and never hide, soften,
or argue down that deterministic warning. It does not set the colour itself or
grant permission to train."""
)


V61_STAGE_LINE = (
    "stage in ageComparison.sleepRows sits inside its healthy age band, describe it as\n"
    "healthy for the user's age rather than repeating Garmin's young-adult flag (e.g.\n"
    '"Deep 17% is within the healthy 50-59 range; Garmin only flags it against a younger\n'
    'target").'
)


#: Batch 369 (v67): the mild-signal line and the graded rule's lead, which the replays
#: copied into his brief ("one domain signal", "your autonomic, sleep, load or feel domains").
V61_MILD_SIGNAL_LINE = (
    "is one domain signal the\n"
    "graded verdict has already counted: never call it a cap, and never say it caps the day\n"
    "on its own."
)
V67_MILD_SIGNAL_LINE = (
    "is, on its own, one thing a\n"
    "little off that today's call already counts: never call it a cap, and never say it caps\n"
    "the day on its own."
)
V61_GRADED_LEAD = (
    "records them, then the mechanism, and never count a\n"
    "domain the packet does not flag. Readiness"
)
V67_GRADED_LEAD = (
    "records them, each said as what it measures (his HRV\n"
    "and resting heart rate, his sleep, his training load, how he feels) and never as a domain\n"
    "or as autonomic; then the mechanism; and never count a domain the packet does not flag.\n"
    "Readiness"
)


#: Batch 370.3 (v69) put the blood-pressure kind into SYMPTOM_FOLLOW_THROUGH_RULE.
V69_BLOOD_PRESSURE_KIND = (
    "Kind blood_pressure means his blood pressure on this morning's\n"
    "check-in was very high (acutePhysiology.bloodPressure): the hard session is an easy ride and\n"
    "the app's notice asks him to speak to his GP or 111 today; say so in one sentence, in the\n"
    "app's own words (easing.reason), and never explain the reading away (the cuff, coffee,\n"
    "nerves or white-coat). "
)


#: Batch 384 (v70) put the tomorrow rule in after the "Your question" rule.
V70_TOMORROW_RULE = (
    "tomorrowsPlannedWorkouts holds the sessions the plan has for tomorrow, in the same form\n"
    "as plannedWorkouts. It is there to answer a question about tomorrow and never changes\n"
    "today's call, colour or plan: do not bring tomorrow up unless he asks. When Mark's\n"
    "check-in asks about tomorrow's session (swapping it, moving it, how hard it is), answer\n"
    'from tomorrowsPlannedWorkouts, under the same "**Your question**" heading. If it is\n'
    "empty, say you have no session planned for tomorrow. Never say that what you were given\n"
    "holds only today's sessions.\n"
)


#: Batch 386 (v71) reworded the app's own words out of the prompt: (v71 text, v70 text).
V71_REWORDS = (
    ("Green held as planned\n(verdict.held)", "Green with the targets held\n(verdict.held)"),
    (
        "When no domain is flagged, say that nothing is flagged or nothing is out of the ordinary;\n"
        'never "marked off".\n',
        "",
    ),
    (
        "otherwise ride it as planned, at its planned power and\nlength), move_test (an",
        "otherwise ride it with the targets held), move_test (an",
    ),
    (
        "the session stays as planned, at its planned power and\nlength), recovery",
        "the session stays as planned, targets held), recovery",
    ),
    (
        '`precool_credited`, tell him the cooling before bed worked, in plain words ("the\n'
        'room cooled well before bed"), even though it stopped above targetPreCoolC. Never say\n'
        '"credited", "credit" or "a miss" about it.',
        "`precool_credited`, explicitly credit that cooling and do not call the pre-cool\n"
        "a miss merely because it stopped above targetPreCoolC.",
    ),
    (
        "each active experiment. Each one's plain.summary is the app's own plain sentence for it,\n"
        "the one the Experiments page shows: say that, in those words, for the experiment line,\n"
        "and add nothing about ranges, correlations or confidence. When plain.summary is null,\n"
        'give only the experiment\'s title and that it is still being watched. Never say "gate" or\n'
        '"gated" about an experiment. Report a supported or refuted result when relevant; never\n'
        "invent a direction. Never auto-conclude an experiment: every conclusion is Mark's to make.\n"
        "The app already derives REM minutes,",
        "each active experiment. Report a supported or refuted result when relevant; for\n"
        "an inconclusive or insufficient result, state the first supplied reason and the\n"
        "coverage still needed rather than inventing a direction. Never auto-conclude an\n"
        "experiment: every conclusion is human-gated. The app already derives REM minutes,",
    ),
    (
        "planned, at its planned power and length, not to soften it.",
        "planned with its targets held, not to soften it.",
    ),
)


def test_the_brief_prompt_is_v61s_text_byte_for_byte() -> None:
    # Batch 317 moved the brief to v62 by adding one rule (HRV_USUAL_RULE), and Batch 339
    # to v63 by adding another (SYMPTOM_ANYWHERE_RULE); Batches 318 and 320 (v64,
    # v65) moved only the contract in the user prompt. Without the two rules the prompt is still
    # v61's text, byte for byte.
    assert morning_analysis.PROMPT_VERSION == "morning-analysis-v71-2026-11-11"
    # Batch 364 (v66) added a third (FEVER_FOLLOW_UP_RULE).
    # Batch 386 (v71): the app's own words reworded out of the rules; undone first, because
    # the lines below match v70's text.
    v70 = morning_analysis.SYSTEM_PROMPT
    for new, old in V71_REWORDS:
        assert new in v70, new
        v70 = v70.replace(new, old, 1)
    v61 = (
        v70.replace(f"\n{morning_analysis.HRV_USUAL_RULE}", "", 1)
        .replace(f"\n{morning_analysis.SYMPTOM_ANYWHERE_RULE}", "", 1)
        .replace(f"\n{morning_analysis.FEVER_FOLLOW_UP_RULE}", "", 1)
        # Batch 369 (v67) rewrote the readiness-trend line in place.
        .replace(morning_analysis.READINESS_TREND_RULE, V61_READINESS_LINE, 1)
        # Batch 369.3 (v67) gave the brief its own REM and stage rules.
        .replace(morning_analysis.MORNING_REM_RULE, REM_FRAMING_RULE, 1)
        .replace(morning_analysis.MORNING_STAGE_RULE, V61_STAGE_LINE, 1)
        # Batch 369 (v67): no engine words for the brief to copy.
        .replace(V67_MILD_SIGNAL_LINE, V61_MILD_SIGNAL_LINE, 1)
        .replace(V67_GRADED_LEAD, V61_GRADED_LEAD, 1)
        # Batch 370.3 (v69): the blood-pressure easing kind.
        .replace(V69_BLOOD_PRESSURE_KIND, "", 1)
        # Batch 384 (v70): the tomorrow rule.
        .replace(V70_TOMORROW_RULE, "", 1)
    )
    assert hashlib.sha256(v61.encode()).hexdigest() == V61_PROMPT_SHA256
    # The packet records the prompt it was written under, so a stored morning matches it.
    digest = hashlib.sha256(morning_analysis.SYSTEM_PROMPT.encode()).hexdigest()
    assert morning_analysis.prompt_system_hash(morning_analysis.SYSTEM_PROMPT) == digest


# -- nothing names the ladder's colour path or the switch --------------------------------

#: Code names (not comments or history) that belonged to the ladder's colour path.
LADDER_NAMES = frozenset(
    {
        "VERDICT_ENGINE",
        "verdict_engine",
        "LADDER_SYSTEM_PROMPT",
        "LADDER_PROMPT_VERSION",
        "GRADED_SYSTEM_PROMPT",
        "GRADED_PROMPT_VERSION",
        "_GRADED_PROMPT_REPLACEMENTS",
        "_graded_system_prompt",
        "LADDER_ONLY_FIELDS",
        "LADDER_ONLY_ACUTE_FIELDS",
        "LADDER_MORNING_FLOORS",
        "LADDER_MILD_SIGNAL_CLOSING",
        "LADDER_EITHER_ALONE_CLAUSE",
        "LADDER_BELOW_FLOOR",
        "LADDER_AMBER_CONSTRAINT",
        "LADDER_RED_CONSTRAINT",
        "HRV_GRADED_RESPONSE_RULE",
        "graded_acute_physiology",
        "_log_verdict_engines",
        "KIND_VERDICT_LESS_CAUTIOUS",
        "_training_load_cap",
        "_sleep_credit_ceiling",
        "_soft_sleep_recovery_override",
        "_hrv_hold_concern",
        "_plan_adjustments",
        "_verdict_adjustment_packet",
    }
)


def _code_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def test_no_source_file_names_the_ladders_colour_path() -> None:
    found = {
        str(path.relative_to(SRC)): sorted(_code_names(path) & LADDER_NAMES)
        for path in SRC.rglob("*.py")
    }
    assert {path: names for path, names in found.items() if names} == {}


def test_the_setting_is_gone() -> None:
    assert "verdict_engine" not in Settings.model_fields
    assert not hasattr(settings, "verdict_engine")
    for name in ("VERDICT_ENGINE", "LADDER_SYSTEM_PROMPT", "GRADED_SYSTEM_PROMPT"):
        assert not hasattr(morning_analysis, name)
    assert not hasattr(morning_verdict, "morning_verdict")


# -- the packet is an allow-list ----------------------------------------------------------


def test_the_verdict_packet_carries_exactly_the_named_fields() -> None:
    context = verdict_context(
        daily_metric=_metric(),
        sleep=_sleep(),
        age_adjusted_sleep_score=82,
        manual_entries=[],
        planned_workouts=[],
    )
    packet = _graded_packet(context, [])

    assert set(packet) == {
        *CONTEXT_FIELDS,
        "acutePhysiology",
        "engine",
        "status",
        "held",
        "reasons",
        "planAdjustments",
        "safetyRulesApplied",
        "graded",
    }
    # Something a caller adds to the context stays out unless it is named.
    leaky = {**context, "someNewWorking": {"rule": "x"}}
    graded = grade(GradingInputs(subject_date=date(2026, 9, 2), acute=context["acutePhysiology"]))
    assert "someNewWorking" not in graded_verdict_packet(leaky, graded, [], breathwork_line=None)
    # The packet's acute rail is its own copy, not the context's.
    assert packet["acutePhysiology"] == context["acutePhysiology"]
    assert packet["acutePhysiology"] is not context["acutePhysiology"]


# -- a morning stored before the switch still renders (308.3) ----------------------------


def test_a_pre_switch_packet_still_renders_as_the_ladder_left_it() -> None:
    assert stored_engine(PRE_SWITCH_PACKET) == ENGINE_LADDER
    assert stored_actions(PRE_SWITCH_PACKET) == {}

    # Home's call reads the ladder's own rule for each live session.
    call = todays_call(PRE_SWITCH_PACKET)
    assert (call.reading, call.key) == ("some_fatigue", "take_the_edge_off")

    # The delivery rail gives its ride the ladder's Amber, as on the day.
    ride = _planned_workout(ENDURANCE_STRUCTURED)
    context = MorningContext(status="Amber", graded=False, actions={})
    ir = build_structured_workout_ir(ride, ftp_watts=280)
    assert morning_ir(ir, context, ride, companion_session=False) == adjust_ir_for_verdict(
        ir, "Amber"
    )

    # The daily loop serialises it unchanged: no engine, not held.
    analysis = Analysis(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        analysis_type="morning",
        subject_date=date(2026, 9, 29),
        generated_at_utc=datetime(2026, 9, 29, 6, 30),
        created_at=datetime(2026, 9, 29, 6, 30),
        prompt_version="morning-analysis-v50-2026-09-28",
        verdict="Amber",
        context_packet=PRE_SWITCH_PACKET,
        output_markdown="read",
        raw_response={},
    )
    out = _serialize_analysis(analysis)
    assert out is not None
    assert out.verdictEngine is None
    assert out.verdictHeld is False


# -- the replay still reads old mornings (308.3, Decision #449) ---------------------------


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _load_fixture()


@pytest.fixture(scope="module")
def replayed(fixture: dict[str, Any]) -> dict[date, Any]:
    return _replayed(fixture)


def test_the_replay_reads_every_pre_switch_morning_against_what_he_was_shown(
    replayed: dict[date, Any],
) -> None:
    mornings = [replayed[day] for day in sorted(replayed)]
    assert len(mornings) == 14
    for morning in mornings:
        # Stored before the switch: shown by the ladder, not judged as drift.
        assert morning.shown_engine is None
        assert morning.reproduces_production is None
        assert morning.shown is not None
        assert morning.changed is (morning.shown_label != morning.graded_label)
        # The acute rail is recomputed through the morning's context, in today's words.
        assert morning.context["acutePhysiology"]["gradedWording"] is True
    report = ReplayReport(start=mornings[0].subject_date, end=mornings[-1].subject_date)
    report.mornings = mornings
    assert floor_violations(report) == []
    text = render_markdown(report, generated="Generated in a test")
    assert "### Shown → graded" in text
    assert "Ladder" not in text and "ladder →" not in text
    assert "Shown by the rule ladder, before the switch on 30 Sep 2026." in text


@pytest.mark.parametrize("rule", sorted(FORCEABLE_RULES))
def test_every_forceable_rule_still_replays_on_and_off(fixture: dict[str, Any], rule: str) -> None:
    """311's (a), (c), (d) and (e), 316's two rules, 336's and the rest (Decision #449)."""
    on = _replayed(fixture, rules_on={rule})
    off = _replayed(fixture, rules_off={rule})
    days = sorted(on)
    text = render_rule_comparison(
        ReplayReport(start=days[0], end=days[-1], mornings=[on[day] for day in days]),
        ReplayReport(start=days[0], end=days[-1], mornings=[off[day] for day in days]),
        rules_off={rule},
    )
    assert RULE_FLAGS[rule] in text
    assert "- **Floors, with the rule:** " in text
    assert "Ladder (the rollback)" not in text


def test_the_named_rules_cover_311_316_and_336() -> None:
    assert {
        "readiness_skips_fair_night_on_low_hrv",
        "readiness_confirms_load_only",
        "readiness_never_confirms",
        "hrv_normal_leaves_out_judged_week",
        "load_ratio_from_high",
        "recovery_time_counts_on_hard_days",
        "test_moved_not_eased",
    } <= FORCEABLE_RULES
