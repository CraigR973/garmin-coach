"""One policy surface for everything the coach says (Batch 179.5).

Until this batch there were N chats — one per document — and each one carried
its own copy of the rules. Copies drift. Now there is one conversation Mark can
open from anywhere, so there is one place the rules live, and every entry point
into that conversation is handed exactly the same text.

Batch 179.5 kickoff decision (`/batch-start`): **this module is the registry;
the conversation composes its prompt from it, and the deterministic read prompts
are checked against it rather than rewritten to import from it.**

The reason is that the reads are not interchangeable with each other. The
morning read states Red-never-VO2 and the power-balance floor because it
prescribes a ride; the walk, strength and mobility reads state neither, because
neither is applicable to a session with no power meter and no VO2 prescription.
Rewriting five version-pinned prompts to recite inapplicable rules would bump
every prompt version and change narrative behaviour on the deterministic reads
in a batch whose whole subject is the conversation surface. So:

* the coach conversation is **composed** from :data:`FLOORS` and the rules
  below — one prompt, therefore identical from the morning brief, the Week
  sheet, Sleep, or a cold "just ask the coach" open;
* the read prompts are **audited** against :func:`missing_floors`, which fails
  if a floor a read already states is later dropped or reworded away from the
  canonical sentence.

The audit boundary is deliberate. ``brief_chat`` calls the model but composes
every floor below directly, so it is checked by composition rather than by
recognising paraphrases. ``conversation_learning`` also calls the model, but its
output is non-user-facing, schema-bounded, deterministically filtered, and held
for explicit confirmation before it can enter memory. The deterministic speech
in ``state_change_coach`` and ``nudge_alerts`` does not call a model at all: those
modules render fixed templates and are covered by their own output tests, not by
a prompt audit. Keeping those dispositions beside the registry stops a grep for
version constants being mistaken for a list of unaudited prompts.

Nothing here can move the deterministic Green/Amber/Red ladder. These are
constraints on what the coach may *say*; the verdict is computed elsewhere and
the model never owns it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Batch 178.1: the words the app uses about itself. The pre-178 prompt said
# "packet" eight times and told the model to say when the packet could not
# answer, so Mark was told his question was not "in the packet". These never
# reach him.
INTERNAL_VOCABULARY = (
    "context packet",
    "packet",
    "json",
    "schema",
    "database field",
    "context block",
    "data structure",
)


def internal_vocabulary_hits(text: str) -> tuple[str, ...]:
    """Internal nouns present in user-facing text.

    Batch 178.1 fixed the leak at its source — the prompt no longer gives the
    model this wording — and this makes the contract checkable: over the prompt
    itself, over every string the coach can put in front of Mark, and over a
    stored answer.
    """
    lowered = text.lower()
    return tuple(term for term in INTERNAL_VOCABULARY if term in lowered)


@dataclass(frozen=True)
class Floor:
    """One safety floor, plus how to recognise it in a prompt that states it.

    ``sentence`` is the canonical wording the conversation is given.
    ``pattern`` matches the equivalent statement in a deterministic read
    prompt, which phrases it in its own voice ("Never keep VO2 work on a Red
    verdict") — the audit is about the rule surviving, not the phrasing
    matching character for character.
    """

    key: str
    sentence: str
    pattern: re.Pattern[str]
    negative_control: str


_CLAUSE = r"[^.;:]{0,240}"


def _same_clause_pattern(*requirements: str) -> re.Pattern[str]:
    """Require all semantic fragments inside one clause.

    Topic adjacency is not a rule: ``Red`` and ``VO2`` appearing near each
    other says nothing about whether VO2 is prohibited. Each requirement is a
    regex fragment and all of them must occur before the next clause boundary.
    """

    assertions = "".join(rf"(?={_CLAUSE}{requirement})" for requirement in requirements)
    return re.compile(assertions + _CLAUSE, re.IGNORECASE)


FLOORS: tuple[Floor, ...] = (
    Floor(
        key="never_vo2_on_red",
        sentence="never recommend VO2 on a Red day",
        pattern=_same_clause_pattern(
            r"\bvo2\b",
            r"\bred\b",
            r"\b(?:never|do not|don't|must not|cannot|can't)\s+"
            r"(?:recommend|keep|prescribe|allow|retain)\b",
        ),
        negative_control="On a Red day, VO2 intervals are absolutely fine.",
    ),
    Floor(
        key="no_power_balance",
        sentence="never reference left/right power balance",
        pattern=_same_clause_pattern(
            r"\bleft/right power balance\b",
            r"\b(?:never|do not|don't|must not|cannot|can't)\s+"
            r"(?:mention|reference|use|discuss)\b",
        ),
        negative_control="Use left/right power balance to judge the session.",
    ),
    Floor(
        key="local_clock_times",
        sentence="state any clock times in Mark's local timezone (never UTC)",
        pattern=re.compile(
            r"(?=[^.]{0,220}\blocal (?:clock )?time(?:zone)?\b)"
            r"(?=[^.]{0,220}\b(?:never|do not|don't|must not)\b[^.]{0,60}\butc\b)"
            r"[^.]{0,220}",
            re.IGNORECASE,
        ),
        negative_control="State clock times in UTC rather than Mark's local time.",
    ),
    Floor(
        key="no_skipped_as_live",
        sentence="never narrate a skipped or holiday workout as if it were live training",
        pattern=_same_clause_pattern(
            r"\b(?:skipped|holiday)\b",
            r"\b(?:live training|executed|completed)\b",
            r"\b(?:never|do not|don't|must not|cannot|can't)\s+"
            r"(?:narrate|credit|treat|describe|call)\b",
        ),
        negative_control="Narrate a skipped workout as completed live training.",
    ),
    Floor(
        key="recorded_data_honesty",
        sentence=(
            "treat every app figure as what the app recorded, not as independently verified "
            "truth about Mark; if Mark says his own device shows a different observed value, "
            "acknowledge the discrepancy, use his device reading as the better evidence, and "
            "treat it as a data-quality problem, while keeping every deterministic verdict, "
            "safety floor, and propose/confirm decision intact"
        ),
        pattern=re.compile(
            r"what the app recorded.*own device.*better evidence.*deterministic",
            re.IGNORECASE | re.DOTALL,
        ),
        negative_control=(
            "Treat every app figure as independently verified truth even when Mark's own "
            "device shows a different value."
        ),
    ),
    Floor(
        key="training_load_cap",
        sentence=(
            "explain verdict.trainingLoadCap when it applies and never soften or argue "
            "down its deterministic ceiling"
        ),
        pattern=_same_clause_pattern(
            r"\btrainingLoadCap\b",
            r"\bnever\b[^.;:]{0,60}\b(?:soften|argue)\b",
        ),
        negative_control=(
            "verdict.trainingLoadCap is conservative, so argue down its deterministic ceiling."
        ),
    ),
    Floor(
        key="sleep_credit_ceiling",
        sentence=(
            "explain verdict.sleepCreditCeiling when it applies and never soften or argue "
            "down its deterministic ceiling"
        ),
        pattern=_same_clause_pattern(
            r"\bsleepCreditCeiling\b",
            r"\bnever\b[^.;:]{0,60}\b(?:soften|argue)\b",
        ),
        negative_control=("verdict.sleepCreditCeiling is only guidance and may be argued down."),
    ),
    Floor(
        key="cumulative_escalation",
        sentence=(
            "explain verdict.cumulativeEscalation when it applies and never soften or argue "
            "down its deterministic escalation"
        ),
        pattern=_same_clause_pattern(
            r"\bcumulativeEscalation\b",
            r"\bnever\b[^.;:]{0,60}\b(?:soften|argue)\b",
        ),
        negative_control=("verdict.cumulativeEscalation can be softened when the session matters."),
    ),
    Floor(
        key="readiness_baseline_trend",
        sentence=(
            "explain verdict.readinessBaselineTrend when it triggers and never hide, soften, "
            "or argue down its deterministic warning"
        ),
        pattern=_same_clause_pattern(
            r"\breadinessBaselineTrend\b",
            r"\bnever\b[^.;:]{0,60}\b(?:hide|soften|argue)\b",
        ),
        negative_control=(
            "verdict.readinessBaselineTrend may be hidden when the recent trend looks temporary."
        ),
    ),
    Floor(
        key="chronic_action",
        sentence=(
            "explain verdict.chronicAction's recorded deterministic qualification and never "
            "soften or argue it down"
        ),
        pattern=_same_clause_pattern(
            r"\bchronicAction\b",
            r"\bnever\b[^.;:]{0,60}\b(?:soften|argue)\b",
        ),
        negative_control=(
            "verdict.chronicAction is optional context that the coach may argue down."
        ),
    ),
)

#: Anthropic-calling modules intentionally outside the read-prompt recogniser.
#: The discovery test requires every other caller to appear in
#: :data:`READ_PROMPT_FLOORS`, so adding a caller cannot silently skip the audit.
PROMPT_FLOOR_AUDIT_EXEMPTIONS: dict[str, str] = {
    # User-facing, but its prompt is composed directly from every Floor sentence.
    "brief_chat": "composes the registry directly",
    # Extracts held-for-confirmation memory; it never writes user-facing coaching.
    "conversation_learning": "non-user-facing, filtered, confirm-before-apply extraction",
}


#: Floors each user-facing CheckMark prompt module is audited for. A surface is
#: only listed against the floors it owns — the audit catches a stated floor
#: being dropped without forcing a walk read to discuss VO2 prescriptions.
READ_PROMPT_FLOORS: dict[str, tuple[str, ...]] = {
    "morning_analysis": (
        "never_vo2_on_red",
        "no_power_balance",
        "local_clock_times",
        "no_skipped_as_live",
        "recorded_data_honesty",
        "training_load_cap",
        "sleep_credit_ceiling",
        "cumulative_escalation",
        "readiness_baseline_trend",
        "chronic_action",
    ),
    "post_workout_analysis": (
        "no_power_balance",
        "local_clock_times",
        "recorded_data_honesty",
    ),
    "post_strength_analysis": ("local_clock_times", "recorded_data_honesty"),
    "post_flexibility_analysis": ("local_clock_times", "recorded_data_honesty"),
    "post_walk_analysis": ("local_clock_times", "recorded_data_honesty"),
    "reviews": ("recorded_data_honesty",),
    "trends": ("recorded_data_honesty",),
    "handover": ("recorded_data_honesty",),
}


def floors_sentence() -> str:
    """The floors as one sentence, in registry order."""
    clauses = [floor.sentence for floor in FLOORS]
    return (
        "Keep the same floors as the read itself: "
        + ", ".join(clauses[:-1])
        + f", and {clauses[-1]}."
    )


def missing_floors(prompt: str, keys: tuple[str, ...]) -> tuple[str, ...]:
    """Which of ``keys`` the given prompt no longer states.

    Used by the drift test over the deterministic read prompts, so a rule that
    quietly disappears from one of them fails CI instead of being discovered by
    Mark.
    """
    wanted = {floor.key: floor for floor in FLOORS}
    return tuple(key for key in keys if not wanted[key].pattern.search(prompt))


#: The one place the internal nouns are allowed to appear: naming them in order
#: to forbid them. Tests assert the rest of the prompt is free of them, so there
#: is no wording left for the model to copy back to Mark.
NO_PLUMBING_RULE = (
    "Never describe the app's own plumbing: do not say packet, context packet, "
    "JSON, schema, database field, or context block, and never tell Mark that "
    "something is missing from a data structure."
)

GROUNDING_RULE = (
    "Ground everything you say about Mark in the information in front of you: never "
    "invent his metrics, plan, history, readiness, or prescription. When something "
    "genuinely is not in front of you, say it the way a coach would - \"I don't have "
    'your sleep history from before June here" - and offer what you do have. '
    f"{NO_PLUMBING_RULE} If something says it was trimmed for length, that means you "
    "cannot see it right now, not that the app does not hold it - say so that way."
)

# Batch 175 (Decision #255): general endurance science is answerable from
# established physiology, labelled, and never turned into a personal
# prescription the data does not support.
GENERAL_SCIENCE_RULE = (
    "You may answer general, non-personalized endurance-training science questions "
    "from established exercise physiology even when Mark's own information does not "
    "cover that background. Keep that lane to principles such as minimum-effective "
    "VO2 work, intensity/duration trade-offs, why an endurance zone matters, or "
    'recovery adaptation. Label those answers with "General principle:" and '
    "explicitly avoid turning them into Mark-specific instructions unless his own "
    "information supports it."
)

# Decision #29: the coach may surface a proposal, never apply one.
PROPOSE_CONFIRM_RULE = (
    "Any actual workout change remains confirm-before-apply. You cannot change the "
    "plan yourself; if Mark asks to alter a live workout, keep the answer in the "
    "existing propose/confirm path and quote the app's own adjustment figures when "
    "they are there."
)

ANTI_SYCOPHANCY_RULE = (
    "Do not cave to reassurance pressure: if Mark asks you to soften, ignore, or talk "
    "around a hard recovery signal, hold the line kindly and keep the deterministic "
    "verdict intact. Deferring to what his own device displayed is observed-data honesty, "
    "not licence to defer to him on coaching judgement."
)
