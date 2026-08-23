"""Batch 217 — a derived fact says how it was reached, in words Mark can read.

The failure this covers is not that the reason was missing. Twice it was
present and unusable:

* **2026-08-20.** Mark asked *"What was the basis of the 23:15 sleep protocol
  target as don't recall setting it?"* The packet held
  ``knowledgeBase.sections[sleep_protocol].source = "batch_5_seed"`` and the
  coach answered *"the app doesn't show me the reasoning ... but I'd be
  speculating."* It was reading an internal build token that
  :data:`NO_PLUMBING_RULE` correctly forbids it from repeating to him.
* **2026-08-15.** He challenged *"VO2 has 1 of a 2-session target done"* and the
  coach conceded the number looked wrong rather than explaining that a target is
  a count of the sessions his own plan carries that week.

And on **2026-08-14**, challenged on a tag it could not explain at all, it
invented a mechanism — a Garmin skin-temperature outlier — asserted it twice and
carried the invention into an unrelated answer the next day.

So the contract has three halves and all three are checked here: a basis is a
sentence rather than a token, every write path that stamps a token has one, and
the coach is told not to fill a missing basis with a plausible guess.
"""

from __future__ import annotations

import ast
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.coach_policy import (
    DERIVED_FACTS,
    FLOORS,
    INTERNAL_SOURCE_BASIS,
    INTERNAL_SOURCE_BASIS_EXEMPTIONS,
    NO_INVENTED_DERIVATION_RULE,
    READ_PROMPT_FLOORS,
    _resolve,
    facts_missing_basis,
    internal_vocabulary_hits,
    missing_floors,
    source_basis,
)
from src.services.morning_analysis import (
    MorningAnalysisService,
    _knowledge_base_packet,
    _planned_workout_packet,
)
from src.services.training_week import (
    _planned_workout_packet as _training_week_planned_workout_packet,
)

SRC = Path(__file__).parents[1] / "src"
PROVENANCE_MODELS = {"PlannedWorkout", "KnowledgeBase"}


# ---------------------------------------------------------------------------
# A basis is a sentence, never a token
# ---------------------------------------------------------------------------


def test_an_unrecognised_token_yields_nothing_rather_than_itself() -> None:
    """Silence beats echoing plumbing.

    ``source`` is not always a code constant — an imported plan supplies its
    own name — so the map will meet values it has never seen. Returning the raw
    token would recreate the exact 08-20 failure in a field called ``basis``,
    which is worse, because it would then look answered.
    """
    assert source_basis("some_future_plan_v9") is None
    assert source_basis(None) is None
    assert source_basis("") is None
    assert source_basis("batch_5_seed") == "set up when the app was first configured"
    # Whitespace is a storage artefact, not a different provenance.
    assert source_basis("  batch_5_seed  ") == source_basis("batch_5_seed")


def test_every_translation_is_something_the_coach_is_allowed_to_say() -> None:
    for token, sentence in INTERNAL_SOURCE_BASIS.items():
        assert internal_vocabulary_hits(sentence) == (), token
        # A sentence, not a relabelled enum.
        assert "_" not in sentence, token
        assert sentence != token
        assert " " in sentence.strip(), token


def _provenance_source_literals() -> set[str]:
    """Every ``source=`` literal written against a provenance-carrying model.

    Discovered from the tree rather than listed, following the Batch 179.5
    prompt audit: adding a new write path cannot silently reintroduce an
    unquotable token. Module-level string constants and the two-branch
    ``"a" if cond else "b"`` form are resolved; anything genuinely dynamic is
    ignored here and covered by the exemption map's own reasoning.
    """

    def literals(node: ast.AST, constants: dict[str, str]) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return literals(node.body, constants) | literals(node.orelse, constants)
        if isinstance(node, ast.Name) and node.id in constants:
            return {constants[node.id]}
        return set()

    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name not in PROVENANCE_MODELS:
                continue
            for keyword in node.keywords:
                if keyword.arg == "source":
                    found |= literals(keyword.value, constants)
    return found


def test_every_write_path_stamps_a_token_the_coach_can_translate() -> None:
    """The discovery half, and the reason this test exists at all.

    Written by hand from the six values live in production, the map missed six
    more that only the tree knows about — `block_generator`, `holiday_resume`,
    `reset_week`, `weekly_restructure`, `block_generator_lock` and
    `conversation_learning_confirmed`. A hand-maintained list would have shipped
    with those holes and nothing would have noticed until Mark asked.
    """
    discovered = _provenance_source_literals()
    assert discovered, "the AST walk found no provenance writes — the discovery is broken"
    covered = set(INTERNAL_SOURCE_BASIS) | set(INTERNAL_SOURCE_BASIS_EXEMPTIONS)
    assert discovered <= covered, sorted(discovered - covered)


