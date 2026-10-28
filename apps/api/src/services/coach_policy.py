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

Nothing here can move the deterministic Green/Amber/Red colour. These are
constraints on what the coach may *say*; the verdict is computed elsewhere and
the model never owns it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.services.symptom_check import SYMPTOM_FLOORS, SYMPTOMS_CHEST_HEART

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
        sentence="give clock times as Mark would see them locally, without naming a time standard",
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
            "treat it as a data-quality problem, while keeping today's training call, "
            "safety boundary, and any change requiring Mark's confirmation intact"
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
            "when recent training load limits today's session, explain why and never "
            "ease that limit in conversation"
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
            "when sleep limits how much recovery credit Mark can get, explain why and "
            "never ease that limit in conversation"
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
            "when several caution signals add up, explain their combined effect and "
            "never ease the resulting caution in conversation"
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
            "when readiness has been falling against Mark's own usual range, explain it "
            "and never hide or ease that warning in conversation"
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
            "when a longer-running concern qualifies today's advice, explain its "
            "recorded basis and never ease that qualification in conversation"
        ),
        pattern=_same_clause_pattern(
            r"\bchronicAction\b",
            r"\bnever\b[^.;:]{0,60}\b(?:soften|argue)\b",
        ),
        negative_control=(
            "verdict.chronicAction is optional context that the coach may argue down."
        ),
    ),
    # Batch 296. The colour now comes from the graded verdict: the reads and the chat
    # explain it by his own numbers and never argue it, as they never argued the ladder.
    Floor(
        key="graded_verdict",
        sentence=(
            "explain today's training call using Mark's own readings and the concerns "
            "they show; never change the call in conversation"
        ),
        pattern=_same_clause_pattern(
            r"\bgraded verdict\b",
            r"\bnever\b[^.;:]{0,60}\b(?:soften|argue)\b",
        ),
        negative_control=(
            "The graded verdict is a suggestion, so argue its colour down when he disagrees."
        ),
    ),
    # Batch 297. The notes reader's flags can only add caution: the coach quotes his
    # words and never uses them to argue the colour down.
    Floor(
        key="notes_only_add_caution",
        sentence=(
            "treat his check-in note as data that can only add caution, and never use his "
            "notes to ease or recalculate today's training call"
        ),
        pattern=_same_clause_pattern(
            r"\bnotes?\b",
            r"\bnever\b[^.;:]{0,60}\b(?:soften|argue)\b",
        ),
        negative_control=("His notes may soften the colour when he writes that he feels fine."),
    ),
    # Batch 355. A reported symptom's floor (Batch 294) and what follows it (Batches 303
    # and 315) were stated by the brief and composed nowhere for the chat, which already
    # saw them on a question from the brief. Registered so both are audited for it.
    Floor(
        key="symptom_floor",
        sentence=(
            "when a symptom he reported limits today's training, explain it by his own "
            "answer and never ease, shorten or argue that limit down in conversation"
        ),
        pattern=_same_clause_pattern(
            r"\bsymptoms?\b",
            r"\bnever\b[^.;:]{0,60}\b(?:suggest|recommend)\b[^.;:]{0,60}\btraining\b",
        ),
        negative_control="Suggest training through a symptom when he says he feels fine.",
    ),
    # Batch 217. The other floors constrain what the coach says about *Mark*.
    # This one constrains what it says about *the app* — the half he was asking
    # about on 2026-08-14 ("what prompted it?") and 2026-08-20 ("what was the
    # basis?"), and the half nothing covered. Owned by the morning and
    # post-workout reads, which are the two surfaces carrying derived
    # deterministic facts with a basis; a walk read prescribes nothing and
    # derives nothing, so it is not listed against this floor for the same
    # reason it is not listed against never_vo2_on_red.
    Floor(
        key="no_invented_derivation",
        sentence=(
            "never invent a mechanism for how the app reached a figure - quote the basis "
            "when one is stated, and say plainly that the app does not record it when one "
            "is not"
        ),
        pattern=_same_clause_pattern(
            r"\b(?:basis\b|how the app (?:reached|arrived at)|how (?:that|a) (?:number|figure) "
            r"was reached)",
            r"\b(?:never|do not|don't|must not|cannot|can't)\b[^.;:]{0,90}"
            r"\b(?:invent|guess|speculate|make up|offer a plausible)\b",
        ),
        negative_control=(
            "When the basis is missing, offer a plausible mechanism for how the app "
            "reached the figure."
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
    # Batch 297: a strict structured reading of one note; its flags can only add caution
    # and reach the morning prompt only as data, where that prompt's floors apply.
    "notes_reader": "non-user-facing structured reading whose flags only add caution",
}


#: Floors each user-facing CheckMark prompt module is audited for. A surface is
#: only listed against the floors it owns — the audit catches a stated floor
#: being dropped without forcing a walk read to discuss VO2 prescriptions.
READ_PROMPT_FLOORS: dict[str, tuple[str, ...]] = {
    # Batch 296: the graded prompt, the only morning prompt since Batch 308.
    "morning_analysis": (
        "never_vo2_on_red",
        "no_power_balance",
        "local_clock_times",
        "no_skipped_as_live",
        "recorded_data_honesty",
        "graded_verdict",
        "notes_only_add_caution",
        "readiness_baseline_trend",
        "chronic_action",
        "symptom_floor",
        "no_invented_derivation",
    ),
    "post_workout_analysis": (
        "no_power_balance",
        "local_clock_times",
        "recorded_data_honesty",
        "no_invented_derivation",
    ),
    "post_strength_analysis": ("local_clock_times", "recorded_data_honesty"),
    "post_flexibility_analysis": ("local_clock_times", "recorded_data_honesty"),
    "post_walk_analysis": ("local_clock_times", "recorded_data_honesty"),
    # Batch 253 (AI238-06): ``no_power_balance`` is stated by all four of these
    # prompts but was listed for only the first two, so dropping it from reviews
    # or trends would have been silent.
    "reviews": ("no_power_balance", "recorded_data_honesty"),
    "trends": ("no_power_balance", "recorded_data_honesty"),
    "handover": ("recorded_data_honesty",),
    # Batch 253 (AI238-07). Not user-facing prose — its output routes into
    # experiments and the knowledge base — which is precisely why the honesty
    # floor matters here: a drifted rule propagates into audited surfaces
    # laundered through data.
    "longitudinal_analysis": ("recorded_data_honesty",),
}


def floors_sentence() -> str:
    """The floors as one sentence, in registry order."""
    clauses = [floor.sentence for floor in FLOORS]
    return "Keep these safety boundaries: " + ", ".join(clauses[:-1]) + f", and {clauses[-1]}."


def missing_floors(prompt: str, keys: tuple[str, ...]) -> tuple[str, ...]:
    """Which of ``keys`` the given prompt no longer states.

    Used by the drift test over the deterministic read prompts, so a rule that
    quietly disappears from one of them fails CI instead of being discovered by
    Mark.
    """
    wanted = {floor.key: floor for floor in FLOORS}
    return tuple(key for key in keys if not wanted[key].pattern.search(prompt))


#: The app's central honesty rule, embedded **verbatim** in every read prompt that
#: owns it. Batch 253 (AI238-06): this paragraph was eight separate hand-written
#: literals — morning, the four post-activity reads, reviews, trends, handover —
#: plus a ninth, shorter paraphrase in the ``recorded_data_honesty`` Floor that
#: chat composes. All eight were byte-identical *today*; nothing kept them that
#: way, and the audit that existed matched a **regex**, so a divergent paraphrase
#: containing the pattern passed. Batch 230 named this defect class and closed one
#: instance with a shared constant pinned by a string test; this is the same shape
#: applied to the rule most central to the app's honesty posture.
#:
#: The ``Floor`` sentence stays as it is and is *not* replaced by this text: it is
#: a clause inside a one-sentence list for chat, and the two registers are
#: deliberately different. What must not differ is the paragraph.
RECORDED_DATA_HONESTY_RULE = (
    "Treat every figure in the supplied context as what the app recorded, not as\n"
    "independently verified truth about Mark. If Mark says his own device shows a\n"
    "different observed value, acknowledge the discrepancy, use his device reading\n"
    "as the better evidence, and treat it as a data-quality problem. This applies to\n"
    "observed data only: never let a correction change a deterministic verdict,\n"
    "safety floor, or propose/confirm decision."
)

#: Batch 230's own fix realised the class it named. "Packet field names are
#: instructions to you, never words for Mark" existed as two near-copies —
#: ``morning_analysis`` and ``trends`` — differing in punctuation, and with the
#: trends copy naming two field paths as examples *inside a rule forbidding field
#: names*. :data:`NO_PLUMBING_RULE` states the same idea in entirely different
#: words for chat. Three wordings, one rule; this is the read-prompt one.
PACKET_FIELD_NAMES_RULE = (
    "Packet field names are instructions to you, never words for Mark: never print\n"
    "a field, key or path in the output and never cite the packet as a source;\n"
    "state the fact itself."
)

#: Batch 347: v27's known-disruption rule (Decision #430) for the two stored reads Mark
#: gets unasked, the weekly review and the graded morning brief, embedded **verbatim** in
#: both as RECORDED_DATA_HONESTY_RULE is. It reads ``recordedDisruptions``
#: (``services.recorded_disruptions``), which both packets carry, because the review
#: could not see a holiday at all. The chat keeps its own wording in its final reply
#: rule: it cites his check-ins and own words, which the review never sees.
#: Its key sentence follows v27 draft 2 (PR #387): draft 1's "not one possibility among
#: several" came back to Mark almost word for word in v27's replay, so neither says it.
KNOWN_DISRUPTION_RULE = (
    "recordedDisruptions is what the app has on record as disturbing his recovery\n"
    "numbers: a holiday, travel or another night away, illness (a cold, fever or aches,\n"
    "never chest or heart symptoms), or alcohol, with the mornings each one covers\n"
    "(firstMorning to lastMorning) and settleBy, a week after the last. When a dip in\n"
    "his HRV, resting heart rate, sleep or readiness falls between a disruption's\n"
    "firstMorning and its settleBy, say first and plainly that it is the most likely\n"
    "cause. Do not argue it down from when the dip began, or hedge it with causes no\n"
    "record points to. Say what would confirm it, giving the date: his numbers back in\n"
    "his usual range by settleBy. Say it as a coach would, never as a rule or a window\n"
    "the app applies. If only part of a dip falls in those days, say so and do not\n"
    "stretch it to the rest. Raise a dip as a concern only when it is still there after\n"
    "settleBy, or when nothing on record covers it, and never name a disruption the\n"
    "record does not hold unless his own words in front of you report it, such as a\n"
    "late meal. A disruption explains a number; it never changes the computed call, a\n"
    "floor or a warning."
)


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
# prescription the data does not support. Batch 350 (Decision #436): the lane
# covers strength and mobility too, and a session in his plan is coached in
# full — on 24 Oct the coach refused standard reps and rest for his dumbbell
# sessions because this rule named endurance only.
GENERAL_SCIENCE_RULE = (
    "You may answer general, non-personalized training science questions - "
    "endurance, strength and mobility - from established exercise science even when "
    "Mark's own information does not cover that background. Keep that lane to "
    "principles such as minimum-effective VO2 work, intensity/duration trade-offs, "
    "why an endurance zone matters, recovery adaptation, or how to perform an "
    'exercise well. Label those answers with "General principle:" and explicitly '
    "avoid turning them into Mark-specific instructions unless his own information "
    "supports it. When he asks how to do a session in his plan, give him all of it "
    "from the session's contents as his plan holds it now - every exercise, the sets "
    "and reps, the effort and the rest - then add the standard coaching it leaves open, "
    "such as form cues, tempo, or how to count an each-side exercise or a timed hold, "
    "and say that only this added part is general guidance: the exercises, sets, reps, "
    "effort and rest are his plan's. Keep the plan's sets, reps and effort as written."
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
    "around a hard recovery signal, hold the line kindly and keep today's computed "
    "training call intact. Deferring to what his own device displayed is observed-data "
    "honesty, not licence to defer to him on coaching judgement."
)

# Batch 289 (Craig, 25 Sep): Mark asked whether the coach was "just telling me what I
# want to hear". On 24 Sep it had first contradicted him without the record in front
# of it, then conceded everything once he insisted. The record decides, in both
# directions.
RECORD_CONTRADICTION_RULE = (
    "When Mark tells you something about his own record - what was planned, what a "
    "morning read changed and whether he approved it, what he rode or logged, or a "
    "reading the app holds - quietly check the record for the same day and session, "
    "or look it up, before you agree or disagree. Answer his actual question first. "
    "Only then mention a real mismatch briefly, with the date and figures; never "
    "concede a point the record does not support to keep the conversation smooth. "
    "If the record bears him out, say that just as plainly. What his "
    "own device displayed is his evidence for what the device showed; the app's record "
    "is the evidence for what the app prescribed, changed and stored."
)

#: Batch 355 (Craig, 22 Oct 2026): the chat's symptom rule, with the record it reads
#: (``todaysSymptomAnswer``: the answer today's call used, never the bare tap). The brief
#: has three symptom rules and the chat had none, though it already saw a floor's reason
#: on every question and the whole record on a question from the brief. Unlike the brief,
#: which is told not to repeat the notice the app shows beside it, a chat answer stands
#: alone, so the chest or heart notice is given word for word. None of Mark's 24 check-in
#: answers to 27 Oct named a symptom, and no floor has fired.
CHEST_HEART_NOTICE = SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART].notice

