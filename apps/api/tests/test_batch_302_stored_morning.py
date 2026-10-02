"""Batch 302 — the colour and the floors survive a failed brief.

The morning row is stored when the morning is graded, with its prose empty, and the
brief is written into it afterwards. Before this batch the row was written only after
the paid call returned, so an Anthropic outage took the colour, the medical floors, the
plan lines and the ride changes with the prose: on 21 Jul 2026 Mark checked in at 08:35
UTC and had no colour until 18:07, on a Red day.

302.5's tests. The pure ones pin the rules; the Postgres ones at the foot run the real
pipeline through a credit 400 and a spend-cap 400 and show what is left standing.
"""

from __future__ import annotations

import ast
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import (
    Analysis,
    BriefGenerationStatus,
    CheckInReading,
    GenerationRequest,
    ManualEntry,
    PlannedWorkout,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.routers import daily_loop as daily_loop_router
from src.services import morning_analysis as morning_analysis_module
from src.services.anthropic_text import AnthropicApiError, classify_anthropic_error
from src.services.brief_chat import (
    BRIEF_NOT_WRITTEN_NOTE,
    _build_system_prompt_prefix,
)
from src.services.brief_generation_status import (
    STATUS_FAILED,
    STATUS_GENERATING,
    STATUS_READY,
)
from src.services.bulk_history_reads import select_morning_calls
from src.services.chat_context import CoachOrigin
from src.services.coach_tools import BRIEF_NOT_WRITTEN_MEANING, CoachToolbox
from src.services.daily_loop_envelope import (
    STALE_GENERATING_REASON,
    _serialize_analysis,
    _serialize_brief_generation,
    split_stored_morning,
)
from src.services.delivered_verdict import delivered_verdicts
from src.services.disputes import DisputeService
from src.services.executable_coaching import ExecutableCoachingService
from src.services.generation_requests import (
    GENERATION_IDENTITY_KEY,
    STATUS_COMPLETED,
    GenerationClaim,
    GenerationRequestInProgress,
    _identity,
    manual_entry_generation_version,
    morning_generation_identity,
)
from src.services.graded_morning import (
    BRIEF_NOT_WRITTEN,
    BRIEF_WRITTEN_AT_KEY,
    brief_is_written,
    brief_written_at,
    stamp_brief_written_at,
)
from src.services.morning_analysis import (
    PROMPT_VERSION,
    ClaudeGenerationResult,
    GradedMorning,
    MorningAnalysisError,
    MorningAnalysisService,
    _stored_morning_stands,
)
from src.services.morning_inputs import MorningInputPresence
from src.services.morning_pipeline import (
    BACKSTOP_POLICY,
    CHECKIN_POLICY,
    RETRY_POLICY,
    CommitPolicy,
    MorningBriefPipeline,
    MorningTrigger,
    run_brief_retry,
)
from src.services.notes_reader import STATUS_FAILED as NOTES_FAILED
from src.services.notes_reader import STATUS_READ as NOTES_READ
from src.services.nudge_alerts import (
    ANALYSIS_TYPE_BRIEF_READY,
    ANALYSIS_TYPE_CALL_READY,
    CALL_READY_FALLBACK_BODY,
    build_brief_ready_plan,
    build_call_ready_plan,
)
from src.services.verdict_scaling import blocks_red_vo2
from src.services.workout_delivery import build_structured_workout_ir
from tests.test_batch_296_graded_colour import _seed_one_poor_night
from tests.test_batch_297_notes_reader import FakeNotesClient, _flag, _reading
from tests.test_morning_analysis import FakeMorningClient
from tests.test_morning_pipeline import _morning, _nudges, _profile, _ready, _session_ctx, _status

SRC = Path(morning_analysis_module.__file__).resolve().parent.parent

DAY = date(2026, 10, 7)
PRESENT = MorningInputPresence(daily_metrics=True, sleep=True)

#: The two Anthropic 400s that have stopped a paid call, in the provider's own words.
CREDIT_400 = "Your credit balance is too low to access the Anthropic API."
SPEND_CAP_400 = (
    "You have reached your specified API usage limits. You will regain access on "
    "2026-09-01 at 00:00 UTC."
)


def _billing_error(message: str) -> AnthropicApiError:
    """The error the real client raises for one of those 400s."""
    reason = classify_anthropic_error(
        400, error_type="invalid_request_error", error_message=message
    )
    return AnthropicApiError(message, reason=reason, status_code=400)


# -- the generation identity: a changed symptom answer is a changed input ---------------


def _entry(**overrides: Any) -> ManualEntry:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "entry_date": DAY,
        "entry_at_utc": datetime(2026, 10, 7, 7, 0),
        "subjective_score": 7,
        "feel": "good",
        "supplements_json": {},
        "food_json": {},
        "actual_workout_json": {},
        "notes": "Slept ok.",
        "symptoms": "none",
    }
    fields.update(overrides)
    return ManualEntry(**fields)


def test_a_changed_symptom_answer_is_a_changed_input() -> None:
    """Batch 294 added the answer and did not hash it, so re-saving a check-in with only
    a new answer shared the stored brief's identity and regraded nothing. Run on `main`,
    "none" and "chest_heart" hashed alike."""
    none = manual_entry_generation_version(_entry(symptoms="none"))
    chest = manual_entry_generation_version(_entry(symptoms="chest_heart"))
    cold = manual_entry_generation_version(_entry(symptoms="head_cold"))
    assert len({none, chest, cold}) == 3


def test_a_re_save_that_changes_nothing_keeps_the_identity() -> None:
    """Only the content is hashed, never the save's timestamp: a second save of the
    same check-in is the same request, and the stored morning stands."""
    first = _entry()
    again = _entry(entry_at_utc=first.entry_at_utc + timedelta(minutes=30))
    assert manual_entry_generation_version(first) == manual_entry_generation_version(again)


def test_an_unanswered_check_in_keeps_the_identity_it_had() -> None:
    """An activity check-in never carries the answer, so its identity must not move."""
    entry = _entry(symptoms=None, activity_id=uuid.uuid4())
    before_the_batch = _identity(
        {
            "plannedWorkoutId": None,
            "activityId": str(entry.activity_id),
            "plannedWorkoutVersion": None,
            "bpSystolic": None,
            "bpDiastolic": None,
            "subjectiveScore": "7",
            "rpe": None,
            "feel": "good",
            "adherenceStatus": None,
            "actualWorkout": "{}",
            "supplements": "{}",
            "food": "{}",
            "notes": "Slept ok.",
        }
    )
    assert manual_entry_generation_version(entry) == before_the_batch


# -- what "written" means ---------------------------------------------------------------


def _stored(**overrides: Any) -> Analysis:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "analysis_type": "morning",
        "subject_date": DAY,
        "generated_at_utc": datetime(2026, 10, 7, 7, 1),
        "prompt_version": PROMPT_VERSION,
        "model_name": None,
        "verdict": "Red",
        "context_packet": {
            "packetType": "morning_analysis",
            "subjectDate": DAY.isoformat(),
            "dailyMetrics": {},
            "sleep": {},
            "verdict": {"status": "Red", "reasons": ["A head cold: easy riding at most."]},
            GENERATION_IDENTITY_KEY: "identity-a",
        },
        "output_markdown": BRIEF_NOT_WRITTEN,
        "raw_response": {},
    }
    fields.update(overrides)
    return Analysis(**fields)


