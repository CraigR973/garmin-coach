"""The paid paired eval must never reuse answers from a different context."""

from scripts.run_coach_voice_eval import _discard_stale_answers


def test_complete_pair_is_invalidated_after_a_context_change() -> None:
    row = {
        "old": {"contextSha256": "before"},
        "new": {"contextSha256": "before", "promptSha256": "same-prompt"},
    }

    _discard_stale_answers(row, context_hash="after", prompt_hash="same-prompt", redo_new=True)

    assert "old" not in row
    assert "new" not in row


def test_matching_pair_is_reused_when_only_resuming() -> None:
    row = {
        "old": {"contextSha256": "same"},
        "new": {"contextSha256": "same", "promptSha256": "same-prompt"},
    }

    _discard_stale_answers(row, context_hash="same", prompt_hash="same-prompt", redo_new=True)

    assert set(row) == {"old", "new"}
