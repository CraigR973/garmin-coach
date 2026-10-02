"""Batch 297 — Claude reads the check-in notes, and can only add caution.

297.8's tests. A stored reading is reused on regeneration; a failed reading leaves the
colour unchanged and says so; an exhaustive check proves no flag ever relaxes the
colour; each eval case's recorded response maps to the expected flags within the gate
Craig confirmed. The two-Reds cause check reads the reader, not regular expressions.
"""

from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.config import settings
from src.models.coaching import CheckInReading, ManualEntry
from src.models.profile import Profile, UserRole
from src.services.chronic_patterns import (
    _check_in_training_context,
    _red_day_evidence,
    reading_causes,
)
from src.services.morning_analysis import (
    GRADED_SYSTEM_PROMPT,
    LADDER_SYSTEM_PROMPT,
    NOTES_READING_RULE,
    MorningAnalysisService,
)
from src.services.notes_eval import (
    gate_failures,
    load_cases,
    recorded_passes,
    score_pass,
)
from src.services.notes_reader import (
    CAUSES,
    FLAGS,
    STATUS_FAILED,
    STATUS_NO_NOTES,
    STATUS_NOT_READ,
    STATUS_READ,
    NotesReaderService,
    NotesReading,
    day_effects,
    notes_hash,
    parse_reading,
    reading_effects,
)
from src.services.symptom_check import (
    SYMPTOM_ANSWERS,
    SYMPTOM_SEVERITY,
    more_severe_symptom,
)
from src.services.verdict_grading import grade
from tests.test_batch_295_verdict_grading import LEVELS, RANK, _inputs
from tests.test_batch_296_graded_colour import _seed_one_poor_night
from tests.test_morning_analysis import FakeMorningClient

FIXTURES = Path(__file__).parent / "fixtures"
EVAL_CASES = FIXTURES / "notes_eval_2026_09.json"
RECORDED = FIXTURES / "notes_eval_recorded"

ABSENT_FLAG = {"state": "absent", "who": "unknown", "when": "unknown", "words": ""}
ABSENT_CAUSE = {"state": "absent", "when": "unknown", "words": ""}


def _reading(**overrides: dict[str, Any]) -> dict[str, Any]:
    reading: dict[str, Any] = {name: dict(ABSENT_FLAG) for name in FLAGS}
    reading.update({name: dict(ABSENT_CAUSE) for name in CAUSES})
    for name, value in overrides.items():
        reading[name] = {**reading[name], **value}
    return reading


def _flag(state: str, who: str = "him", when: str = "now", words: str = "") -> dict[str, Any]:
    return {"state": state, "who": who, "when": when, "words": words}


# -- the one-way mapping ------------------------------------------------------------------


def test_a_symptom_he_writes_sets_the_floor_and_home_asks() -> None:
    effects = reading_effects(
        _reading(head_cold=_flag("present", words="sore throat and a runny nose"))
    )
    assert effects.symptom_answer == "head_cold"
    assert effects.symptom_words == "sore throat and a runny nose"
    assert effects.ask_symptom_question is True
    assert effects.feel_notch == 0


def test_the_most_severe_written_symptom_wins() -> None:
    effects = reading_effects(
        _reading(head_cold=_flag("present"), chest_heart=_flag("present", words="tight chest"))
    )
    assert effects.symptom_answer == "chest_heart"


@pytest.mark.parametrize(
    ("who", "when"),
    [("someone_else", "now"), ("him", "earlier"), ("someone_else", "earlier")],
)
def test_someone_elses_or_a_past_symptom_does_nothing(who: str, when: str) -> None:
    effects = reading_effects(_reading(fever_aches=_flag("present", who=who, when=when)))
    assert effects.symptom_answer is None
    assert effects.ask_symptom_question is False


def test_an_unclear_symptom_asks_and_sets_no_floor() -> None:
    effects = reading_effects(_reading(chest_heart=_flag("unclear", words="heartburn")))
    assert effects.symptom_answer is None
    assert effects.ask_symptom_question is True
    assert effects.ask_words == "heartburn"


def test_feeling_unwell_asks_and_adds_a_notch_and_fatigue_only_the_notch() -> None:
    unwell = reading_effects(_reading(unwell=_flag("present", words="feel the effects")))
    assert (unwell.ask_symptom_question, unwell.feel_notch) == (True, 1)
    assert unwell.feel_words == "feel the effects"
    tired = reading_effects(_reading(fatigue=_flag("present", words="legs like lead")))
    assert (tired.ask_symptom_question, tired.feel_notch) == (False, 1)