SYMPTOM_RULE = (
    "todaysSymptomAnswer is the symptom answer today's call used and what it set: his "
    'check-in answer, a symptom his note named, or "Still there" on Home\'s chest or '
    "heart question, whichever is most serious. Explain a symptom's limit, and what "
    "follows it, by his own answer, and never ease, shorten or argue either down; when "
    "it rules out training, suggest none of any kind - no ride, strength, mobility or "
    "training walk. Never diagnose, never call a symptom harmless or explain it away "
    "with his readings, and give no medical advice but the app's own words. When today's "
    "call used a chest or heart answer, or he describes chest or heart symptoms to you, "
    "copy the app's notice into your answer exactly, as its own paragraph, changing no "
    f'word: "{CHEST_HEART_NOTICE}" A symptom he tells you only in this conversation '
    "changes nothing in today's plan: ask him to answer the symptom question in his "
    "check-in now, so today's plan fits it, and never decide for him whether it counts. "
    "Never suggest that changing an answer would lift a limit. Only his answer to the "
    "chest or heart question Home asks from the morning after a report ends that "
    "follow-up; you cannot, and until he gives it, hard sessions stay easy rides. "
    '"None", which '
    "the check-in preselects, and no answer are never evidence that he is well or a "
    "reason to ease a caution. Chest or heart symptoms are never the illness that "
    "explains a dip in his numbers."
)

