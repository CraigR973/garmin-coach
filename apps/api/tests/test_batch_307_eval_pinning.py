"""Batch 307 — the notes-reader eval catches a prompt change.

CI scores the reader's *recorded* responses, which cost money to make. Until this batch
nothing tied a recording to the prompt it answered: reword ``SYSTEM_PROMPT`` and CI went
on passing against evidence gathered for the old words. Batch 303 pinned the prompt's
version; this pins its text as well, and says what to do when either moves.

It also closes the other half of the same gap. A reading stored under an earlier prompt
was reused for ever, so a morning graded again after a prompt change still carried what
the old prompt read. It is now read again, in place, and a failed re-read keeps the
reading it had.

307.3's held-out notes were written and scored with Batch 303's paid run
(``tests/test_batch_303_medical_follow_through.py``).
"""

from __future__ import annotations

import ast
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from src.config import settings
from src.models.coaching import CheckInReading, ManualEntry
from src.services import notes_reader
from src.services.notes_eval import RERUN_THE_EVAL, stale_recording_reason
from src.services.notes_reader import (
    PROMPT_VERSION,
    STATUS_FAILED,
    STATUS_READ,
    SYSTEM_PROMPT,
    NotesReaderService,
    notes_hash,
    prompt_sha256,
)
from tests.test_batch_297_notes_reader import FakeNotesClient, _flag, _reading

REPO = Path(__file__).resolve().parents[3]
RECORDED = Path(__file__).parent / "fixtures" / "notes_eval_recorded"
RUN_SCRIPT = REPO / "scripts" / "run_notes_eval.py"


def _production_recording() -> dict[str, Any]:
    model = settings.notes_reader_model or settings.anthropic_model
    recording: dict[str, Any] = json.loads((RECORDED / f"{model}.json").read_text("utf-8"))
    return recording


# -- 307.2: the recording answers the prompt the reader sends today --------------------------


def test_the_production_models_recording_answers_todays_prompt() -> None:
    """The gate itself. It fails the moment the prompt's version or its text moves without
    a new paid run, and the failure says what to do."""
    reason = stale_recording_reason(_production_recording())
    assert reason is None, f"{reason} {RERUN_THE_EVAL}"


def test_the_pin_is_a_hash_of_the_prompts_own_text() -> None:
    assert prompt_sha256() == hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    recording = _production_recording()
    assert recording["promptVersion"] == PROMPT_VERSION
    assert recording["promptSha256"] == prompt_sha256()