def test_his_answer_after_the_reading_governs() -> None:
    effects = reading_effects(
        _reading(head_cold=_flag("present"), fatigue=_flag("present")),
        answered_after_reading=True,
    )
    assert effects.symptom_answer is None
    assert effects.ask_symptom_question is False
    # How he feels is his own words, not an answer he has since changed.
    assert effects.feel_notch == 1


def test_causes_are_context_only() -> None:
    effects = reading_effects(
        _reading(
            alcohol={"state": "present", "when": "last_night", "words": "13 units"},
            travel={"state": "present", "when": "now", "words": "on holiday"},
        )
    )
    assert [cause.cause for cause in effects.causes] == ["alcohol", "travel"]
    assert effects.symptom_answer is None
    assert effects.ask_symptom_question is False
    assert effects.feel_notch == 0


# -- an exhaustive check that no flag relaxes the colour ----------------------------------


def test_a_written_symptom_never_lowers_his_answer() -> None:
    for tapped, written in itertools.product((None, *SYMPTOM_ANSWERS), (None, *SYMPTOM_ANSWERS)):
        chosen = more_severe_symptom(tapped, written)
        if tapped is not None:
            assert chosen is not None
            assert SYMPTOM_SEVERITY[chosen] >= SYMPTOM_SEVERITY[tapped]


def test_every_single_flag_state_only_adds() -> None:
    """Every flag, every state, who and when: never a floor from nothing it can't show."""

    for name in FLAGS:
        for state, who, when in itertools.product(
            ("present", "absent", "unclear"),
            ("him", "someone_else", "unknown"),
            ("now", "last_night", "earlier", "unknown"),
        ):
            effects = reading_effects(_reading(**{name: _flag(state, who, when)}))
            if effects.symptom_answer is not None:
                assert (state, who) == ("present", "him") and when in {"now", "last_night"}
            if effects.feel_notch:
                assert name in {"unwell", "fatigue"} and state == "present"
            assert effects.feel_notch in (0, 1)


def test_a_notch_never_gives_a_better_colour_over_the_whole_grid() -> None:
    keys = list(LEVELS)
    violations: list[str] = []
    for combo in itertools.product(*(range(len(LEVELS[key])) for key in keys)):
        inputs = _inputs(**{key: LEVELS[key][i] for key, i in zip(keys, combo, strict=True)})
        without = grade(inputs)
        noted = grade(replace(inputs, notes_feel_notch=1, notes_feel_words="legs like lead"))
        if RANK[noted.label] < RANK[without.label] or (without.floor and not noted.floor):
            violations.append(f"{combo}: {without.label} -> {noted.label}")
    assert violations == []


def test_the_notch_is_one_step_and_quoted() -> None:
    inputs = _inputs(feel=8)
    noted = grade(replace(inputs, notes_feel_notch=1, notes_feel_words="legs like lead"))
    subjective = noted.domain("subjective")
    assert subjective.rating == "mild"
    assert noted.summary.endswith('you wrote "legs like lead".')
    assert noted.to_packet()["references"]["notesFeelNotch"] == 1


# -- the day: which check-in, which reading ----------------------------------------------


def _entry(notes: str | None, at: datetime) -> ManualEntry:
    return ManualEntry(
        id=uuid.uuid4(), user_id=uuid.uuid4(), entry_date=at.date(), entry_at_utc=at, notes=notes
    )


def _stored(entry: ManualEntry, status: str, reading: dict[str, Any], at: datetime) -> Mock:
    return Mock(
        manual_entry_id=entry.id,
        notes_sha256=notes_hash(entry.notes),
        status=status,
        reading=reading,
        created_at=at,
        updated_at=at,
        model_name="claude-test",
        prompt_version="notes-reader-test",
    )


def test_the_day_reads_its_newest_noted_check_in() -> None:
    morning = datetime(2026, 10, 7, 7, 0)
    entry = _entry("Sore throat since yesterday.", morning)
    assert day_effects([], []).status == STATUS_NO_NOTES
    assert day_effects([entry], []).status == STATUS_NOT_READ
    failed = day_effects([entry], [_stored(entry, STATUS_FAILED, {}, morning)])
    assert failed.status == STATUS_FAILED
    assert failed.symptom_answer is None
    read = day_effects(
        [entry],
        [_stored(entry, STATUS_READ, _reading(head_cold=_flag("present")), morning + timedelta(1))],
    )
    assert (read.status, read.symptom_answer) == (STATUS_READ, "head_cold")
    # A reading of an older version of the note is not this note's reading.
    entry.notes = "Actually fine today."
    stale = day_effects(
        [entry],
        [
            Mock(
                manual_entry_id=entry.id,
                notes_sha256=notes_hash("Sore throat since yesterday."),
                status=STATUS_READ,
                reading=_reading(head_cold=_flag("present")),
                created_at=morning,
                updated_at=morning,
            )
        ],
    )
    assert stale.status == STATUS_NOT_READ


