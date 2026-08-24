"""Batch 220: compact evidence, banding and honesty-policy tests."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.models.coaching import ManualEntry
from src.services.longitudinal_analysis import (
    COLUMNS,
    MIN_STRUCTURED_SETUP_NIGHTS,
    DataQualityFlagFinding,
    FindingBand,
    LongitudinalFinding,
    LongitudinalFindings,
    NightEvidence,
    ProposedExperimentFinding,
    ReachabilityFinding,
    _manual_context,
    anthropic_output_schema,
    build_longitudinal_packet,
    build_message_params,
    enforce_findings_policy,
    parse_batch_result,
    temperature_bands,
)


def _night(
    offset: int,
    *,
    temperature: float | None,
    rem: float,
    awake: float,
    setup: bool = False,
    note: str | None = None,
) -> NightEvidence:
    return NightEvidence(
        calendar_date=date(2026, 1, 1) + timedelta(days=offset),
        sleep_score=80,
        rem_sleep_min=rem,
        awake_sleep_min=awake,
        bedroom_mean_temp_c=temperature,
        setup_recorded=setup,
        bedding_weight="thin_cover" if setup else None,
        notes=(note,) if note else (),
    )


def _temperature_finding(
    *,
    evidence_status: str = "supported",
    confidence: str = "high",
    reachability: str = "reachable",
) -> LongitudinalFinding:
    return LongitudinalFinding.model_validate(
        {
            "findingKey": "temperature-optimum",
            "topic": "temperature_sleep",
            "observation": "The middle temperature band has the strongest observed outcomes.",
            "confidence": confidence,
            "evidenceStatus": evidence_status,
            "evidenceSummary": ["Three measured temperature bands are present."],
            "temperatureBands": [
                {
                    "lowerC": 99,
                    "upperC": 100,
                    "nights": 1,
                    "remMeanMin": 1,
                    "awakeMeanMin": 1,
                    "sleepScoreMean": 1,
                }
            ],
            "confounds": [],
            "reachability": {
                "status": reachability,
                "explanation": "The proposed range appears reachable from the supplied evidence.",
            },
            "proposedExperiment": None,
            "dataQualityFlag": None,
        }
    )


def test_temperature_bands_preserve_a_synthetic_u_shape() -> None:
    nights = [
        _night(0, temperature=17.2, rem=35, awake=70),
        _night(1, temperature=17.4, rem=37, awake=68),
        _night(2, temperature=18.2, rem=70, awake=25),
        _night(3, temperature=18.4, rem=72, awake=23),
        _night(4, temperature=19.2, rem=36, awake=69),
        _night(5, temperature=19.4, rem=34, awake=71),
    ]

    bands = temperature_bands(nights)

    assert [band["lowerC"] for band in bands] == [17.0, 18.0, 19.0]
    assert [band["nights"] for band in bands] == [2, 2, 2]
    assert [band["remMeanMin"] for band in bands] == [36.0, 71.0, 35.0]
    assert [band["awakeMeanMin"] for band in bands] == [69.0, 24.0, 70.0]


def test_packet_is_columnar_deterministic_and_clock_free() -> None:
    later = _night(2, temperature=19.4, rem=55, awake=30, setup=True)
    earlier = _night(1, temperature=18.4, rem=60, awake=25)

    first = build_longitudinal_packet([later, earlier], as_of_date=date(2026, 1, 3))
    second = build_longitudinal_packet([earlier, later], as_of_date=date(2026, 1, 3))

    assert first == second
    assert first["columns"] == list(COLUMNS)
    assert first["nights"][0][0] == "2026-01-02"
    assert "generatedAtUtc" not in first
    assert first["coverage"]["structuredSetupNights"] == 1
    assert first["coverage"]["causalTemperatureClaimEligible"] is False


def test_coverage_requires_three_populated_temperature_bands() -> None:
    nights = [
        _night(
            offset,
            temperature=17.2 + (offset % 3),
            rem=60,
            awake=30,
            setup=True,
        )
        for offset in range(21)
    ]

    packet = build_longitudinal_packet(nights, as_of_date=date(2026, 1, 21))

    assert packet["coverage"]["qualifiedTemperatureBands"] == 3
    assert packet["coverage"]["causalTemperatureClaimEligible"] is True


def test_activity_entry_cannot_erase_the_morning_sleep_setup() -> None:
    user_id = uuid.uuid4()
    wake_date = date(2026, 1, 2)
    morning = ManualEntry(
        user_id=user_id,
        entry_date=wake_date,
        entry_at_utc=datetime(2026, 1, 2, 7),
        sleep_setup_json={"beddingWeight": "thin_cover"},
        notes="Window open.",
    )
    activity = ManualEntry(
        user_id=user_id,
        activity_id=uuid.uuid4(),
        entry_date=wake_date,
        entry_at_utc=datetime(2026, 1, 2, 18),
        sleep_setup_json={},
        notes="Ride felt steady.",
    )

    setup, notes = _manual_context([morning, activity])

    assert setup == {"beddingWeight": "thin_cover"}
    assert notes == ("Window open.", "Ride felt steady.")


def test_insufficient_setup_forces_inconclusive_and_keeps_measured_bands() -> None:
    nights = [
        _night(0, temperature=17.2, rem=40, awake=60),
        _night(1, temperature=18.2, rem=70, awake=25),
        _night(2, temperature=19.2, rem=42, awake=58),
    ]
    packet = build_longitudinal_packet(nights, as_of_date=date(2026, 1, 3))
    model_claim = LongitudinalFindings(findings=[_temperature_finding()])

    guarded = enforce_findings_policy(packet, model_claim)
    finding = guarded.findings[0]

    assert finding.evidence_status == "inconclusive"
    assert finding.confidence == "low"
    assert finding.temperature_bands == [
        FindingBand.model_validate(band) for band in packet["temperatureBands"]
    ]
    assert finding.proposed_experiment is not None
    assert finding.proposed_experiment.minimum_nights == MIN_STRUCTURED_SETUP_NIGHTS
    assert finding.data_quality_flag is not None
    assert finding.data_quality_flag.kind == "insufficient_setup_coverage"
    assert any("structured sleep setup" in confound for confound in finding.confounds)


def test_explicit_hot_night_constraint_prevents_fully_reachable_claim() -> None:
    note = "On hot days there is nothing else I can do; the room was as cool as possible."
    nights = [
        _night(
            offset,
            temperature=18.2,
            rem=60,
            awake=30,
            setup=True,
            note=note if offset == 0 else None,
        )
        for offset in range(MIN_STRUCTURED_SETUP_NIGHTS)
    ]
    packet = build_longitudinal_packet(
        nights,
        as_of_date=date(2026, 1, 1) + timedelta(days=MIN_STRUCTURED_SETUP_NIGHTS),
    )

    guarded = enforce_findings_policy(
        packet,
        LongitudinalFindings(findings=[_temperature_finding()]),
    )

    assert guarded.findings[0].reachability.status == "partly_reachable"
    assert "hot nights" in guarded.findings[0].reachability.explanation


def test_findings_schema_rejects_unknown_fields() -> None:
    payload = _temperature_finding().model_dump(by_alias=True, mode="json")
    payload["unsupported"] = True

    with pytest.raises(ValidationError):
        LongitudinalFinding.model_validate(payload)


def test_message_params_use_current_structured_output_shape() -> None:
    packet = build_longitudinal_packet(
        [_night(0, temperature=18.5, rem=60, awake=30)],
        as_of_date=date(2026, 1, 1),
    )

    params, prompt = build_message_params(packet, model_name="claude-test", max_tokens=2048)

    assert params["model"] == "claude-test"
    assert params["max_tokens"] == 2048
    assert params["output_config"]["format"]["type"] == "json_schema"
    schema = params["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert "findings" in schema["required"]
    assert '"columns"' in prompt
    assert '"nights"' in prompt


def test_provider_schema_strips_constraints_but_local_model_keeps_them() -> None:
    provider_schema = json.dumps(anthropic_output_schema(), sort_keys=True)
    local_schema = json.dumps(LongitudinalFindings.model_json_schema(by_alias=True), sort_keys=True)

    assert '"minimum"' not in provider_schema
    assert '"maxLength"' not in provider_schema
    assert '"maxItems"' not in provider_schema
    assert '"minimum"' in local_schema
    assert '"maxLength"' in local_schema


# Explicit construction smoke for nullable structured-output branches.  These
# are required-but-null in the provider schema, not optional missing keys.
def test_nullable_finding_branches_are_schema_members() -> None:
    finding = _temperature_finding()
    assert finding.proposed_experiment is None
    assert finding.data_quality_flag is None
    assert isinstance(
        ProposedExperimentFinding.model_validate(
            {
                "title": "Stable setup trial",
                "hypothesis": "A stable setup separates temperature from bedding.",
                "minimumNights": 21,
                "setupToHoldConstant": ["bedding"],
                "measurements": ["REM minutes"],
                "reachabilityPlan": "Record what the room can achieve each night.",
            }
        ),
        ProposedExperimentFinding,
    )
    assert isinstance(
        DataQualityFlagFinding(
            kind="confounded_history", detail="Bedding and windows changed together."
        ),
        DataQualityFlagFinding,
    )
    assert isinstance(
        ReachabilityFinding(status="unknown", explanation="No constraint was recorded."),
        ReachabilityFinding,
    )


def test_batch_result_parses_schema_constrained_text() -> None:
    payload = LongitudinalFindings(findings=[_temperature_finding()]).model_dump_json(by_alias=True)
    parsed, raw = parse_batch_result(
        [
            {
                "custom_id": "longitudinal-test",
                "result": {
                    "type": "succeeded",
                    "message": {
                        "model": "claude-test",
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": payload}],
                    },
                },
            }
        ],
        custom_id="longitudinal-test",
    )

    assert parsed.findings[0].finding_key == "temperature-optimum"
    assert raw["custom_id"] == "longitudinal-test"