def test_a_morning_is_written_only_when_it_carries_prose() -> None:
    assert brief_is_written(None) is False
    assert brief_is_written(_stored()) is False
    assert brief_is_written(_stored(output_markdown="  \n")) is False
    assert brief_is_written(_stored(output_markdown="**Verdict:** Red.")) is True


def test_the_briefs_own_time_is_kept_beside_the_providers_response() -> None:
    raw: dict[str, Any] = {"id": "msg_1"}
    stamp_brief_written_at(raw, now=datetime(2026, 10, 7, 17, 7, 45, 123456))
    assert raw == {"id": "msg_1", BRIEF_WRITTEN_AT_KEY: "2026-10-07T17:07:45Z"}
    assert brief_written_at(raw) == "2026-10-07T17:07:45Z"
    assert brief_written_at({}) is None  # a brief stored before the batch
    assert brief_written_at(None) is None


# -- when a stored morning stands -------------------------------------------------------


def test_a_stored_morning_stands_on_the_same_inputs_forced_or_not() -> None:
    stored = _stored()
    for force in (True, False):
        assert _stored_morning_stands(
            stored, request_identity="identity-a", input_presence=PRESENT, force=force
        )


def test_a_changed_input_regrades_a_forced_run_and_only_a_forced_run() -> None:
    """The check-in forces: a new answer is a new morning. The backstop does not: a
    morning whose proven presence still matches is the one Mark was shown."""
    stored = _stored()
    assert not _stored_morning_stands(
        stored, request_identity="identity-b", input_presence=PRESENT, force=True
    )
    assert _stored_morning_stands(
        stored, request_identity="identity-b", input_presence=PRESENT, force=False
    )
    # ...but never across a change in what the app can prove it has.
    late_sleep = MorningInputPresence(daily_metrics=True, sleep=False)
    assert not _stored_morning_stands(
        stored, request_identity="identity-b", input_presence=late_sleep, force=False
    )


def test_a_morning_graded_under_another_prompt_never_stands() -> None:
    stored = _stored(prompt_version="morning-analysis-v1-2026-06-21")
    assert not _stored_morning_stands(
        stored, request_identity="identity-a", input_presence=PRESENT, force=False
    )


# -- grading: the morning is stored before any brief is written -------------------------


class _RecordingClient:
    """A morning client that remembers what it was asked to write from."""

    def __init__(self, markdown: str = "**Verdict:** Red.", error: Exception | None = None) -> None:
        self.markdown = markdown
        self.error = error
        self.calls = 0
        self.packets: list[dict[str, Any]] = []

    async def generate(
        self, *, context_packet: dict[str, Any], user_prompt: str
    ) -> ClaudeGenerationResult:
        self.calls += 1
        self.packets.append(context_packet)
        if self.error is not None:
            raise self.error
        return ClaudeGenerationResult(
            output_markdown=self.markdown,
            raw_response={"id": "msg_1", "usage": {"output_tokens": 12}},
            model_name="claude-test",
        )


def _grading_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entry: ManualEntry,
    stored: Analysis | None,
    reading_status: str | None = None,
) -> tuple[MorningAnalysisService, AsyncMock, MagicMock, AsyncMock]:
    """The morning service over a mocked session: what it stores, and when."""
    session = AsyncMock()
    session.add = MagicMock()
    service = MorningAnalysisService(session)
    assemble = AsyncMock(
        return_value={
            "packetType": "morning_analysis",
            "subjectDate": DAY.isoformat(),
            "dailyMetrics": {},
            "sleep": {},
            "verdict": {"status": "Red"},
        }
    )
    notes = MagicMock()
    notes.ensure_reading = AsyncMock(
        return_value=None if reading_status is None else MagicMock(status=reading_status)
    )
    monkeypatch.setattr(service, "_manual_entries", AsyncMock(return_value=[entry]))
    monkeypatch.setattr(service, "latest_analysis", AsyncMock(return_value=stored))
    monkeypatch.setattr(service, "assemble_context_packet", assemble)
    monkeypatch.setattr(
        morning_analysis_module, "morning_input_presence", AsyncMock(return_value=PRESENT)
    )
    monkeypatch.setattr(morning_analysis_module, "acquire_artifact_scope", AsyncMock())
    monkeypatch.setattr(
        morning_analysis_module, "NotesReaderService", MagicMock(return_value=notes)
    )
    return service, session, notes, assemble


def _identity_for(player: Any, entry: ManualEntry) -> str:
    return morning_generation_identity(
        user_id=player.id,
        subject_date=DAY,
        input_version=manual_entry_generation_version(entry),
        input_completeness_version=PRESENT.version,
        prompt_version=PROMPT_VERSION,
    )


def _packet_with(identity: str, notes_status: str | None = None) -> dict[str, Any]:
    verdict: dict[str, Any] = {"status": "Amber"}
    if notes_status is not None:
        verdict["notesReading"] = {"status": notes_status}
    return {"dailyMetrics": {}, "sleep": {}, "verdict": verdict, GENERATION_IDENTITY_KEY: identity}


@pytest.mark.asyncio
async def test_the_morning_is_stored_and_committed_before_any_paid_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole batch in one test: grading stores the row with its prose empty and
    commits, and takes no claim, because the claim is what covers the paid call."""
    player = _profile()
    entry = _entry()
    service, session, _notes, _assemble = _grading_service(monkeypatch, entry=entry, stored=None)
    claim = MagicMock(side_effect=AssertionError("grading must not take the paid claim"))
    monkeypatch.setattr(morning_analysis_module, "claim_generation_request", claim)

    morning = await service.grade_and_store(player, DAY, force=True)

    assert isinstance(morning, GradedMorning)
    assert (morning.graded, morning.written) == (True, False)
    [stored] = [call.args[0] for call in session.add.call_args_list]
    assert stored is morning.analysis
    assert stored.analysis_type == "morning"
    assert stored.verdict == "Red"
    assert stored.output_markdown == ""
    assert stored.model_name is None
    assert stored.raw_response == {}
    assert stored.context_packet[GENERATION_IDENTITY_KEY] == _identity_for(player, entry)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_retry_writes_the_brief_for_the_morning_mark_was_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored morning graded on these inputs stands: nothing is graded again, his
    note is not read again, and the colour cannot move under him."""
    player = _profile()
    entry = _entry()
    stored = _stored(context_packet=_packet_with(_identity_for(player, entry), NOTES_READ))
    service, session, notes, assemble = _grading_service(monkeypatch, entry=entry, stored=stored)

    morning = await service.grade_and_store(player, DAY, force=True)

    assert morning.analysis is stored
    assert (morning.graded, morning.written) == (False, False)
    assemble.assert_not_awaited()
    notes.ensure_reading.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_awaited_once()  # the scope is released on every path