def test_a_reworded_prompt_under_the_same_version_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case the version alone missed: the words change and the version does not."""
    recording = _production_recording()
    reworded = SYSTEM_PROMPT.replace("Heartburn or indigestion", "Heartburn, reflux or indigestion")
    assert reworded != SYSTEM_PROMPT
    monkeypatch.setattr(notes_reader, "SYSTEM_PROMPT", reworded)
    reason = stale_recording_reason(recording)
    assert reason is not None
    assert "prompt text has changed" in reason
    assert "re-run the eval" in RERUN_THE_EVAL.lower()
    assert "scripts/run_notes_eval.py run" in RERUN_THE_EVAL


def test_a_new_prompt_version_or_an_unpinned_recording_is_stale() -> None:
    recording = _production_recording()
    older = {**recording, "promptVersion": "notes-reader-v1-2026-09-30"}
    assert "notes-reader-v1-2026-09-30" in str(stale_recording_reason(older))
    unpinned = {key: value for key, value in recording.items() if key != "promptSha256"}
    assert "carries no prompt hash" in str(stale_recording_reason(unpinned))


def test_an_earlier_prompts_recording_is_kept_and_known_to_be_stale() -> None:
    """Haiku 4.5 was recorded under v1 and is not the production model. The report names
    it instead of scoring it (Batch 303); the pin agrees that it is stale."""
    haiku = json.loads((RECORDED / "claude-haiku-4-5-20251001.json").read_text("utf-8"))
    assert stale_recording_reason(haiku) is not None


def test_every_paid_run_records_the_hash_of_the_prompt_it_sent() -> None:
    tree = ast.parse(RUN_SCRIPT.read_text(encoding="utf-8"))
    recorded_keys = {
        key.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert {"promptVersion", "promptSha256"} <= recorded_keys
    source = RUN_SCRIPT.read_text(encoding="utf-8")
    assert "prompt_sha256()" in source
    # ...and the report scores only a recording that answers today's prompt.
    assert "if stale_recording_reason(recording) is not None:" in source


# -- 307.4: a reading made under an earlier prompt is read again ------------------------------


def _entry(notes: str) -> ManualEntry:
    return ManualEntry(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        entry_date=datetime(2026, 10, 9).date(),
        entry_at_utc=datetime(2026, 10, 9, 7, 0),
        notes=notes,
    )


def _stored(entry: ManualEntry, *, prompt_version: str, reading: dict[str, Any]) -> CheckInReading:
    return CheckInReading(
        id=uuid.uuid4(),
        user_id=entry.user_id,
        manual_entry_id=entry.id,
        notes_sha256=notes_hash(entry.notes),
        status=STATUS_READ,
        reading=reading,
        model_name="claude-test",
        prompt_version=prompt_version,
    )


def _service(existing: CheckInReading | None) -> tuple[NotesReaderService, Mock]:
    session = Mock()
    session.scalar = AsyncMock(return_value=existing)
    session.flush = AsyncMock()
    return NotesReaderService(session), session


@pytest.mark.asyncio
async def test_a_reading_under_todays_prompt_is_reused_and_costs_nothing() -> None:
    entry = _entry("Got breathless climbing the stairs, which never normally happens.")
    stored = _stored(entry, prompt_version=PROMPT_VERSION, reading=_reading())
    service, session = _service(stored)
    client = FakeNotesClient(_reading(chest_heart=_flag("present")))

    result = await service.ensure_reading(entry.user_id, [entry], client=client)

    assert result is stored
    assert client.calls == 0
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_reading_made_under_an_earlier_prompt_is_read_again_in_place() -> None:
    """Under v1 this note read as nothing: breathlessness was not a flag. On `main` that
    reading was reused for ever, so a regraded morning never saw what v2 reads in it."""
    entry = _entry("Got breathless climbing the stairs, which never normally happens.")
    stored = _stored(entry, prompt_version="notes-reader-v1-2026-09-30", reading=_reading())
    service, session = _service(stored)
    client = FakeNotesClient(_reading(chest_heart=_flag("present", words="breathless")))

    result = await service.ensure_reading(entry.user_id, [entry], client=client)

    assert client.calls == 1
    # The same row, so there is still one reading per check-in and note.
    assert result is stored
    assert (stored.status, stored.prompt_version) == (STATUS_READ, PROMPT_VERSION)
    assert stored.reading["chest_heart"]["state"] == "present"
    session.flush.assert_awaited_once()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_re_read_keeps_the_reading_it_had() -> None:
    """A re-read is an improvement, not a requirement. Losing a good reading to a failed
    call would take a floor his note had set away with it."""
    entry = _entry("Woke with a sore throat and a runny nose.")
    earlier = _reading(head_cold=_flag("present", words="sore throat"))
    stored = _stored(entry, prompt_version="notes-reader-v1-2026-09-30", reading=earlier)
    service, _session = _service(stored)
    failing = FakeNotesClient(error=True)

    result = await service.ensure_reading(entry.user_id, [entry], client=failing)

    assert failing.calls == 1
    assert result is stored
    assert stored.status == STATUS_READ
    assert stored.reading == earlier
    # Still marked as the earlier prompt's, so the next grading tries again.
    assert stored.prompt_version == "notes-reader-v1-2026-09-30"


@pytest.mark.asyncio
async def test_a_failed_first_reading_is_still_recorded_as_failed() -> None:
    """Unchanged from Batch 297: with nothing to fall back on, the failure is stored and
    retried in place by the next grading."""
    entry = _entry("Woke with a sore throat and a runny nose.")
    stored = _stored(entry, prompt_version=PROMPT_VERSION, reading={})
    stored.status = STATUS_FAILED
    service, _session = _service(stored)

    await service.ensure_reading(entry.user_id, [entry], client=FakeNotesClient(error=True))
    assert stored.status == STATUS_FAILED

    working = FakeNotesClient(_reading(head_cold=_flag("present")))
    result = await service.ensure_reading(entry.user_id, [entry], client=working)
    assert result is stored
    assert (stored.status, stored.reading["head_cold"]["state"]) == (STATUS_READ, "present")