def test_his_answer_to_homes_question_after_the_reading_is_his_answer() -> None:
    # Batch 303: until then a check-in saved after the reading was "his answer". The
    # answer now has a time of its own (tests/test_batch_303_medical_follow_through.py).
    read_at = datetime(2026, 10, 7, 7, 0)
    entry = _entry("Sore throat.", read_at - timedelta(minutes=1))
    entry.symptoms_answered_at_utc = read_at + timedelta(minutes=30)
    effects = day_effects(
        [entry], [_stored(entry, STATUS_READ, _reading(head_cold=_flag("present")), read_at)]
    )
    assert effects.answered_after_reading is True
    assert effects.symptom_answer is None


def test_the_packet_says_what_the_reading_means() -> None:
    packet = reading_effects(_reading(head_cold=_flag("unclear", words="scratchy"))).to_packet()
    assert packet["askSymptomQuestion"] is True
    assert packet["askWords"] == "scratchy"
    assert "only add caution" in packet["meaning"]


def test_the_schema_is_strict() -> None:
    good = json.dumps(_reading())
    assert parse_reading(good)["head_cold"]["state"] == "absent"
    with pytest.raises(Exception, match="schema"):
        parse_reading(json.dumps({**_reading(), "extra": 1}))
    with pytest.raises(Exception, match="schema"):
        parse_reading(json.dumps(_reading(head_cold={"state": "maybe"})))


def test_the_graded_prompt_carries_the_rule_and_the_ladder_prompt_does_not() -> None:
    assert NOTES_READING_RULE in GRADED_SYSTEM_PROMPT
    assert NOTES_READING_RULE not in LADDER_SYSTEM_PROMPT


# -- the two-Reds cause check reads the reader -------------------------------------------


def test_batch_212s_bedroom_notes_are_not_illness_and_a_real_cold_is() -> None:
    # 14 and 15 Aug: "felt cold from drafts", "too cold". The reader keys them absent.
    assert reading_causes(_reading()) == ()
    assert reading_causes(_reading(head_cold=_flag("present", words="streaming cold"))) == (
        ("illness", "streaming cold"),
    )


def test_causes_keep_batch_194s_shape() -> None:
    assert reading_causes(_reading(chest_heart=_flag("present"))) == ()
    assert reading_causes(_reading(head_cold=_flag("present", who="someone_else"))) == ()
    last_night = {"state": "present", "when": "last_night", "words": "13 units"}
    assert reading_causes(_reading(alcohol=last_night)) == (("alcohol", "13 units"),)
    earlier = {"state": "present", "when": "earlier", "words": "beers on Friday"}
    assert reading_causes(_reading(alcohol=earlier)) == ()
    week = {"state": "present", "when": "now", "words": "recovery week"}
    assert reading_causes(_reading(deliberate_rest=week)) == (("deliberate_rest", "recovery week"),)


def test_the_red_day_evidence_and_context_come_from_readings() -> None:
    day = date(2026, 10, 9)
    entry = _entry("Streaming cold.", datetime.combine(day, datetime.min.time()))
    stored = _stored(entry, STATUS_READ, _reading(head_cold=_flag("present", words="cold")), day)
    recovery = [
        Mock(
            calendar_date=day,
            recovery_time_min=0,
            acute_load=0.0,
            hrv_7_day_avg_ms=47,
            hrv_last_night_avg_ms=47,
            hrv_status="balanced",
            hrv_baseline_low_ms=43,
            hrv_baseline_high_ms=55,
            resting_heart_rate_bpm=45,
            readiness_score=70,
        )
    ]
    evidence = _red_day_evidence(recovery, manual_rows=[entry], baselines={}, readings=[stored])
    assert evidence[day].check_in_reasons == ("illness",)
    # With no reading, no cause is found and the Red counts.
    assert (
        _red_day_evidence(recovery, manual_rows=[entry], baselines={})[day].check_in_reasons == ()
    )
    [context] = _check_in_training_context([entry], [stored])
    assert (context.reason, context.matched_text) == ("illness", "cold")


# -- the eval: the recorded responses meet the gate ---------------------------------------


def _production_recording() -> dict[str, Any]:
    model = settings.notes_reader_model or settings.anthropic_model
    path = RECORDED / f"{model}.json"
    assert path.exists(), f"no recorded eval for the production model {model}"
    return dict(json.loads(path.read_text(encoding="utf-8")))