@pytest.mark.asyncio
async def test_a_new_symptom_answer_regrades_a_morning_that_already_has_a_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = _profile()
    answered_none = _entry(symptoms="none")
    brief = _stored(
        context_packet=_packet_with(_identity_for(player, answered_none)),
        output_markdown="**Verdict:** Amber.",
        verdict="Amber",
    )
    now_chest = _entry(symptoms="chest_heart")
    service, session, _notes, assemble = _grading_service(
        monkeypatch, entry=now_chest, stored=brief
    )

    morning = await service.grade_and_store(player, DAY, force=True)

    assert morning.graded is True
    assert morning.analysis is not brief
    assert morning.written is False
    assemble.assert_awaited_once()
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_a_note_unread_in_an_outage_is_read_and_regraded_on_the_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In a full outage the notes reader fails too, so the morning is graded without
    his note. The retry reads it, and a symptom he wrote is not lost."""
    player = _profile()
    entry = _entry(notes="Chest feels tight this morning.")
    stored = _stored(context_packet=_packet_with(_identity_for(player, entry), NOTES_FAILED))
    service, session, notes, assemble = _grading_service(
        monkeypatch, entry=entry, stored=stored, reading_status=NOTES_READ
    )

    morning = await service.grade_and_store(player, DAY, force=True)

    assert morning.graded is True
    assert morning.analysis is not stored
    assemble.assert_awaited_once()
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_a_note_that_still_cannot_be_read_keeps_the_stored_morning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrying through a long outage must not pile up a row a tap."""
    player = _profile()
    entry = _entry(notes="Chest feels tight this morning.")
    stored = _stored(context_packet=_packet_with(_identity_for(player, entry), NOTES_FAILED))
    service, session, notes, assemble = _grading_service(
        monkeypatch, entry=entry, stored=stored, reading_status=NOTES_FAILED
    )

    morning = await service.grade_and_store(player, DAY, force=True)

    assert morning.analysis is stored
    assert morning.graded is False
    notes.ensure_reading.assert_awaited_once()
    assemble.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_a_written_brief_is_not_regraded_for_an_unread_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unchanged from before the batch: a written brief already says it could not read
    his note, and regrading it would pay for a second brief."""
    player = _profile()
    entry = _entry(notes="Chest feels tight this morning.")
    brief = _stored(
        context_packet=_packet_with(_identity_for(player, entry), NOTES_FAILED),
        output_markdown="**Verdict:** Amber. I could not read your note today.",
    )
    service, _session, notes, assemble = _grading_service(
        monkeypatch, entry=entry, stored=brief, reading_status=NOTES_READ
    )

    morning = await service.grade_and_store(player, DAY, force=True)

    assert morning.analysis is brief
    assert morning.written is True
    notes.ensure_reading.assert_not_awaited()
    assemble.assert_not_awaited()


# -- writing: the brief goes into the stored morning ------------------------------------


def _writing_service(
    monkeypatch: pytest.MonkeyPatch, stored: Analysis | None
) -> tuple[MorningAnalysisService, AsyncMock, list[GenerationClaim]]:
    session = AsyncMock()
    service = MorningAnalysisService(session)
    claims: list[GenerationClaim] = []

    @asynccontextmanager
    async def claim_request(*_args: Any, **kwargs: Any) -> AsyncIterator[GenerationClaim]:
        claim = GenerationClaim(row=MagicMock(), existing_analysis=None)
        claim.row.requested_identity = kwargs["request_identity"]
        claims.append(claim)
        yield claim

    monkeypatch.setattr(service, "latest_analysis", AsyncMock(return_value=stored))
    monkeypatch.setattr(morning_analysis_module, "claim_generation_request", claim_request)
    return service, session, claims


@pytest.mark.asyncio
async def test_the_brief_is_written_into_the_stored_morning_from_its_own_packet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored()
    packet = stored.context_packet
    service, _session, claims = _writing_service(monkeypatch, stored)
    client = _RecordingClient()

    result = await service.write_brief(_profile(), DAY, client=client)

    assert result.generated is True
    assert result.analysis is stored  # the same row: nothing is inserted beside it
    assert client.packets == [packet]  # written from the packet it was graded on
    assert stored.context_packet is packet  # which the brief does not touch
    assert stored.verdict == "Red"
    assert stored.output_markdown == "**Verdict:** Red."
    assert stored.model_name == "claude-test"
    assert stored.raw_response["usage"] == {"output_tokens": 12}
    assert brief_written_at(stored.raw_response) is not None
    [claim] = claims
    # The claim is the stored morning's own identity, and it completes on that row.
    assert claim.row.requested_identity == "identity-a"
    assert claim.row.status == STATUS_COMPLETED
    assert claim.row.analysis_id == stored.id


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [CREDIT_400, SPEND_CAP_400])
async def test_a_failed_paid_call_leaves_the_stored_morning_exactly_as_it_was(
    monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    stored = _stored()
    service, _session, _claims = _writing_service(monkeypatch, stored)
    client = _RecordingClient(error=_billing_error(message))

    with pytest.raises(AnthropicApiError) as raised:
        await service.write_brief(_profile(), DAY, client=client)

    assert raised.value.reason == "billing"  # both wordings, since Batch 248
    assert stored.verdict == "Red"
    assert stored.output_markdown == ""
    assert stored.model_name is None
    assert stored.raw_response == {}


@pytest.mark.asyncio
async def test_an_empty_brief_is_refused_because_empty_means_not_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored()
    service, _session, _claims = _writing_service(monkeypatch, stored)

    with pytest.raises(MorningAnalysisError, match="empty"):
        await service.write_brief(_profile(), DAY, client=_RecordingClient(markdown="  \n"))

    assert brief_is_written(stored) is False


@pytest.mark.asyncio
async def test_a_written_morning_is_never_paid_for_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = _stored(output_markdown="**Verdict:** Red.")
    service, _session, claims = _writing_service(monkeypatch, brief)
    client = _RecordingClient()

    result = await service.write_brief(_profile(), DAY, client=client)

    assert (result.generated, result.analysis) == (False, brief)
    assert client.calls == 0
    assert claims == []


@pytest.mark.asyncio
async def test_a_brief_is_not_written_from_another_prompts_packet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _stored(prompt_version="morning-analysis-v1-2026-06-21")
    service, _session, _claims = _writing_service(monkeypatch, stale)
    client = _RecordingClient()

    with pytest.raises(MorningAnalysisError, match="another prompt version"):
        await service.write_brief(_profile(), DAY, client=client)

    assert client.calls == 0


# -- the pipeline: three stages, and what a failure in each one costs --------------------


def _coaching() -> MagicMock:
    coaching = MagicMock()
    coaching.regenerate_for_verdict = AsyncMock(return_value=[MagicMock()])
    coaching.propose_chronic_deload = AsyncMock(return_value=[])
    return coaching


def _pipeline(
    session: AsyncMock,
    policy: Any,
    *,
    morning: MagicMock,
    coaching: MagicMock | None = None,
    status: MagicMock | None = None,
    nudges: MagicMock | None = None,
) -> MorningBriefPipeline:
    pipeline = MorningBriefPipeline(session, policy=policy, morning_service=morning)
    pipeline.coaching = coaching or _coaching()
    pipeline.status = status or _status()
    pipeline.nudges = nudges or _nudges()
    pipeline.insights = MagicMock(record_drivers=AsyncMock(return_value=MagicMock(record_count=0)))
    return pipeline


@pytest.mark.asyncio
async def test_the_ride_changes_no_longer_wait_for_the_paid_call() -> None:
    """Grade, then the ride changes, then the brief. Before the batch the proposals ran
    after the paid call and inside its transaction, so a failed call offered no ride."""
    order: list[str] = []
    morning = _morning()
    coaching = _coaching()
    status = _status()
    nudges = _nudges()

    def record(name: str, mock: AsyncMock) -> None:
        result = mock.return_value

        async def run(*_args: Any, **_kwargs: Any) -> Any:
            order.append(name)
            return result

        mock.side_effect = run

    record("grade", morning.grade_and_store)
    record("proposals", coaching.regenerate_for_verdict)
    record("deload", coaching.propose_chronic_deload)
    record("brief", morning.write_brief)
    record("ready push", nudges.push_brief_ready)
    record("ready", status.mark_ready)

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = _pipeline(
            AsyncMock(),
            CHECKIN_POLICY,
            morning=morning,
            coaching=coaching,
            status=status,
            nudges=nudges,
        )
        outcome = await pipeline.generate_brief(_profile(), DAY)

    assert order == ["grade", "proposals", "deload", "brief", "ready push", "ready"]
    assert (outcome.generated, outcome.failures) == (True, 0)
    assert outcome.proposals_regenerated == 1
    # Both stages read the stored morning; the brief's own analysis is what is pushed.
    graded = morning.grade_and_store.return_value.analysis
    assert coaching.regenerate_for_verdict.await_args.kwargs["analysis"] is graded
    assert nudges.push_brief_ready.await_args.args[1] is morning.write_brief.return_value.analysis


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [CREDIT_400, SPEND_CAP_400])
@pytest.mark.parametrize("policy", [CHECKIN_POLICY, BACKSTOP_POLICY, RETRY_POLICY])
async def test_a_failed_brief_leaves_the_colour_and_the_ride_proposal(
    message: str, policy: Any
) -> None:
    """A credit 400 and a spend-cap 400, through every trigger: the morning was stored
    and its ride changes proposed before the call, the failure is recorded under them,
    and he is told the colour is there."""
    session = AsyncMock()
    morning = _morning()
    morning.write_brief = AsyncMock(side_effect=_billing_error(message))
    coaching = _coaching()
    status = _status()
    nudges = _nudges()
    profile = _profile()

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = _pipeline(
            session, policy, morning=morning, coaching=coaching, status=status, nudges=nudges
        )
        outcome = await pipeline.generate_brief(profile, DAY)

    graded = morning.grade_and_store.return_value.analysis
    assert outcome.analysis is graded  # the stored morning outlives the failure
    assert (outcome.generated, outcome.failures) == (False, 1)
    assert outcome.proposals_regenerated == 1
    coaching.regenerate_for_verdict.assert_awaited_once()
    status.mark_failed.assert_awaited_once_with(profile.id, DAY, reason="billing", commit=True)
    assert nudges.notify_admin_generation_failure.await_args.kwargs["reason"] == "billing"
    status.mark_ready.assert_not_awaited()
    nudges.push_brief_ready.assert_not_awaited()
    nudges.push_call_ready.assert_awaited_once()
    assert nudges.push_call_ready.await_args.args[1] is graded
    assert outcome.call_ready_pushes == 1


@pytest.mark.asyncio
async def test_a_morning_that_cannot_be_graded_sends_no_call_ready_push() -> None:
    """There is no colour to announce, so the old failure card stands alone."""
    morning = _morning()
    morning.grade_and_store = AsyncMock(side_effect=RuntimeError("database went away"))
    status = _status()
    nudges = _nudges()

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = _pipeline(
            AsyncMock(), CHECKIN_POLICY, morning=morning, status=status, nudges=nudges
        )
        outcome = await pipeline.generate_brief(_profile(), DAY)

    assert outcome.failures == 1
    assert outcome.analysis is None
    status.mark_failed.assert_awaited_once()
    morning.write_brief.assert_not_awaited()
    nudges.push_call_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_morning_whose_brief_is_written_pays_for_nothing() -> None:
    morning = _morning(written=True)
    status = _status()
    nudges = _nudges()

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = _pipeline(
            AsyncMock(), CHECKIN_POLICY, morning=morning, status=status, nudges=nudges
        )
        outcome = await pipeline.generate_brief(_profile(), DAY)

    assert (outcome.existing, outcome.generated, outcome.failures) == (True, False, 0)
    morning.write_brief.assert_not_awaited()
    status.mark_generating.assert_not_awaited()  # nothing is on its way
    status.mark_ready.assert_awaited_once()
    nudges.push_brief_ready.assert_awaited_once()  # the check-in pushes when unchanged


@pytest.mark.asyncio
async def test_a_stored_morning_without_its_brief_says_a_brief_is_on_its_way() -> None:
    """The backstop has no request to mark this from, so the pipeline does, once the
    morning is stored and before the paid call."""
    order: list[str] = []
    morning = _morning()
    status = _status()
    status.mark_generating.side_effect = lambda *_a, **_k: order.append("generating")
    morning.write_brief.side_effect = lambda *_a, **_k: (
        order.append("brief") or MagicMock(generated=True, analysis=MagicMock())
    )

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = _pipeline(AsyncMock(), BACKSTOP_POLICY, morning=morning, status=status)
        await pipeline.generate_brief(_profile(), DAY)

    assert order == ["generating", "brief"]
    status.mark_generating.assert_awaited_once()
    assert status.mark_generating.await_args.kwargs == {"commit": True}


@pytest.mark.asyncio
async def test_a_brief_another_worker_is_writing_is_deferred_not_failed() -> None:
    """Batch 232.1, at the stage the paid call now lives in."""
    morning = _morning()
    morning.write_brief = AsyncMock(side_effect=GenerationRequestInProgress())
    status = _status()
    nudges = _nudges()

    with patch("src.services.morning_pipeline.morning_input_presence", _ready()):
        pipeline = _pipeline(
            AsyncMock(), CHECKIN_POLICY, morning=morning, status=status, nudges=nudges
        )
        outcome = await pipeline.generate_brief(_profile(), DAY)

    assert (outcome.deferred, outcome.failures) == (True, 0)
    status.mark_failed.assert_not_awaited()
    status.mark_ready.assert_not_awaited()
    nudges.push_call_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_ride_changes_another_worker_holds_are_deferred_not_failed() -> None:
    """The proposals took the claim's lock while they shared its transaction. They
    take the same scope for their own now, and a run that cannot have it stands down."""
    morning = _morning()
    status = _status()
    with (
        patch("src.services.morning_pipeline.morning_input_presence", _ready()),
        patch(
            "src.services.morning_pipeline.acquire_artifact_scope",
            AsyncMock(side_effect=GenerationRequestInProgress()),
        ),
    ):
        for policy in (CHECKIN_POLICY, BACKSTOP_POLICY):
            pipeline = _pipeline(AsyncMock(), policy, morning=morning, status=status)
            outcome = await pipeline.generate_brief(_profile(), DAY)
            assert (outcome.deferred, outcome.failures) == (True, 0)

    morning.write_brief.assert_not_awaited()
    status.mark_failed.assert_not_awaited()
    pipeline.coaching.regenerate_for_verdict.assert_not_awaited()


# -- "Try again" is its own request, and saves nothing ----------------------------------


def test_the_retry_is_the_check_ins_run_without_the_check_in() -> None:
    assert RETRY_POLICY.trigger is MorningTrigger.RETRY
    assert RETRY_POLICY.commit is CommitPolicy.TERMINAL
    # Forced, so a check-in changed since the stored morning is graded, not aliased.
    # A stored morning graded on today's inputs still stands: see the identity tests.
    assert RETRY_POLICY.force_regenerate is True
    assert RETRY_POLICY.allow_missing_sleep is CHECKIN_POLICY.allow_missing_sleep
    assert RETRY_POLICY.precompute_drivers is False


@pytest.mark.asyncio
async def test_the_retry_syncs_inputs_then_runs_the_pipeline_under_its_own_policy() -> None:
    profile = _profile()
    session = AsyncMock()
    session.get = AsyncMock(return_value=profile)
    seen: list[tuple[str, Any]] = []

    async def sync(pipeline: MorningBriefPipeline, _profiles: list[Any]) -> None:
        seen.append(("sync", pipeline.policy.trigger))

    async def generate(pipeline: MorningBriefPipeline, *_a: Any, **_k: Any) -> MagicMock:
        seen.append(("generate", pipeline.policy.trigger))
        return MagicMock()

    with (
        patch(
            "src.services.morning_pipeline.AsyncSessionLocal", return_value=_session_ctx(session)
        ),
        patch.object(MorningBriefPipeline, "sync_inputs", sync),
        patch.object(MorningBriefPipeline, "generate_brief", generate),
    ):
        await run_brief_retry(profile.id, DAY)

    assert seen == [("sync", MorningTrigger.RETRY), ("generate", MorningTrigger.RETRY)]


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    [node] = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    ]
    return node


def _calls(node: ast.AST) -> set[str]:
    return {
        call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    }


def test_neither_the_retry_route_nor_its_run_saves_a_check_in() -> None:
    """The reason the retry is a route at all. A save moves the check-in's timestamp
    past a stored note reading, after which the preselected "None" governs and a symptom
    found in his note is dropped (`notes_reader._answered_after`)."""
    router = ast.parse((SRC / "routers" / "daily_loop.py").read_text())
    route = _calls(_function(router, "retry_morning_brief"))
    assert "upsert_manual_entry" not in route
    assert {"mark_generating", "add_task"} <= route
    # The save route is the one that does, so the two are visibly different requests.
    assert "upsert_manual_entry" in _calls(_function(router, "upsert_manual_entry"))

    pipeline_source = (SRC / "services" / "morning_pipeline.py").read_text()
    assert "upsert_manual_entry" not in pipeline_source
    assert "entry_at_utc" not in pipeline_source


# -- the envelope: a morning without its brief travels on its own ------------------------


def test_a_morning_without_its_brief_is_not_a_morning_analysis() -> None:
    """`morningAnalysis` keeps meaning a written brief, so an app build cached from
    before the batch reads such a morning as it always did: no brief yet."""
    stored = _stored()
    serialized = _serialize_analysis(stored)
    assert serialized is not None

    morning_analysis, graded_morning = split_stored_morning(stored, serialized)

    assert morning_analysis is None
    assert graded_morning is serialized
    assert graded_morning.verdict == "red"
    assert graded_morning.outputMarkdown == ""
    assert graded_morning.reasons == ["A head cold: easy riding at most."]
    assert graded_morning.briefWrittenAtUtc is None


def test_a_written_brief_is_the_morning_analysis_it_always_was() -> None:
    raw: dict[str, Any] = {"id": "msg_1"}
    stamp_brief_written_at(raw, now=datetime(2026, 10, 7, 17, 7))
    brief = _stored(output_markdown="**Verdict:** Red.", raw_response=raw)
    serialized = _serialize_analysis(brief)

    morning_analysis, graded_morning = split_stored_morning(brief, serialized)

    assert graded_morning is None
    assert morning_analysis is serialized
    assert morning_analysis is not None
    # Graded at 07:01, written at 17:07: the page says when the brief was written.
    assert morning_analysis.generatedAtUtc == "2026-10-07T07:01:00Z"
    assert morning_analysis.briefWrittenAtUtc == "2026-10-07T17:07:00Z"
    assert split_stored_morning(None, None) == (None, None)


GRADED_AT = datetime(2026, 10, 7, 7, 1)
SOON = GRADED_AT + timedelta(minutes=2)
MUCH_LATER = GRADED_AT + timedelta(hours=3)


def _status_row(status: str, reason: str | None, updated_at: datetime) -> BriefGenerationStatus:
    return BriefGenerationStatus(
        user_id=uuid.uuid4(), subject_date=DAY, status=status, reason=reason, updated_at=updated_at
    )


def _generation(
    row: BriefGenerationStatus | None, *, written: bool = False, now: datetime = SOON
) -> tuple[str, str | None] | None:
    out = _serialize_brief_generation(
        row, has_analysis=written, graded_at=None if written else GRADED_AT, now=now
    )
    return None if out is None else (out.status, out.reason)


def test_a_graded_morning_waits_on_its_status_row() -> None:
    generating = _status_row(STATUS_GENERATING, None, GRADED_AT)
    failed = _status_row(STATUS_FAILED, "billing", GRADED_AT + timedelta(seconds=40))
    assert _generation(generating) == ("generating", None)
    assert _generation(failed) == ("failed", "billing")
    assert _generation(failed, now=MUCH_LATER) == ("failed", "billing")
    # Batch 144's guard still applies: an orphaned generation does not spin for ever.
    assert _generation(generating, now=MUCH_LATER) == ("failed", STALE_GENERATING_REASON)
    # A written brief outranks every row, as it always has.
    assert _generation(failed, written=True) == ("ready", None)


def test_a_status_row_that_is_not_about_this_morning_is_read_from_its_age() -> None:
    """A process that died between storing the morning and marking it. The row then
    describes an earlier brief, an earlier failure, or nothing at all; the stored
    morning's own age says whether its brief can still be on its way."""
    earlier_brief = _status_row(STATUS_READY, None, GRADED_AT - timedelta(hours=1))
    earlier_failure = _status_row(STATUS_FAILED, "inputs", GRADED_AT - timedelta(minutes=5))
    for row in (None, earlier_brief, earlier_failure):
        assert _generation(row) == ("generating", None)
        assert _generation(row, now=MUCH_LATER) == ("failed", STALE_GENERATING_REASON)