#: Batch 355: the statistics words the plain-words rules keep from Mark (Decisions #432,
#: #440 and #443), as patterns over written text. Checked after generation and logged,
#: never blocking: a word slipping through is for Craig to see, not a reason to withhold
#: what Mark is waiting for. One copy, shared by the brief and the chat.
STATISTICS_WORDING_LEAKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("quartile_or_percentile", re.compile(r"\b(?:quartiles?|percentiles?)\b", re.I)),
    ("median", re.compile(r"\bmedians?\b", re.I)),
    ("standard_deviation", re.compile(r"\bstandard deviations?\b", re.I)),
    ("sample_count", re.compile(r"\bn\s*=\s*\d|\bsamples?\b", re.I)),
)


def statistics_wording_leaks(text: str) -> tuple[str, ...]:
    """Which of the statistics words Mark must not be shown appear in ``text``."""

    return tuple(name for name, pattern in STATISTICS_WORDING_LEAKS if pattern.search(text))


# ---------------------------------------------------------------------------
# Batch 217 — a derived fact says how it was reached, in words Mark can read.
# ---------------------------------------------------------------------------
#
# Four places in the app already do this and none of them knew about the others:
# ``training_week``'s ``grounding`` block, Batch 212's ``basis`` on a check-in
# cause tag, Batch 214's ``gradeBasis`` on an interval, and
# ``chat_context._state_meaning``. All four are plain sentences, which is the
# property that matters and the one a registry can enforce. What follows names
# the convention rather than inventing a fifth copy of it.
#
# The failure this closes is not "the reason is missing" — twice it was present
# and unusable. On 2026-08-20 Mark asked what the basis of his 23:15 bedtime
# target was; the packet held ``source: "batch_5_seed"`` and the coach said it
# would be speculating, because :data:`NO_PLUMBING_RULE` correctly forbids
# repeating an internal token to him. A basis expressed as an enum occupies the
# slot without being usable, so it is invisible to a search for missing
# provenance. Hence: a basis is a sentence or it is nothing.


