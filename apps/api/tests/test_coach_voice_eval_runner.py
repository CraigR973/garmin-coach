"""The paid paired eval reuses only complete pairs on one frozen context."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.run_coach_voice_eval import (
    _complete_pair_is_current,
    _discard_stale_answers,
    _FrozenEvalTools,
    _refresh_saved_delivery_fallback,
    _validate_frozen_case5,
)

from src.services.brief_chat import FINAL_REPLY_RULE, SYSTEM_PROMPT


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


def test_server_fallback_refreshes_only_a_current_no_tool_correction() -> None:
    row = {
        "case": 4,
        "new": {
            "answer": "You're right. I had that backwards.",
            "promptSha256": "current",
            "toolUses": 0,
        },
    }

    assert not _refresh_saved_delivery_fallback(row, prompt_hash="older")
    assert _refresh_saved_delivery_fallback(row, prompt_hash="current")
    assert row["new"]["modelAnswer"] == "You're right. I had that backwards."
    assert row["new"]["answer"].endswith("I've passed that correction to Craig.")
    assert row["new"]["serverFallbackPassOn"]
    assert not _refresh_saved_delivery_fallback(row, prompt_hash="current")

    row["new"]["toolUses"] = 1
    row["new"].pop("serverFallbackPassOn")
    assert not _refresh_saved_delivery_fallback(row, prompt_hash="current")


def test_frozen_case5_requires_earlier_read_current_prompt_and_same_content() -> None:
    common = {
        "sourceQuestionAtUtc": "2026-10-07T17:27:22",
        "sourceReadAtUtc": "2026-10-07T16:32:52",
        "question": "Has this changed?",
        "prior": [],
        "readPrefix": "The 7 Oct read.",
        "scope": "Frozen read only.",
    }
    fixture = {
        **common,
        "contextSha256": hashlib.sha256(json.dumps(common, sort_keys=True).encode()).hexdigest(),
        "newSystem": [
            {"type": "text", "text": SYSTEM_PROMPT + "\n\n" + common["readPrefix"]},
            {"type": "text", "text": FINAL_REPLY_RULE},
        ],
    }

    assert _validate_frozen_case5(fixture) == fixture["contextSha256"]
    fixture["readPrefix"] = "The 14 Oct check-in."
    with pytest.raises(ValueError, match="hash"):
        _validate_frozen_case5(fixture)
    fixture["contextSha256"] = hashlib.sha256(
        json.dumps({key: fixture[key] for key in common}, sort_keys=True).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="later 14 Oct"):
        _validate_frozen_case5(fixture)
    fixture["sourceReadAtUtc"] = "2026-10-08T08:00:00"
    with pytest.raises(ValueError, match="precede"):
        _validate_frozen_case5(fixture)


@pytest.mark.asyncio
async def test_frozen_case5_never_uses_live_history_tools() -> None:
    toolbox = _FrozenEvalTools(None, SimpleNamespace(id="frozen"), "Has this changed?")

    blocked = await toolbox.execute(tool_use_id="one", name="get_activities", payload={})
    sent = await toolbox.execute(
        tool_use_id="two",
        name="pass_to_craig",
        payload={"summary": "Mark reports a missing change."},
    )

    assert blocked.is_error
    assert sent.content.startswith("Alert succeeded.")
    assert toolbox.passed_to_craig