def test_a_day_with_no_stored_morning_reads_as_it_did_before_the_batch() -> None:
    def before(row: BriefGenerationStatus | None) -> tuple[str, str | None] | None:
        out = _serialize_brief_generation(row, has_analysis=False, now=SOON)
        return None if out is None else (out.status, out.reason)

    assert before(None) is None
    assert before(_status_row(STATUS_FAILED, "inputs", GRADED_AT)) == ("failed", "inputs")
    assert before(_status_row(STATUS_GENERATING, None, GRADED_AT)) == ("generating", None)


# -- the push on a morning whose brief did not finish -----------------------------------


def test_the_call_ready_push_says_the_colour_is_there() -> None:
    stored = _stored()
    plan = build_call_ready_plan(stored, DAY)

    assert plan.title == "Today's call is ready"
    assert plan.body == "A head cold: easy riding at most."  # the first reason, as the brief push
    assert plan.data == {"url": "/", "kind": "call_ready", "status": "Red"}
    assert plan.severity == "red"
    assert plan.analysis_type == ANALYSIS_TYPE_CALL_READY
    # Its own once-a-day tag, so a brief written later still announces itself.
    brief = build_brief_ready_plan(stored, DAY)
    assert (plan.tag, brief.tag) == ("call-ready-2026-10-07", "brief-ready-2026-10-07")
    assert brief.analysis_type == ANALYSIS_TYPE_BRIEF_READY != plan.analysis_type