# ---------------------------------------------------------------------------
# The packet carries it
# ---------------------------------------------------------------------------


def _knowledge_base_row(source: str) -> KnowledgeBase:
    return KnowledgeBase(
        user_id=uuid.uuid4(),
        section="sleep_protocol",
        version=1,
        is_active=True,
        source=source,
        content={"bedtime": "23:15"},
    )


def _planned_workout_row(source: str) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plan_block_id=None,
        workout_date=date(2026, 8, 23),
        version=1,
        title="Z2 + Neuromuscular",
        workout_type="bike_endurance",
        status="planned",
        is_active=True,
        planned_duration_min=58,
        intensity_target="Zone 2 ~65-72% FTP",
        structured_workout={},
        source=source,
    )


def test_the_2026_08_20_question_is_answerable_from_the_section_itself() -> None:
    """The exact row the coach was looking at when it said it would be speculating."""
    packet = _knowledge_base_packet(_knowledge_base_row("batch_5_seed"))
    assert packet["basis"] == "set up when the app was first configured"
    # The token stays for the app's own consumers; the sentence is what is sayable.
    assert packet["source"] == "batch_5_seed"
    assert internal_vocabulary_hits(packet["basis"]) == ()


def test_a_planned_session_says_how_it_reached_the_calendar() -> None:
    for builder in (_planned_workout_packet, _training_week_planned_workout_packet):
        packet = builder(_planned_workout_row("today_card_swap"))
        assert packet["basis"] == "moved to this day from the app's Today card"


def test_an_unrecognised_source_omits_the_key_rather_than_leaking_it() -> None:
    for builder in (_planned_workout_packet, _training_week_planned_workout_packet):
        packet = builder(_planned_workout_row("some_future_plan_v9"))
        assert "basis" not in packet
        assert packet["source"] == "some_future_plan_v9"


# ---------------------------------------------------------------------------
# The registry, and its drift test
# ---------------------------------------------------------------------------


def test_resolve_walks_a_packet_shape_without_assuming_it_is_there() -> None:
    packet = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert _resolve(packet, "a.b.[]") == [{"c": 1}, {"c": 2}]
    # A read with no such section is not a failure — a rest day has no ride.
    assert _resolve(packet, "missing.b.[]") == []
    assert _resolve(packet, "a.b") == [[{"c": 1}, {"c": 2}]]
    # A string is not a list to be walked into character by character.
    assert _resolve({"a": "bc"}, "a.[]") == []


def test_every_registry_entry_reports_its_own_negative_control() -> None:
    """199.1's lesson, applied to provenance: prove the check can fail."""
    for fact in DERIVED_FACTS:
        assert facts_missing_basis(fact.negative_control) == (fact.key,), fact.key
        assert fact.describes
        assert fact.basis_field


def test_a_basis_that_is_an_internal_token_counts_as_missing() -> None:
    """The 08-20 shape stated as a rule.

    ``source: "batch_5_seed"`` looked like provenance and was not sayable. A
    field called ``basis`` holding the same token would pass a naive presence
    check while leaving Mark exactly where he was.
    """
    packet = {
        "knowledgeBase": {"sections": [{"section": "sleep_protocol", "basis": "batch_5_seed"}]}
    }
    assert facts_missing_basis(packet) == ("knowledge_base_section",)


def test_a_fully_annotated_packet_reports_nothing_missing() -> None:
    packet = {
        "verdict": {
            "weeklyMix": {"buckets": [{"bucket": "vo2", "basis": "counted from your plan"}]}
        },
        "knowledgeBase": {"sections": [{"section": "sleep_protocol", "basis": "set up at setup"}]},
        "plannedWorkouts": [{"title": "Z2", "basis": "imported from your training plan"}],
        "trainingWeekSoFar": {
            "days": [{"planned": [{"title": "Z2", "basis": "imported from your training plan"}]}]
        },
    }
    assert facts_missing_basis(packet) == ()


def test_an_absent_section_is_not_a_missing_basis() -> None:
    """A rest-day read carries no planned workout, and that is not a defect."""
    assert facts_missing_basis({"plannedWorkouts": []}) == ()
    assert facts_missing_basis({}) == ()


