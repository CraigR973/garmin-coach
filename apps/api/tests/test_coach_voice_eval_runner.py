"""The paid paired eval reuses only complete pairs on one frozen context."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.run_coach_voice_eval import _complete_pair_is_current, _discard_stale_answers


def test_complete_pair_is_reused_without_reassembling_live_context() -> None:
    row = {
        "old": {"contextSha256": "before"},
        "new": {"contextSha256": "before", "promptSha256": "same-prompt"},
    }

    assert _complete_pair_is_current(row, prompt_hash="same-prompt", redo_new=True)


def test_incomplete_or_mismatched_pair_requires_fresh_context() -> None:
    row = {
        "old": {"contextSha256": "before"},
        "new": {"contextSha256": "after", "promptSha256": "same-prompt"},
    }

    assert not _complete_pair_is_current(row, prompt_hash="same-prompt", redo_new=True)
    row["new"]["contextSha256"] = "before"
    assert not _complete_pair_is_current(row, prompt_hash="new-prompt", redo_new=True)
    row.pop("old")
    assert not _complete_pair_is_current(row, prompt_hash="same-prompt", redo_new=True)


def test_matching_pair_is_reused_when_only_resuming() -> None:
    row = {
        "old": {"contextSha256": "same"},
        "new": {"contextSha256": "same", "promptSha256": "same-prompt"},
    }

    _discard_stale_answers(row, context_hash="same", prompt_hash="same-prompt", redo_new=True)

    assert set(row) == {"old", "new"}
