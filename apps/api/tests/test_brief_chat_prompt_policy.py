"""Pure prompt-policy coverage for brief chat (Batch 175 lane, Batch 178 register).

These run without Postgres, so the contract that decides what Mark actually
reads is checked on every local run, not only in CI.
"""

from src.services.brief_chat import (
    INTERNAL_VOCABULARY,
    NO_PLUMBING_RULE,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    _capability_instruction,
    _read_description,
    internal_vocabulary_hits,
)
from src.services.chat_context import APP_STATE_KEY

#: The prompt is a wrapped literal, so a phrase can straddle a newline. Assert
#: against whitespace-normalized text (the Batch 175 CI lesson).
FLAT_PROMPT = " ".join(SYSTEM_PROMPT.split())


class _FakeAnalysis:
    def __init__(self, analysis_type: str, subject_date: str = "2026-07-30") -> None:
        self.analysis_type = analysis_type
        self.subject_date = _Date(subject_date)


class _Date:
    def __init__(self, value: str) -> None:
        self._value = value

    def isoformat(self) -> str:
        return self._value


def test_brief_chat_prompt_allows_labelled_general_science_lane() -> None:
    """Batch 175's lane survives Batch 178's rewrite of the register."""
    assert PROMPT_VERSION == "brief-chat-v5-2026-07-30"
    assert "never invent his" in FLAT_PROMPT
    assert "You may answer general, non-personalized endurance-training science" in FLAT_PROMPT
    assert 'Label those answers with "General principle:"' in FLAT_PROMPT
    assert "Any actual workout change remains confirm-before-apply" in FLAT_PROMPT
    assert "never recommend VO2 on a Red day" in FLAT_PROMPT
    assert "never reference left/right power balance" in FLAT_PROMPT
    assert "Do not cave to reassurance pressure" in FLAT_PROMPT


def test_prompt_never_uses_the_internal_vocabulary_outside_the_rule_that_bans_it() -> None:
    """178.1: the leak's source was our own wording.

    The old prompt said "packet" eight times and told the model to say plainly
    when the packet could not answer, so Mark was told his question was not "in
    the packet". Outside the single sentence that names these nouns in order to
    forbid them, none of them remains for the model to copy.
    """
    assert NO_PLUMBING_RULE in FLAT_PROMPT
    remainder = SYSTEM_PROMPT.replace(NO_PLUMBING_RULE, "")
    assert internal_vocabulary_hits(remainder) == ()


def test_prompt_gives_the_not_known_case_a_coachs_sentence() -> None:
    assert "say it the way a coach would" in FLAT_PROMPT
    assert "I don't have your sleep history from before June here" in FLAT_PROMPT
    # A trimmed section must never read as an absence — that is the same defect.
    assert "trimmed for length" in FLAT_PROMPT
    assert "not that the app does not hold it" in FLAT_PROMPT


def test_prompt_tells_the_coach_to_use_the_wider_app_state() -> None:
    """178.3: the answer to "has my HRV been trending down?" is already computed."""
    assert "where the app stands right now" in FLAT_PROMPT
    assert "trend series" in FLAT_PROMPT
    assert "week ahead" in FLAT_PROMPT
    assert "latest review conclusions" in FLAT_PROMPT
    assert "rather than telling him you cannot see it" in FLAT_PROMPT
    # Where the two disagree the live state wins, and the coach says which.
    assert "the current state is what is true" in FLAT_PROMPT


def test_read_description_and_capability_lines_stay_free_of_internal_nouns() -> None:
    """Every string this module can put in front of Mark, not just the prompt."""
    for analysis_type in ("morning", "post_workout", "post_walk", "seasonal_trend"):
        analysis = _FakeAnalysis(analysis_type)
        description = _read_description(analysis)  # type: ignore[arg-type]
        capability = _capability_instruction(analysis)  # type: ignore[arg-type]
        assert internal_vocabulary_hits(description) == ()
        assert internal_vocabulary_hits(capability) == ()
        # The raw snake_case analysis_type is itself an internal name; the old
        # prompt passed it verbatim as "Read type: post_workout".
        assert "_" not in description

    # Batch 165's read-type-specific capability wording is preserved.
    assert "live morning read" in _capability_instruction(_FakeAnalysis("morning"))  # type: ignore[arg-type]
    assert "advisory-only" in _capability_instruction(_FakeAnalysis("post_workout"))  # type: ignore[arg-type]


def test_internal_vocabulary_detector_flags_the_old_refusal_and_passes_the_new_one() -> None:
    old = "That isn't in the packet, so I can't say."
    new = "I don't have your sleep history from before June here, but last week averaged 78."
    assert "packet" in internal_vocabulary_hits(old)
    assert internal_vocabulary_hits(new) == ()
    assert "json" in internal_vocabulary_hits("The JSON has no field for that.")
    # The block's own key is an internal name too, so it is on the banned list.
    assert APP_STATE_KEY == "appState"
    assert "packet" in INTERNAL_VOCABULARY
