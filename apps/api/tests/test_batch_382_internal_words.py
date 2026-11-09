"""Batch 382 — the app's own words stay out of the brief, the post-session reads and the
experiment notice.

The cases are real-shaped (a packet with the keys a morning and a ride carry) with invented
wording. Each failed on ``main`` first: nothing looked for these words after generation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity, Experiment
from src.models.profile import Profile, UserRole
from src.services import morning_analysis, post_activity_read_runner
from src.services.brief_check import MISS_INTERNAL_WORDS, MISSES, check_brief
from src.services.coach_policy import INTERNAL_SOURCE_BASIS
from src.services.internal_words import internal_words, known_names
from src.services.plain_words_repair import (
    INTERNAL_WORDS_REPAIR_SYSTEM_PROMPT,
    OUTCOME_ERROR,
    OUTCOME_REJECTED,
    OUTCOME_REPAIRED,
    RepairCall,
    repair_brief,
    repair_internal_words,
)
from src.services.post_flexibility_analysis import PostFlexibilityAnalysisService
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_walk_analysis import PostWalkAnalysisService
from src.services.post_workout_analysis import (
    SYSTEM_PROMPT as RIDE_PROMPT,
)
from src.services.post_workout_analysis import (
    ClaudeGenerationResult,
    PostWorkoutAnalysisService,
)
from src.services.state_change_coach import _experiment_snapshot, plain_outcome_sentence
from tests.test_batch_302_stored_morning import (
    DAY,
    _profile,
    _RecordingClient,
    _stored,
    _writing_service,
)
from tests.test_batch_318_brief_leads import GOOD, PACKET

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-11-09-batch-382-wording.md"

#: A packet with the keys a ride read carries (the shape, not Mark's figures).
RIDE_PACKET: dict[str, Any] = {
    "packetType": "post_workout",
    "rideDeviation": {"diverged": False, "reason": None},
    "gradingTarget": {"source": "delivered_proposal", "adjustment": None},
    "upcomingWorkouts": [
        {"workoutDate": "2026-11-12", "title": "Long Z2", "source": "operator_move"}
    ],
    "execution": {"intervals": [{"hrDriftPct": 3.1, "fade": "none"}]},
}
RIDE = (
    "**Workout rating:** steady.\n\n"
    "Your heart rate drifted 3.1% across the work. Tomorrow is a Long Z2 of 120 minutes."
)


def _call(answer: str | Exception) -> tuple[list[str], RepairCall]:
    seen: list[str] = []

    async def call(system: str, user: str) -> str:
        seen.append(user)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return seen, call


# -- what counts ---------------------------------------------------------------------------


def test_plain_prose_has_none_of_the_words() -> None:
    found = internal_words(RIDE, RIDE_PACKET, prompt_text=RIDE_PROMPT)
    assert not found.found
    assert found.words == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("That is consistent with what's in the packet.", ("packet",)),
        ("The packet only gives me today's planned sessions.", ("packet",)),
        ("The context packets show it, as JSON.", ("context packets", "json")),
        ("It sits in a database field.", ("database field",)),
    ],
)
def test_the_apps_nouns_for_its_information_are_found(text: str, expected: tuple[str, ...]) -> None:
    assert internal_words(text).plumbing == expected


def test_a_packet_key_is_a_field_name_and_an_unknown_camel_word_is_not() -> None:
    text = "Your rideDeviation is clear and the upcomingWorkouts hold a ride, at 120 mmHg, 90 kJ."
    found = internal_words(text, RIDE_PACKET)
    assert found.names == ("rideDeviation", "upcomingWorkouts")
    # mmHg and kJ are camelCase but not the app's.
    assert internal_words("120 mmHg, 90 kJ, an iPhone", RIDE_PACKET).names == ()


def test_the_prompts_own_names_count_though_the_packet_omits_them() -> None:
    assert "prescribedErgMode" in RIDE_PROMPT
    assert "prescribedErgMode" not in known_names(RIDE_PACKET)
    assert internal_words("prescribedErgMode was off", RIDE_PACKET).names == ()
    found = internal_words("prescribedErgMode was off", RIDE_PACKET, prompt_text=RIDE_PROMPT)
    assert found.names == ("prescribedErgMode",)


@pytest.mark.parametrize("label", sorted(INTERNAL_SOURCE_BASIS))
def test_every_raw_source_label_is_found(label: str) -> None:
    # Post-session packets carry a planned session's raw ``source``, and from 19 Nov nine
    # Dumbbells A rows carry ``operator_move`` (Batch 381).
    assert internal_words(f"It was moved ({label}).").names == (label,)


def test_a_correlation_figure_is_found_in_every_form() -> None:
    for text in ("(r=0.26)", "(r = 0.26)", "r=-0.31", "r=+0.10", "r = −0.3"):
        assert internal_words(text).statistic_symbols, text
    assert not internal_words("a score of r2 or R=5 ohms or her=3").found


# -- the brief -----------------------------------------------------------------------------

LEAKY = GOOD.replace(
    "the session is on as written.",
    "the session is on as written. The packet only gives me today's planned sessions.",
)


def test_the_brief_check_finds_them() -> None:
    assert MISS_INTERNAL_WORDS in MISSES
    assert MISS_INTERNAL_WORDS not in check_brief(PACKET, GOOD).misses
    check = check_brief(PACKET, LEAKY)
    assert MISS_INTERNAL_WORDS in check.misses
    assert check.internal_words == ("packet",)
    assert check.to_packet()["internalWords"] == ["packet"]
    keyed = GOOD.replace(
        "A sleep score of 82.", "The overnightHrv is steady, from today_card_swap."
    )
    assert check_brief(PACKET, keyed).internal_words == ("today_card_swap", "overnightHrv")


def test_the_stored_headline_is_not_an_internal_word() -> None:
    # "Green light" is the app's own signed-off words; nothing in it has the shape.
    assert check_brief(PACKET, GOOD).internal_words == ()


async def test_the_brief_repair_says_the_fact_itself() -> None:
    seen, call = _call(GOOD)
    text, record = await repair_brief(PACKET, LEAKY, call=call)
    assert (text, record["outcome"]) == (GOOD.strip(), OUTCOME_REPAIRED)
    assert record["misses"] == [MISS_INTERNAL_WORDS]
    assert "Remove the words: packet." in seen[0]
    from src.services.plain_words_repair import BRIEF_REPAIR_SYSTEM_PROMPT

    assert "say the fact itself" in " ".join(BRIEF_REPAIR_SYSTEM_PROMPT.split())


async def test_a_brief_repair_that_keeps_the_word_is_not_kept() -> None:
    _seen, call = _call(LEAKY)
    text, record = await repair_brief(PACKET, LEAKY, call=call)
    assert (text, record["outcome"]) == (LEAKY, OUTCOME_REJECTED)
    assert record["failed"] == ["missesLeft"]


@pytest.mark.asyncio
async def test_a_brief_with_the_word_is_repaired_before_it_is_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(morning_analysis, "admin_alert", lambda *_a, **k: alerts.append(k["kind"]))
    stored = _stored(context_packet={**_stored().context_packet, **PACKET})
    service, _session, _claims = _writing_service(monkeypatch, stored)
    seen, call = _call(GOOD)

    await service.write_brief(
        _profile(), DAY, client=_RecordingClient(markdown=LEAKY), repair_call=call
    )

    assert stored.output_markdown == GOOD.strip()
    assert stored.raw_response["plainWordsRepair"]["outcome"] == OUTCOME_REPAIRED
    assert stored.raw_response[morning_analysis.BRIEF_CHECK_KEY]["passed"] is True
    assert alerts == [] and len(seen) == 1


# -- the post-session reads ----------------------------------------------------------------

LEAKY_RIDE = (
    "**Workout rating:** steady.\n\n"
    "Your heart rate drifted 3.1% across the work, and the rideDeviation is clear. "
    "That's consistent with what's in the packet. Tomorrow is a Long Z2 of 120 minutes."
)


async def test_a_clean_read_makes_no_repair_call() -> None:
    seen, call = _call(RIDE)
    text, record = await repair_internal_words(RIDE, RIDE_PACKET, call=call)
    assert (text, record, seen) == (RIDE, {"attempted": False}, [])


async def test_a_read_with_the_words_is_repaired_and_the_call_names_them() -> None:
    seen, call = _call(RIDE)
    text, record = await repair_internal_words(
        LEAKY_RIDE, RIDE_PACKET, call=call, prompt_text=RIDE_PROMPT
    )
    assert (text, record["outcome"]) == (RIDE, OUTCOME_REPAIRED)
    assert record["internalWords"] == {
        "plumbing": ["packet"],
        "names": ["rideDeviation"],
        "statisticSymbols": [],
    }
    assert seen[0].startswith("Words to remove: packet, rideDeviation.")
    assert 'never "the packet"' in " ".join(INTERNAL_WORDS_REPAIR_SYSTEM_PROMPT.split())


async def test_a_repair_that_changes_a_figure_or_keeps_a_word_is_not_kept() -> None:
    changed = RIDE.replace("3.1%", "3.8%")
    _seen, call = _call(changed)
    text, record = await repair_internal_words(LEAKY_RIDE, RIDE_PACKET, call=call)
    assert (text, record["outcome"], record["figuresChanged"]) == (
        LEAKY_RIDE,
        OUTCOME_REJECTED,
        True,
    )
    _seen, call = _call(LEAKY_RIDE)
    text, record = await repair_internal_words(LEAKY_RIDE, RIDE_PACKET, call=call)
    assert (text, record["outcome"]) == (LEAKY_RIDE, OUTCOME_REJECTED)
    assert record["wordsLeft"] == ["packet", "rideDeviation"]


async def test_a_failed_repair_call_keeps_the_original() -> None:
    _seen, call = _call(RuntimeError("provider down"))
    text, record = await repair_internal_words(LEAKY_RIDE, RIDE_PACKET, call=call)
    assert (text, record["outcome"], record["error"]) == (
        LEAKY_RIDE,
        OUTCOME_ERROR,
        "RuntimeError",
    )


def test_every_post_session_read_knows_its_prompts_names() -> None:
    for service in (
        PostWorkoutAnalysisService,
        PostStrengthAnalysisService,
        PostWalkAnalysisService,
        PostFlexibilityAnalysisService,
    ):
        assert service.system_prompt, service


@dataclass
class _LeakyRideClient:
    calls: int = 0

    async def generate(
        self, *, context_packet: dict[str, Any], user_prompt: str
    ) -> ClaudeGenerationResult:
        self.calls += 1
        return ClaudeGenerationResult(
            output_markdown=LEAKY_RIDE,
            raw_response={"id": "msg_test", "model": "claude-test", "content": []},
            model_name="claude-test",
        )


async def _ride(session: Any) -> tuple[Profile, Activity]:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Words Test",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.flush()
    activity = Activity(
        user_id=player.id,
        garmin_activity_id=382001,
        activity_name="Indoor ride",
        activity_type="indoor_cycling",
        start_utc=datetime(2026, 1, 1, 11, 0),
        duration_sec=3600,
        avg_heart_rate_bpm=141,
        avg_power_watts=221,
        raw_summary={},
    )
    session.add(activity)
    await session.commit()
    return player, activity


@pytest.mark.asyncio
async def test_a_stored_ride_read_is_repaired(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player, activity = await _ride(session)
        seen, call = _call(RIDE)

        result = await PostWorkoutAnalysisService(session).generate_and_store(
            player, activity, client=_LeakyRideClient(), repair_call=call
        )

        stored = result.analysis
        assert stored.output_markdown == RIDE
        assert stored.raw_response["plainWordsRepair"]["outcome"] == OUTCOME_REPAIRED
        assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_repair_that_fails_leaves_the_read_and_tells_craig(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts: list[dict[str, Any]] = []

    def _alert(_logger: Any, event: str, *, kind: str, **fields: Any) -> None:
        alerts.append({"event": event, "kind": kind, **fields})

    monkeypatch.setattr(post_activity_read_runner, "admin_alert", _alert)
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player, activity = await _ride(session)
        _seen, call = _call(RuntimeError("provider down"))

        result = await PostWorkoutAnalysisService(session).generate_and_store(
            player, activity, client=_LeakyRideClient(), repair_call=call
        )

        assert result.analysis.output_markdown == LEAKY_RIDE  # Mark is never held up
        assert result.analysis.raw_response["plainWordsRepair"]["outcome"] == OUTCOME_ERROR
        [alert] = alerts
        assert alert["event"] == "post_read_internal_words_left"
        assert alert["words"] == ["packet", "rideDeviation"]


@pytest.mark.asyncio
async def test_a_test_client_makes_no_repair_call(db_conn: AsyncConnection) -> None:
    # Without a ``repair_call`` and with a client passed, nothing reaches the provider.
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player, activity = await _ride(session)
        result = await PostWorkoutAnalysisService(session).generate_and_store(
            player, activity, client=_LeakyRideClient()
        )
        assert result.analysis.output_markdown == LEAKY_RIDE
        assert "plainWordsRepair" not in result.analysis.raw_response


# -- the experiment notice -----------------------------------------------------------------


def _packet(kind: str, recommendation: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "ok",
        "recommendation": recommendation,
        "evidence": evidence,
        "reasons": ["No measured candidate correlates (strongest r=+0.10, range -0.10 to +0.29)"],
    }


def _experiment() -> Experiment:
    return Experiment(
        id=uuid.uuid4(), user_id=uuid.uuid4(), title="Night waking", hypothesis="h", status="active"
    )


def test_the_refuted_correlation_notice_has_no_statistics() -> None:
    snapshot = _experiment_snapshot(
        _experiment(),
        _packet("correlation", "refuted", {"strongestDriver": "sleep_stress_avg"}),
    )
    assert snapshot is not None
    assert not internal_words(snapshot.message).found
    assert "r=" not in snapshot.message and "range" not in snapshot.message
    assert snapshot.state_value == "refuted"  # what makes it a transition is unchanged
    assert "I have not concluded it for you" in snapshot.message


def test_the_supported_correlation_notice_names_the_driver_in_words() -> None:
    sentence = plain_outcome_sentence(
        _packet("correlation", "supported", {"strongestDriver": "bedroom_peak_fan_speed"})
    )
    assert sentence == (
        "Fan speed moves closely with the disturbed nights, so it looks like a trigger."
    )


def test_every_kind_has_a_plain_sentence_and_a_missing_figure_has_none() -> None:
    gate = plain_outcome_sentence(
        _packet("gate", "supported", {"currentStreak": 7, "gateNights": 7, "floor": 75})
    )
    rem = plain_outcome_sentence(
        _packet("intervention_compare", "supported", {"remPctDelta": 2.4, "awakeMinDelta": -12.0})
    )
    group = plain_outcome_sentence(
        _packet(
            "group_compare",
            "refuted",
            {"metricLabel": "HRV", "units": "ms", "recoveryMean": 44.1, "buildMean": 51.2},
        )
    )
    assert gate.startswith("Your age-adjusted sleep score has stayed at or above 75 for 7 nights")
    assert rem.startswith("On the nights you tried it, REM was 2.4 percentage points higher")
    assert "you were awake 12 minutes less" in rem
    assert group.startswith("Your HRV averaged 44.1 ms in recovery weeks against 51.2 ms")
    for sentence in (gate, rem, group):
        assert not internal_words(sentence).found
    # No figure to build from: no sentence, never the technical line.
    assert plain_outcome_sentence(_packet("gate", "supported", {})) == ""
    assert plain_outcome_sentence(_packet("correlation", "supported", {})) == ""
    assert plain_outcome_sentence({"kind": "gate", "recommendation": "supported"}) == ""


def test_the_notice_words_are_the_signed_off_draft() -> None:
    draft = " ".join(DRAFT.read_text(encoding="utf-8").replace("**", "").split())
    for sentence in (
        plain_outcome_sentence(_packet("correlation", "refuted", {})),
        plain_outcome_sentence(
            _packet("correlation", "supported", {"strongestDriver": "bedroom_peak_fan_speed"})
        ),
        plain_outcome_sentence(
            _packet("gate", "supported", {"currentStreak": 7, "gateNights": 7, "floor": 75})
        ),
        plain_outcome_sentence(
            _packet(
                "intervention_compare", "supported", {"remPctDelta": 2.4, "awakeMinDelta": -12.0}
            )
        ),
        plain_outcome_sentence(
            _packet(
                "group_compare",
                "refuted",
                {"metricLabel": "HRV", "units": "ms", "recoveryMean": 44.1, "buildMean": 51.2},
            )
        ),
    ):
        assert sentence in draft