def test_the_call_ready_push_falls_back_to_signed_off_words() -> None:
    plan = build_call_ready_plan(_stored(context_packet={"verdict": {"status": "Green"}}), DAY)
    assert plan.body == CALL_READY_FALLBACK_BODY == "Today's call and your plan are ready on Home."


# -- the two readers of the prose -------------------------------------------------------


def _prefix(analysis: Analysis) -> str:
    return _build_system_prompt_prefix(
        analysis=analysis, origin=CoachOrigin(), local_today=DAY, adjustable_set=None
    )


def test_the_coach_is_told_a_mornings_brief_did_not_finish() -> None:
    prefix = _prefix(_stored())
    assert BRIEF_NOT_WRITTEN_NOTE in prefix
    assert "What you wrote in that read" not in prefix
    assert "He asked this from this morning's call, graded for 2026-10-07." in prefix
    # It still gets what the morning was graded on.
    assert "as it stood when it was graded:" in prefix
    assert '"status": "Red"' in prefix


def test_a_written_brief_is_handed_to_the_coach_as_before() -> None:
    prefix = _prefix(_stored(output_markdown="**Verdict:** Red."))
    assert "What you wrote in that read:\n**Verdict:** Red." in prefix
    assert "He asked this from this morning's brief, written for 2026-10-07." in prefix
    assert "as it stood when you wrote it:" in prefix
    assert BRIEF_NOT_WRITTEN_NOTE not in prefix