def test_the_production_models_recorded_responses_meet_the_gate() -> None:
    cases = load_cases(EVAL_CASES)
    recording = _production_recording()
    scores = [score_pass(cases, readings) for readings in recorded_passes(recording)]
    assert len(scores) >= 2
    assert gate_failures(scores) == []
    for score in scores:
        assert len(score.red_flags) == 12
        assert score.failed_readings == []


def test_every_recorded_response_still_fits_the_schema() -> None:
    for path in sorted(RECORDED.glob("*.json")):
        recording = json.loads(path.read_text(encoding="utf-8"))
        for case_id, attempts in recording["cases"].items():
            for attempt in attempts:
                NotesReading.model_validate(attempt, strict=True)
                assert case_id


def test_the_eval_cases_are_the_ones_craig_labelled() -> None:
    cases = load_cases(EVAL_CASES)
    assert len(cases) == 100
    assert sum(case.source == "real" for case in cases) == 56
    by_id = {case.id: case for case in cases}
    # Craig, 30 Sep: Home asks after hay fever too.
    assert by_id["H42"].labels["head_cold"]["state"] == "unclear"
    # Batch 212's bedroom notes are keyed as nothing.
    assert by_id["R22"].labels == {} and by_id["R23"].labels == {}


# -- on Postgres: one reading per version, reused, retried, and harmless when it fails ----


class FakeNotesClient:
    model_name = "claude-test"

    def __init__(self, reading: dict[str, Any] | None = None, error: bool = False) -> None:
        self.reading = reading or _reading()
        self.error = error
        self.calls = 0

    async def read(self, notes: str) -> dict[str, Any]:
        self.calls += 1
        if self.error:
            raise RuntimeError("billing outage")
        return self.reading


async def _seed(session: Any, notes: str) -> tuple[Profile, ManualEntry]:
    user_id = uuid.uuid4()
    player = Profile(
        id=user_id,
        display_name="Notes Reader",
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )
    session.add(player)
    await session.flush()
    await _seed_one_poor_night(session, user_id, date(2026, 9, 7))
    await session.flush()
    entry = await session.scalar(select(ManualEntry).where(ManualEntry.user_id == user_id))
    assert entry is not None
    entry.notes = notes
    entry.subjective_score = 8
    await session.commit()
    return player, entry


