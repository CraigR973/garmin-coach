"""Postgres lifecycle coverage for the Batch 220 durable finding rail."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.config import settings
from src.models.coaching import Analysis, Experiment, Sleep
from src.models.notification import PushSubscription
from src.models.profile import Profile, UserRole
from src.services.longitudinal_analysis import (
    LongitudinalAnalysisService,
    LongitudinalFindings,
    billing_alert_readiness,
)


class _BatchClient:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.submissions = 0

    async def count_tokens(self, params: dict[str, Any]) -> int:
        return 2345

    async def submit(self, *, custom_id: str, params: dict[str, Any]) -> dict[str, Any]:
        self.submissions += 1
        self.custom_id = custom_id
        return {
            "id": "msgbatch_test",
            "processing_status": "in_progress",
            "request_counts": {
                "processing": 1,
                "succeeded": 0,
                "errored": 0,
                "canceled": 0,
                "expired": 0,
            },
        }

    async def retrieve(self, batch_id: str) -> dict[str, Any]:
        return {
            "id": batch_id,
            "processing_status": "ended",
            "request_counts": {
                "processing": 0,
                "succeeded": 1,
                "errored": 0,
                "canceled": 0,
                "expired": 0,
            },
        }

    async def results(self, batch_id: str) -> list[dict[str, Any]]:
        return [
            {
                "custom_id": self.custom_id,
                "result": {
                    "type": "succeeded",
                    "message": {
                        "model": "claude-test",
                        "stop_reason": "end_turn",
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(self.output, separators=(",", ":")),
                            }
                        ],
                        "usage": {"input_tokens": 2345, "output_tokens": 321},
                    },
                },
            }
        ]


class _TransientPollClient(_BatchClient):
    async def retrieve(self, batch_id: str) -> dict[str, Any]:
        raise RuntimeError("temporary network failure")


def _finding_payload() -> dict[str, Any]:
    return {
        "findings": [
            {
                "findingKey": "temperature-optimum",
                "topic": "temperature_sleep",
                "observation": (
                    "Current temperature evidence is confounded and cannot establish an optimum."
                ),
                "confidence": "moderate",
                "evidenceStatus": "supported",
                "evidenceSummary": ["Bedroom coverage exists for part of the history."],
                "temperatureBands": [],
                "confounds": ["Bedding was not structured historically."],
                "reachability": {
                    "status": "unknown",
                    "explanation": "Achievable temperatures were not consistently recorded.",
                },
                "proposedExperiment": None,
                "dataQualityFlag": None,
            }
        ]
    }


async def _seed_profiles(
    session: AsyncSession, *, player_id: uuid.UUID, operator_id: uuid.UUID
) -> tuple[Profile, Profile]:
    player = Profile(
        id=player_id,
        display_name="Longitudinal player",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    operator = Profile(
        id=operator_id,
        display_name="Longitudinal operator",
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    session.add_all([player, operator])
    # These models do not expose ORM relationships, so make the FK ordering
    # explicit instead of relying on unit-of-work table sorting.
    await session.flush()
    session.add(
        PushSubscription(
            user_id=operator_id,
            subscription={
                "endpoint": "https://push.example/operator",
                "keys": {"p256dh": "test", "auth": "test"},
            },
            device_hint="operator-test",
            is_active=True,
        )
    )
    session.add(
        Sleep(
            user_id=player_id,
            calendar_date=date(2026, 8, 24),
            sleep_start_utc=datetime(2026, 8, 23, 22, 0),
            sleep_end_utc=datetime(2026, 8, 24, 6, 30),
            score=77,
            duration_sec=8 * 3600,
            rem_sleep_sec=55 * 60,
            awake_sleep_sec=42 * 60,
            factors_json={},
            raw_payload={},
        )
    )
    await session.commit()
    return player, operator


@pytest.mark.asyncio
async def test_submit_collect_and_route_are_durable_and_idempotent(
    db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    monkeypatch.setattr(settings, "admin_alert_user_id", str(operator_id))
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player, _operator = await _seed_profiles(
            session, player_id=player_id, operator_id=operator_id
        )
        assert (await billing_alert_readiness(session)).ready is True
        client = _BatchClient(_finding_payload())
        service = LongitudinalAnalysisService(session)

        submitted = await service.submit_monthly(
            player,
            as_of_date=date(2026, 8, 24),
            client=client,
        )
        assert submitted.submitted is True
        assert submitted.input_tokens == 2345
        assert submitted.analysis.verdict == "pending"

        duplicate = await service.submit_monthly(
            player,
            as_of_date=date(2026, 8, 24),
            client=client,
        )
        assert duplicate.submitted is False
        assert duplicate.analysis.id == submitted.analysis.id
        assert client.submissions == 1

        collected = await service.collect_pending(player, client=client)
        assert collected.completed == 1
        assert collected.findings_routed == 1

        await session.refresh(submitted.analysis)
        assert submitted.analysis.verdict == "completed"
        findings = LongitudinalFindings.model_validate(
            submitted.analysis.raw_response["structuredFindings"]
        )
        finding = findings.findings[0]
        assert finding.evidence_status == "inconclusive"
        assert finding.confidence == "low"
        assert finding.proposed_experiment is not None
        assert finding.data_quality_flag is not None

        experiment = await session.scalar(
            select(Experiment).where(
                Experiment.user_id == player_id,
                Experiment.success_criteria_json["slug"].astext == "early_waking_0400",
            )
        )
        assert experiment is not None
        entries = experiment.observations_json["entries"]
        routed = [
            entry
            for entry in entries
            if entry["metrics"].get("longitudinalAnalysisId") == str(submitted.analysis.id)
        ]
        assert len(routed) == 1
        assert routed[0]["metrics"]["findingKey"] == "temperature-optimum"

        # A collector rerun sees no pending row and cannot duplicate the observation.
        again = await service.collect_pending(player, client=client)
        assert again.completed == 0
        await session.refresh(experiment)
        assert len(experiment.observations_json["entries"]) == len(entries)

        audit_rows = list(
            (
                await session.execute(
                    select(Analysis).where(
                        Analysis.user_id == player_id,
                        Analysis.analysis_type == "experiment_update",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(row.context_packet.get("action") == "observation" for row in audit_rows)


@pytest.mark.asyncio
async def test_billing_alert_gate_requires_an_active_subscription(
    db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_id = uuid.uuid4()
    monkeypatch.setattr(settings, "admin_alert_user_id", str(operator_id))
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=operator_id,
                display_name="Operator without push",
                role=UserRole.player,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()

        self_readiness = await billing_alert_readiness(
            session,
            subject_profile_id=operator_id,
        )
        readiness = await billing_alert_readiness(session)

        assert self_readiness.ready is False
        assert self_readiness.reason == "admin_alert_points_to_subject"
        assert readiness.ready is False
        assert readiness.reason == "admin_alert_subscription_missing"


@pytest.mark.asyncio
async def test_transient_collection_failure_keeps_analysis_pending(
    db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    monkeypatch.setattr(settings, "admin_alert_user_id", str(operator_id))
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player, _operator = await _seed_profiles(
            session,
            player_id=player_id,
            operator_id=operator_id,
        )
        client = _TransientPollClient(_finding_payload())
        service = LongitudinalAnalysisService(session)
        submitted = await service.submit_monthly(
            player,
            as_of_date=date(2026, 8, 24),
            client=client,
        )

        with pytest.raises(RuntimeError, match="temporary network failure"):
            await service.collect_pending(player, client=client)

        await session.refresh(submitted.analysis)
        assert submitted.analysis.verdict == "pending"
        assert submitted.analysis.raw_response["collectionError"]["reason"] == ("collection_failed")