@pytest.mark.asyncio
async def test_the_read_tool_says_a_mornings_brief_was_never_written() -> None:
    stored = _stored()
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=stored)

    result = await CoachToolbox(session, _profile()).execute(
        tool_use_id="tu_1",
        name="get_read",
        payload={"readType": "morning", "subjectDate": DAY.isoformat()},
    )

    payload = json.loads(result.content)
    assert payload["meaning"] == BRIEF_NOT_WRITTEN_MEANING
    assert payload["rows"] == [
        {
            "readType": "morning",
            "subjectDate": "2026-10-07",
            "generatedAtUtc": "2026-10-07T07:01:00Z",
            "verdict": "Red",
            "whatYouWrote": None,
        }
    ]


# -- on Postgres: the real pipeline through a failed paid call ---------------------------
#
# These sessions use savepoints inside the fixture's transaction, so a commit survives a
# later rollback as it does in production, and the fixture still discards everything.

SEEDED_DAY = date(2026, 9, 7)
SORE_THROAT = "Woke with a sore throat and a runny nose."


def _savepoint_session(db_conn: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


async def _seed_morning(
    session: AsyncSession, *, symptoms: str | None, notes: str | None = None
) -> tuple[Profile, ManualEntry, PlannedWorkout]:
    """7 Sep's shape (one very poor night, a VO2 session planned), with his check-in."""
    user_id = uuid.uuid4()
    player = Profile(
        id=user_id,
        display_name="Stored Morning",
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )
    session.add(player)
    await session.flush()
    vo2 = await _seed_one_poor_night(session, user_id, SEEDED_DAY)
    await session.flush()
    entry = await session.scalar(select(ManualEntry).where(ManualEntry.user_id == user_id))
    assert entry is not None
    entry.symptoms = symptoms
    entry.notes = notes
    await session.commit()
    return player, entry, vo2


async def _mornings(session: AsyncSession, user_id: uuid.UUID) -> list[Analysis]:
    rows = await session.execute(
        select(Analysis)
        .where(Analysis.user_id == user_id, Analysis.analysis_type == "morning")
        .order_by(Analysis.generated_at_utc, Analysis.created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars().all())


async def _rows_of(session: AsyncSession, model: Any, user_id: uuid.UUID) -> list[Any]:
    rows = await session.execute(
        select(model).where(model.user_id == user_id).execution_options(populate_existing=True)
    )
    return list(rows.scalars().all())


async def _pushes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(Analysis.analysis_type)
        .where(
            Analysis.user_id == user_id,
            Analysis.analysis_type.in_((ANALYSIS_TYPE_CALL_READY, ANALYSIS_TYPE_BRIEF_READY)),
        )
        .order_by(Analysis.generated_at_utc)
    )
    return list(rows.scalars().all())


def _symptoms(stored: Analysis) -> dict[str, Any]:
    symptoms: dict[str, Any] = stored.context_packet["verdict"]["acutePhysiology"]["symptoms"]
    return symptoms


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [CREDIT_400, SPEND_CAP_400])
async def test_on_postgres_a_failed_paid_call_leaves_the_colour_the_floor_and_the_ride_proposal(
    db_conn: AsyncConnection, message: str
) -> None:
    """302.5, on the real code: a credit 400 and a spend-cap 400 each leave a stored
    colour, its floor and the graded ride proposal. On `main` this run stored nothing."""
    async with _savepoint_session(db_conn) as session:
        player, _entry_row, vo2 = await _seed_morning(session, symptoms="head_cold")
        # Scalars first: the failure handler's rollback expires every loaded instance.
        user_id, vo2_id = player.id, vo2.id
        client = _RecordingClient(error=_billing_error(message))

        outcome = await MorningBriefPipeline(session, policy=CHECKIN_POLICY).generate_brief(
            player, SEEDED_DAY, client=client
        )

        assert client.calls == 1
        assert (outcome.failures, outcome.generated) == (1, False)

        # The colour and the floor, with no prose.
        [stored] = await _mornings(session, user_id)
        assert stored.verdict == "Red"
        assert brief_is_written(stored) is False
        assert (stored.output_markdown, stored.model_name, stored.raw_response) == ("", None, {})
        verdict = stored.context_packet["verdict"]
        assert _symptoms(stored)["answer"] == "head_cold"
        assert any(item["kind"] == "symptoms" for item in verdict["acutePhysiology"]["escalations"])
        # The plan lines and Today's actions are in the stored packet too.
        assert verdict["planAdjustments"]
        assert isinstance(verdict["todayActions"], list)

        # The ride proposal the morning makes, offered without waiting for the brief.
        [proposal] = await _rows_of(session, WorkoutDeliveryProposal, user_id)
        assert proposal.planned_workout_id == vo2_id
        assert proposal.status == "proposed"
        assert proposal.structured_workout_ir["adjustment"]["changed"] is True
        assert outcome.proposals_regenerated == 1

        # The failure is recorded under the colour, and he is told the colour is there.
        [status] = await _rows_of(session, BriefGenerationStatus, user_id)
        assert (status.status, status.reason) == (STATUS_FAILED, "billing")
        assert await _pushes(session, user_id) == [ANALYSIS_TYPE_CALL_READY]

        # What Home is sent: the morning as graded, and no brief.
        serialized = _serialize_analysis(stored)
        morning_analysis, graded_morning = split_stored_morning(stored, serialized)
        assert morning_analysis is None
        assert graded_morning is not None and graded_morning.verdict == "red"
        assert graded_morning.planAdjustments == verdict["planAdjustments"]
        assert graded_morning.todayActions == verdict["todayActions"]
        generation = _serialize_brief_generation(
            status, has_analysis=False, graded_at=stored.generated_at_utc
        )
        assert generation is not None
        assert (generation.status, generation.reason) == ("failed", "billing")

        # The readers that had nothing to read: the rail's VO2 gate, the delivery rail,
        # recent mornings, the counted colour, and a disagreement with the verdict.
        context = await ExecutableCoachingService(session)._morning_context_for(user_id, SEEDED_DAY)
        assert (context.status, context.graded) == ("Red", True)
        await session.refresh(vo2)
        assert blocks_red_vo2(context.status, build_structured_workout_ir(vo2, ftp_watts=280))
        calls = (
            await session.execute(select_morning_calls().where(Analysis.user_id == user_id))
        ).all()
        assert [(row.subject_date, row.verdict) for row in calls] == [(SEEDED_DAY, "Red")]
        assert delivered_verdicts([stored], timezone_name="Europe/London") == {SEEDED_DAY: "Red"}
        dispute = await DisputeService(session).dissent_from_verdict(
            player, subject_date=SEEDED_DAY, reason="I feel fine."
        )
        assert dispute.analysis_id == stored.id
        assert dispute.snapshot["status"] == "Red"