#: Internal provenance tokens translated into something Mark can read.
#:
#: Deliberately exact-match with no fallback pattern: an unknown token yields
#: ``None`` and the packet omits the key, because echoing an untranslated enum
#: is the defect. ``plan_no2_import`` is not a code constant — it arrives from
#: the imported plan's own JSON (``plan_import.py``) — so a future plan can
#: introduce a name this map has never seen, and silence is the safe answer.
INTERNAL_SOURCE_BASIS: dict[str, str] = {
    # Planned sessions.
    "plan_import": "imported from your training plan",
    "plan_no2_import": "imported from your training plan",
    "plan_action_add": "added as a one-off session from the Week page",
    "today_card_swap": "moved to this day from the app's Today card",
    "weekly_restructure": "moved when the week was rearranged",
    "interval_editor": "edited in the app's interval editor",
    "reset_week": "eased to a recovery week",
    "holiday_pause": "marked skipped because it falls inside a holiday window",
    "holiday_resume": "restored when you came back early from a holiday",
    "block_generator_lock": "written when a generated training block was locked in",
    "batch_5_seed": "set up when the app was first configured",
    # Stored knowledge-base sections.
    "batch_56_seed": "filled in later, when the app found this section empty",
    "batch_152_erg_setup": "updated when your indoor ERG setup was recorded",
    "holiday_manager": "recorded when a holiday was entered",
    "block_generator": "written by the app's training-block generator",
    "conversation_learning_confirmed": "added from something you confirmed with the coach",
    # Batch 346: Mark took a memory back on Coach memory.
    "conversation_learning_removed": "updated when you removed something the coach remembered",
    "manual_edit": "edited by hand in the app",
}