def test_a_blank_basis_is_the_same_as_no_basis() -> None:
    assert facts_missing_basis({"plannedWorkouts": [{"basis": "   "}]}) == ("planned_workout",)


# ---------------------------------------------------------------------------
# The rule the transcripts asked for
# ---------------------------------------------------------------------------


def test_the_floor_forbids_inventing_the_apps_own_reasoning() -> None:
    """GROUNDING_RULE covers Mark's data; this covers the app's reasoning.

    The distinction is the whole point. On 08-14 nothing the coach said about
    Mark was invented — his readiness, HRV and Body Battery were all quoted
    correctly. What it invented was *how the app had reached a conclusion*, and
    no rule reached that.
    """
    floor = next(f for f in FLOORS if f.key == "no_invented_derivation")
    assert missing_floors(floor.sentence, (floor.key,)) == ()
    assert missing_floors(floor.negative_control, (floor.key,)) == (floor.key,)
    assert missing_floors(NO_INVENTED_DERIVATION_RULE, (floor.key,)) == ()
    assert internal_vocabulary_hits(NO_INVENTED_DERIVATION_RULE) == ()
    # Named where the derived deterministic facts actually live.
    assert "no_invented_derivation" in READ_PROMPT_FLOORS["morning_analysis"]
    assert "no_invented_derivation" in READ_PROMPT_FLOORS["post_workout_analysis"]


def test_the_rule_covers_both_halves_of_the_recorded_failure() -> None:
    """Invention, and the carry-forward that made it durable.

    The 08-14 guess was repeated the next day as though it had been established
    ("likely triggered the skin temperature outlier"), so forbidding the
    invention alone would leave the second half live.
    """
    rule = NO_INVENTED_DERIVATION_RULE.lower()
    assert "never offer a plausible mechanism" in rule
    assert "carry a guess" in rule
    assert "does not record how that number was reached" in rule


# ---------------------------------------------------------------------------
# End to end, on an assembled packet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_assembled_morning_packet_can_explain_every_covered_fact(
    db_conn: AsyncConnection,
) -> None:
    """The acceptance criterion, checked against the real assembly.

    Not against a hand-built dict: the registry describes the packet the app
    actually sends, and the point of failure both times was a *live* packet
    whose annotation existed only in a shape the coach could not use.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 15)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Fact Basis Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="sleep_protocol",
                version=1,
                is_active=True,
                source="batch_5_seed",
                content={"bedtime": "23:15"},
            )
        )
        # A block of its own, so the starter-week seed does not run and add
        # sessions this test did not choose — the week's counts are the point.
        session.add(
            PlanBlock(
                user_id=user_id,
                name="Wk 1 build",
                version=1,
                sequence_index=1,
                block_type="build",
                start_date=date(2026, 8, 10),
                end_date=date(2026, 8, 16),
                goals_json={},
                raw_plan={},
            )
        )
        await session.flush()
        # The real 2026-08-11 chain: a skipped ghost, then the completed ride.
        # This is the week whose VO2 target Mark challenged.
        session.add_all(
            [
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=date(2026, 8, 11),
                    version=1,
                    title="VO2",
                    workout_type="bike_vo2",
                    status="skipped",
                    is_active=True,
                    planned_duration_min=63,
                    structured_workout={"format": "bike"},
                    source="plan_no2_import",
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=date(2026, 8, 11),
                    version=3,
                    title="VO2",
                    workout_type="bike_vo2",
                    status="completed",
                    is_active=True,
                    planned_duration_min=63,
                    structured_workout={"format": "bike"},
                    source="plan_action_add",
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=subject_date,
                    version=1,
                    title="Sweet Spot",
                    workout_type="bike_sweet_spot",
                    status="planned",
                    is_active=True,
                    planned_duration_min=91,
                    structured_workout={"format": "bike"},
                    source="plan_no2_import",
                ),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    assert facts_missing_basis(packet) == ()

    # And the specific answer Mark could not get, present in the packet itself.
    vo2 = next(
        bucket for bucket in packet["verdict"]["weeklyMix"]["buckets"] if bucket["bucket"] == "vo2"
    )
    assert vo2["target"] == 1
    assert "not a standing weekly quota" in vo2["basis"]
    sleep_protocol = next(
        section
        for section in packet["knowledgeBase"]["sections"]
        if section["section"] == "sleep_protocol"
    )
    assert sleep_protocol["basis"] == "set up when the app was first configured"