@pytest.mark.asyncio
async def test_on_postgres_try_again_writes_the_brief_into_the_same_morning_and_pays_once(
    db_conn: AsyncConnection,
) -> None:
    """302.5: Retry fills the prose without a second notes reading, and nothing is
    charged twice. It also keeps the floor his note set: the retry saves no check-in."""
    async with _savepoint_session(db_conn) as session:
        player, entry, vo2 = await _seed_morning(session, symptoms="none", notes=SORE_THROAT)
        user_id, vo2_id = player.id, vo2.id
        saved_at = entry.entry_at_utc
        notes_client = FakeNotesClient(_reading(head_cold=_flag("present", words="sore throat")))
        failing = _RecordingClient(error=_billing_error(CREDIT_400))

        first = await MorningBriefPipeline(session, policy=CHECKIN_POLICY).generate_brief(
            player, SEEDED_DAY, client=failing, notes_client=notes_client
        )

        assert first.failures == 1
        [stored] = await _mornings(session, user_id)
        stored_id = stored.id
        assert stored.verdict == "Red"
        assert (_symptoms(stored)["answer"], _symptoms(stored)["source"]) == ("head_cold", "notes")
        assert brief_is_written(stored) is False
        # The reading outlives the failed call it used to be rolled back with.
        [reading] = await _rows_of(session, CheckInReading, user_id)
        assert reading.status == NOTES_READ
        assert (notes_client.calls, failing.calls) == (1, 1)

        working = FakeMorningClient()
        retry = await MorningBriefPipeline(session, policy=RETRY_POLICY).generate_brief(
            player, SEEDED_DAY, client=working, notes_client=notes_client
        )

        assert (retry.failures, retry.generated) == (0, True)
        [written] = await _mornings(session, user_id)  # the same row, filled in
        assert written.id == stored_id
        assert brief_is_written(written) is True
        assert written.model_name == "claude-test"
        assert brief_written_at(written.raw_response) is not None
        # Written from the packet the morning was graded on: the colour did not move,
        # and the floor his note set still stands.
        assert written.raw_response["contextVerdict"] == "Red"
        assert written.verdict == "Red"
        assert (_symptoms(written)["answer"], _symptoms(written)["source"]) == (
            "head_cold",
            "notes",
        )
        # One reading, one brief, one proposal.
        assert notes_client.calls == 1
        assert working.calls == 1
        assert len(await _rows_of(session, CheckInReading, user_id)) == 1
        [proposal] = await _rows_of(session, WorkoutDeliveryProposal, user_id)
        assert proposal.planned_workout_id == vo2_id
        # The check-in was never saved again.
        [check_in] = await _rows_of(session, ManualEntry, user_id)
        assert check_in.entry_at_utc == saved_at
        # Ready, announced once each, and the claim completed on the stored row.
        [status] = await _rows_of(session, BriefGenerationStatus, user_id)
        assert status.status == STATUS_READY
        assert await _pushes(session, user_id) == [
            ANALYSIS_TYPE_CALL_READY,
            ANALYSIS_TYPE_BRIEF_READY,
        ]
        [request] = await _rows_of(session, GenerationRequest, user_id)
        assert (request.status, request.analysis_id) == (STATUS_COMPLETED, stored_id)

        # A second identical run pays for nothing at all.
        again = await MorningBriefPipeline(session, policy=RETRY_POLICY).generate_brief(
            player, SEEDED_DAY, client=working, notes_client=notes_client
        )
        assert (again.existing, again.generated, again.failures) == (True, False, 0)
        assert (working.calls, notes_client.calls) == (1, 1)
        assert len(await _mornings(session, user_id)) == 1


@pytest.mark.asyncio
async def test_on_postgres_a_new_symptom_answer_regrades_and_an_earlier_brief_does_not_hide_it(
    db_conn: AsyncConnection,
) -> None:
    """Two defects on `main`, one morning. The answer was not part of the generation
    identity, so re-saving with "Chest or heart" regraded nothing. And had it regraded
    and the call failed, Home would have gone on serving the earlier brief as ready."""
    async with _savepoint_session(db_conn) as session:
        player, _entry_row, _vo2 = await _seed_morning(session, symptoms="none")
        user_id = player.id
        working = FakeMorningClient()

        first = await MorningBriefPipeline(session, policy=CHECKIN_POLICY).generate_brief(
            player, SEEDED_DAY, client=working
        )
        assert first.generated is True
        [brief] = await _mornings(session, user_id)
        brief_id = brief.id
        assert (brief.verdict, brief_is_written(brief)) == ("Amber", True)

        # He re-opens the check-in and answers "Chest or heart". Anthropic is down.
        [check_in] = await _rows_of(session, ManualEntry, user_id)
        check_in.symptoms = "chest_heart"
        check_in.entry_at_utc = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        failing = _RecordingClient(error=_billing_error(SPEND_CAP_400))

        second = await MorningBriefPipeline(session, policy=CHECKIN_POLICY).generate_brief(
            player, SEEDED_DAY, client=failing
        )

        assert second.failures == 1
        earlier, latest = await _mornings(session, user_id)
        assert (earlier.id, earlier.verdict, brief_is_written(earlier)) == (brief_id, "Amber", True)
        assert latest.verdict == "Red"
        assert brief_is_written(latest) is False
        acute = latest.context_packet["verdict"]["acutePhysiology"]
        assert _symptoms(latest)["answer"] == "chest_heart"
        assert acute["requiresTrainingRest"] is True
        newest = await MorningAnalysisService(session).latest_analysis(user_id, SEEDED_DAY)
        assert newest is not None and newest.id == latest.id

        # Home is sent the newer morning, not the earlier brief.
        morning_analysis, graded_morning = split_stored_morning(newest, _serialize_analysis(newest))
        assert morning_analysis is None
        assert graded_morning is not None
        assert graded_morning.verdict == "red"
        assert graded_morning.acutePhysiology["requiresTrainingRest"] is True
        [status] = await _rows_of(session, BriefGenerationStatus, user_id)
        generation = _serialize_brief_generation(
            status, has_analysis=False, graded_at=newest.generated_at_utc
        )
        assert generation is not None
        assert (generation.status, generation.reason) == ("failed", "billing")
        # Every reader of the colour sees the day as he was last shown it.
        assert (
            await ExecutableCoachingService(session)._morning_verdict_for(user_id, SEEDED_DAY)
            == "Red"
        )