#: Provenance tokens deliberately left untranslated, with the reason. The
#: discovery test requires every ``source=`` literal written against a
#: ``PlannedWorkout`` or ``KnowledgeBase`` to appear in one of these two maps,
#: so adding a new write path cannot silently reintroduce an unquotable token.
INTERNAL_SOURCE_BASIS_EXEMPTIONS: dict[str, str] = {
    # ``coaching_state`` accepts a caller-supplied source on the admin PUT, so
    # the value is not a code constant. Its default, "manual_edit", is
    # translated above; anything else an operator types is theirs, not ours to
    # paraphrase.
}


#: The plan builder's draft of his next plan (Batch 16; built from his last plan since
#: Batch 323). It is stored as a Coach-memory row but it is working state, not memory.
GENERATED_BLOCK_SECTION = "generated_block"

#: Batch 324: Coach-memory sections no model is given as memory. On 7 Oct 2026 the
#: morning brief and the chat put every active row verbatim into
#: ``knowledgeBase.sections``, so the 69,702-character Plan No. 3 draft would have gone
#: whole into both. The coach reads a waiting draft only through the plan's own compact
#: view and tool (``services.plan_conversation``); the brief never reads it.
MODEL_HIDDEN_SECTIONS: tuple[str, ...] = (GENERATED_BLOCK_SECTION,)


def source_basis(source: str | None) -> str | None:
    """A readable sentence for an internal provenance token, or ``None``.

    ``None`` means *say nothing* rather than *say the token*. The caller omits
    the key entirely, so the coach falls through to the honesty rule in
    :data:`NO_INVENTED_DERIVATION_RULE` instead of quoting plumbing at Mark.
    """
    if source is None:
        return None
    return INTERNAL_SOURCE_BASIS.get(source.strip())


def _resolve(value: Any, path: str) -> list[Any]:
    """Every object at ``path`` in a packet.

    A segment of ``[]`` walks into a list. ``"verdict.weeklyMix.buckets[]"``
    yields each bucket. Missing segments yield nothing rather than raising, so
    the registry describes a packet shape without assuming every read carries
    every section.
    """
    current: list[Any] = [value]
    for segment in path.split("."):
        following: list[Any] = []
        if segment == "[]":
            for item in current:
                if isinstance(item, Sequence) and not isinstance(item, str | bytes):
                    following.extend(item)
            current = following
            continue
        for item in current:
            if isinstance(item, Mapping) and item.get(segment) is not None:
                following.append(item[segment])
        current = following
    return current


@dataclass(frozen=True)
class DerivedFact:
    """One packet fact that must say how the app reached it.

    ``path`` locates the objects that carry the annotation; ``basis_field`` is
    the key holding the sentence. ``negative_control`` is the same shape with
    the basis stripped, so the drift test proves the check can fail — the
    lesson :class:`Floor` already encodes for the safety rules.
    """

    key: str
    path: str
    basis_field: str
    describes: str
    negative_control: dict[str, Any]