@pytest.mark.asyncio
async def test_a_reading_is_taken_once_and_reused_on_regeneration(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player, entry = await _seed(session, "Woke with a sore throat and a runny nose.")
        client = FakeNotesClient(_reading(head_cold=_flag("present", words="sore throat")))
        service = NotesReaderService(session)
        first = await service.ensure_reading(player.id, [entry], client=client)
        second = await service.ensure_reading(player.id, [entry], client=client)
        assert first is not None and second is not None
        assert first.id == second.id
        assert client.calls == 1
        rows = (
            (
                await session.execute(
                    select(CheckInReading).where(CheckInReading.user_id == player.id)
                )
            )
            .scalars()
            .all()
        )
        assert [row.status for row in rows] == ["read"]


@pytest.mark.asyncio
async def test_a_failed_reading_is_stored_retried_and_leaves_the_colour_alone(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    day = date(2026, 9, 7)
    async with session_factory() as session:
        player, entry = await _seed(session, "Woke with a sore throat and a runny nose.")
        failing = FakeNotesClient(error=True)
        result = await MorningAnalysisService(session).generate_and_store(
            player, day, client=FakeMorningClient(), notes_client=failing
        )
        verdict = result.analysis.context_packet["verdict"]
        assert failing.calls == 1
        assert verdict["notesReading"]["status"] == STATUS_FAILED
        # 7 Sep's shape without the note: one very poor night, graded Amber (Batch 296).
        assert verdict["status"] == "Amber"
        assert verdict["acutePhysiology"]["symptoms"]["answer"] is None
        stored = await session.scalar(
            select(CheckInReading).where(CheckInReading.user_id == player.id)
        )
        assert stored is not None and stored.status == STATUS_FAILED
        assert stored.error and "billing outage" in stored.error

        # The next regeneration retries in place, and the note now sets the floor.
        working = FakeNotesClient(_reading(head_cold=_flag("present", words="sore throat")))
        await NotesReaderService(session).ensure_reading(player.id, [entry], client=working)
        await session.commit()
        packet = await MorningAnalysisService(session).assemble_context_packet(player, day)
        rows = (
            (
                await session.execute(
                    select(CheckInReading).where(CheckInReading.user_id == player.id)
                )
            )
            .scalars()
            .all()
        )
        assert [row.status for row in rows] == [STATUS_READ]
        symptoms = packet["verdict"]["acutePhysiology"]["symptoms"]
        assert (symptoms["answer"], symptoms["source"]) == ("head_cold", "notes")
        assert symptoms["words"] == "sore throat"
        assert packet["verdict"]["status"] == "Red"
        assert packet["verdict"]["notesReading"]["askSymptomQuestion"] is True

        # He saves the check-in again after the reading, None still selected. Since
        # Batch 303 that is not an answer: the note's floor stands and Home still asks.
        later = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        entry.symptoms = "none"
        entry.entry_at_utc = later
        await session.commit()
        resaved = await MorningAnalysisService(session).assemble_context_packet(player, day)
        assert resaved["verdict"]["acutePhysiology"]["symptoms"]["answer"] == "head_cold"
        assert resaved["verdict"]["notesReading"]["answeredAfterReading"] is False
        assert resaved["verdict"]["notesReading"]["askSymptomQuestion"] is True

        # He answers Home's question: his own answer now governs, and relaxes the floor.
        entry.symptoms_answered_at_utc = later + timedelta(minutes=1)
        await session.commit()
        relaxed = await MorningAnalysisService(session).assemble_context_packet(player, day)
        assert relaxed["verdict"]["acutePhysiology"]["symptoms"]["answer"] == "none"
        assert relaxed["verdict"]["notesReading"]["answeredAfterReading"] is True
        assert relaxed["verdict"]["notesReading"]["askSymptomQuestion"] is False


def test_an_answer_between_a_failed_read_and_its_retry_is_not_an_answer() -> None:
    failed_at = datetime(2026, 10, 7, 7, 0)
    entry = _entry("Sore throat.", failed_at - timedelta(minutes=1))
    # Batch 303: his answer to Home's question, given before the note was ever read.
    entry.symptoms_answered_at_utc = failed_at + timedelta(minutes=10)
    retried = _stored(entry, STATUS_READ, _reading(head_cold=_flag("present")), failed_at)
    retried.updated_at = failed_at + timedelta(minutes=20)
    effects = day_effects([entry], [retried])
    assert effects.answered_after_reading is False
    assert effects.symptom_answer == "head_cold"


def test_the_replay_reproduces_a_morning_a_note_made_worse() -> None:
    from src.models.coaching import PlanBlock, Sleep
    from src.services.morning_verdict import graded_verdict_packet
    from src.services.verdict_replay import replay_morning
    from tests.test_batch_295_verdict_grading import _load_fixture, _metrics, _replayed
    from tests.test_batch_296_graded_colour import (
        _graded_read,
        _packet,
        _planned,
    )

    fixture = _load_fixture()
    replayed = _replayed(fixture)
    day = date(2026, 9, 20)  # Green, nothing off: a note is the only thing that can move it
    morning = replayed[day]
    noted = replace(
        morning.graded,
        references={
            **morning.graded.references,
            "notesFeelNotch": 1,
            "notesFeelWords": "legs like lead",
        },
    )
    [day_packet] = [m for m in fixture["mornings"] if m["subjectDate"] == day.isoformat()]
    wake = _metrics(fixture["wakeMetrics"])
    preferred = _metrics(fixture["preferredMetrics"])
    sleeps = {
        date.fromisoformat(row[0]): Sleep(
            calendar_date=date.fromisoformat(row[0]),
            duration_sec=row[1],
            resting_heart_rate_bpm=row[2],
            average_spo2_pct=row[3],
            lowest_spo2_pct=row[4],
            average_respiration=row[5],
        )
        for row in fixture["sleeps"]
    }
    feels = {date.fromisoformat(d): score for d, score in fixture["feels"]}
    blocks = [
        PlanBlock(
            name=name,
            block_type=block_type,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end),
        )
        for name, block_type, start, end in fixture["blocks"]
    ]
    first = replay_morning(
        _graded_read(morning, _packet(replayed, fixture, day), day_packet),
        metrics=wake,
        baseline_metrics=preferred,
        sleeps=sleeps,
        feels=feels,
        blocks=blocks,
    )
    # Production built this morning with the note's notch, and stored it in references.
    with_note = replay_morning(
        _graded_read(
            morning,
            {
                **graded_verdict_packet(
                    morning.ladder_packet, noted, _planned(fixture, day), breathwork_line=None
                ),
            },
            day_packet,
        ),
        metrics=wake,
        baseline_metrics=preferred,
        sleeps=sleeps,
        feels=feels,
        blocks=blocks,
    )
    assert first.graded.domain("subjective").rating == "none"
    assert with_note.graded.domain("subjective").rating == "mild"
    assert RANK[with_note.graded_label] >= RANK[first.graded_label]