@pytest.mark.asyncio
async def test_on_postgres_a_note_unread_in_an_outage_is_read_when_he_tries_again(
    db_conn: AsyncConnection,
) -> None:
    """In a full outage the notes reader fails with the brief. The morning says so, and
    the retry reads the note: the cold he wrote about sets its floor then."""
    async with _savepoint_session(db_conn) as session:
        player, _entry_row, _vo2 = await _seed_morning(session, symptoms="none", notes=SORE_THROAT)
        user_id = player.id
        failing = _RecordingClient(error=_billing_error(CREDIT_400))

        await MorningBriefPipeline(session, policy=CHECKIN_POLICY).generate_brief(
            player, SEEDED_DAY, client=failing, notes_client=FakeNotesClient(error=True)
        )

        [stored] = await _mornings(session, user_id)
        stored_id = stored.id
        assert stored.verdict == "Amber"  # 7 Sep's shape without the note
        assert stored.context_packet["verdict"]["notesReading"]["status"] == NOTES_FAILED
        serialized = _serialize_analysis(stored)
        assert serialized is not None
        assert serialized.notesReadingStatus == NOTES_FAILED  # the line Home shows
        [reading] = await _rows_of(session, CheckInReading, user_id)
        assert reading.status == NOTES_FAILED

        reader = FakeNotesClient(_reading(head_cold=_flag("present", words="sore throat")))
        working = FakeMorningClient()
        retry = await MorningBriefPipeline(session, policy=RETRY_POLICY).generate_brief(
            player, SEEDED_DAY, client=working, notes_client=reader
        )

        assert (retry.failures, retry.generated) == (0, True)
        earlier, latest = await _mornings(session, user_id)
        assert (earlier.id, brief_is_written(earlier)) == (stored_id, False)
        assert latest.verdict == "Red"
        assert brief_is_written(latest) is True
        assert (_symptoms(latest)["answer"], _symptoms(latest)["source"]) == ("head_cold", "notes")
        assert latest.context_packet["verdict"]["notesReading"]["status"] == NOTES_READ
        [reading] = await _rows_of(session, CheckInReading, user_id)  # retried in place
        assert reading.status == NOTES_READ
        assert (reader.calls, working.calls) == (1, 1)


def _db_override(session: AsyncSession) -> Any:
    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    return override


async def _get_daily_loop(player: Profile, session: AsyncSession, day: date) -> dict[str, Any]:
    app.dependency_overrides[get_current_user] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/daily-loop?subject_date={day.isoformat()}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


@pytest.mark.asyncio
async def test_on_postgres_the_daily_loop_serves_a_morning_without_its_brief(
    db_conn: AsyncConnection,
) -> None:
    """The envelope the app reads, end to end: the latest stored morning has no brief,
    an earlier one has, and the status row says the brief failed."""
    day = date(2026, 6, 20)
    async with _savepoint_session(db_conn) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Envelope",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                _stored(
                    user_id=player.id,
                    subject_date=day,
                    generated_at_utc=datetime(2026, 6, 20, 6, 35),
                    verdict="Green",
                    output_markdown="**Green light**",
                    context_packet={"verdict": {"reasons": ["Sleep and HRV are in range."]}},
                ),
                _stored(
                    user_id=player.id,
                    subject_date=day,
                    generated_at_utc=datetime(2026, 6, 20, 7, 10),
                    verdict="Red",
                    context_packet={
                        "verdict": {
                            "reasons": ["Reported chest pain sets a Red floor."],
                            "planAdjustments": ["No training of any kind today."],
                            "acutePhysiology": {"requiresTrainingRest": True},
                            "notesReading": {"status": "failed"},
                        }
                    },
                ),
                BriefGenerationStatus(
                    user_id=player.id, subject_date=day, status=STATUS_FAILED, reason="billing"
                ),
            ]
        )
        await session.commit()

        data = await _get_daily_loop(player, session, day)

    assert data["morningAnalysis"] is None
    graded = data["gradedMorning"]
    assert graded["verdict"] == "red"
    assert graded["outputMarkdown"] == ""
    assert graded["reasons"] == ["Reported chest pain sets a Red floor."]
    assert graded["planAdjustments"] == ["No training of any kind today."]
    assert graded["acutePhysiology"]["requiresTrainingRest"] is True
    assert graded["notesReadingStatus"] == "failed"
    assert graded["briefWrittenAtUtc"] is None
    assert data["briefGeneration"] == {"status": "failed", "reason": "billing"}


@pytest.mark.asyncio
async def test_on_postgres_the_retry_route_starts_the_run_and_saves_nothing(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = date(2026, 7, 12)
    saved_at = datetime(2026, 7, 12, 7, 0)
    queued = AsyncMock()
    monkeypatch.setattr(daily_loop_router, "_retry_brief", queued)
    monkeypatch.setattr(daily_loop_router, "local_today", lambda _timezone: day)

    async with _savepoint_session(db_conn) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Retry Route",
            role=UserRole.player,
            timezone="UTC",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(_entry(user_id=player.id, entry_date=day, entry_at_utc=saved_at))
        await session.commit()
        user_id = player.id

        app.dependency_overrides[get_current_user] = lambda: player
        app.dependency_overrides[get_db] = _db_override(session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                today = await client.post(f"/api/v1/daily-loop/{day.isoformat()}/brief/retry")
                yesterday = await client.post(
                    f"/api/v1/daily-loop/{(day - timedelta(days=1)).isoformat()}/brief/retry"
                )
        finally:
            app.dependency_overrides.clear()

        assert today.status_code == 200, today.text
        assert yesterday.status_code == 200, yesterday.text
        # Today's retry is queued and the envelope already says a brief is on its way.
        queued.assert_awaited_once_with(user_id, day)
        assert today.json()["data"]["briefGeneration"] == {"status": "generating", "reason": None}
        # A day that is over is not retried.
        assert yesterday.json()["data"]["briefGeneration"] is None
        # Nothing of his was written: the check-in keeps the time he saved it.
        [check_in] = await _rows_of(session, ManualEntry, user_id)
        assert check_in.entry_at_utc == saved_at
        assert (
            await session.scalar(
                select(func.count()).select_from(ManualEntry).where(ManualEntry.user_id == user_id)
            )
            == 1
        )