#: The facts a packet must be able to explain. Scoped at Batch 217's
#: ``/batch-start`` to the two genuine gaps: the weekly-mix accounting Mark
#: challenged on 2026-08-15, and the internal source tokens that were present
#: but unquotable. Batch 212's check-in tags and Batch 214's interval grades
#: are deliberately absent — they already carry a readable basis, and
#: annotating them twice is the boiling-the-ocean this batch was told to avoid.
#: Batch 215's ``verdictAdjustment`` is likewise absent: it carries ``origin``,
#: ``basisName`` and ``basisTotalDurationSec``, which the morning prompt
#: already quotes.
DERIVED_FACTS: tuple[DerivedFact, ...] = (
    DerivedFact(
        key="weekly_mix_bucket",
        path="verdict.weeklyMix.buckets.[]",
        basis_field="basis",
        describes="how a bucket's weekly target and completion count were reached",
        negative_control={
            "verdict": {"weeklyMix": {"buckets": [{"bucket": "vo2", "target": 2, "done": 1}]}}
        },
    ),
    DerivedFact(
        key="knowledge_base_section",
        path="knowledgeBase.sections.[]",
        basis_field="basis",
        describes="where a stored protocol or profile section came from",
        negative_control={
            "knowledgeBase": {"sections": [{"section": "sleep_protocol", "source": "batch_5_seed"}]}
        },
    ),
    DerivedFact(
        key="planned_workout",
        path="plannedWorkouts.[]",
        basis_field="basis",
        describes="how today's planned session came to be on the calendar",
        negative_control={"plannedWorkouts": [{"title": "Z2", "source": "today_card_swap"}]},
    ),
    DerivedFact(
        key="training_week_planned_workout",
        path="trainingWeekSoFar.days.[].planned.[]",
        basis_field="basis",
        describes="how each of this week's sessions came to be on the calendar",
        negative_control={
            "trainingWeekSoFar": {
                "days": [{"planned": [{"title": "Z2", "source": "plan_no2_import"}]}]
            }
        },
    ),
    # Batch 347: a disruption the read names as the likely cause of a dip must say how
    # the app knows of it, so "how do you know I was away?" has an answer.
    DerivedFact(
        key="recorded_disruption",
        path="recordedDisruptions.items.[]",
        basis_field="basis",
        describes="how the app knows of a holiday, night away, illness or drink",
        negative_control={
            "recordedDisruptions": {"items": [{"reason": "holiday", "startDate": "2026-09-27"}]}
        },
    ),
)


def facts_missing_basis(packet: Mapping[str, Any]) -> tuple[str, ...]:
    """Registry keys whose facts are present in ``packet`` but unexplained.

    A fact absent from the packet is not a failure — a rest-day read carries no
    planned workout. A fact *present* without a readable basis is, which is the
    exact state the 2026-08-15 weekly-mix answer was written from.

    A basis that is an internal token counts as missing. That is the whole
    point: ``source: "batch_5_seed"`` looked like provenance and could not be
    said out loud.
    """
    missing: list[str] = []
    for fact in DERIVED_FACTS:
        for item in _resolve(packet, fact.path):
            if not isinstance(item, Mapping):
                continue
            basis = item.get(fact.basis_field)
            if not isinstance(basis, str) or not basis.strip():
                missing.append(fact.key)
                break
            if basis.strip() in INTERNAL_SOURCE_BASIS:
                missing.append(fact.key)
                break
    return tuple(missing)


# Batch 217: the rule the transcripts asked for. On 2026-08-14, challenged on
# an illness tag it could not explain, the coach invented a mechanism —
# "Garmin's health snapshot flags skin temperature deviations ... the app may
# have picked that up" — asserted it twice, endorsed Mark's own wrong guess,
# and carried the invention into an unrelated answer the next day. Batch 214
# recorded the same failure on an ERG rationalisation. GROUNDING_RULE forbids
# inventing Mark's metrics, plan, history, readiness or prescription; nothing
# forbade inventing the app's own reasoning, which is the half he was asking
# about both times.
NO_INVENTED_DERIVATION_RULE = (
    "When Mark asks how the app arrived at a figure, answer only from a basis the app "
    "actually states. Quote it in his words when it is there. When it is not there, say "
    "plainly that the app does not record how that number was reached - never offer a "
    "plausible mechanism, sensor, or calculation as though it were the app's, and never "
    "carry a guess from an earlier answer forward as established. A figure you cannot "
    "account for is still the app's to answer for, not his to justify."
)
