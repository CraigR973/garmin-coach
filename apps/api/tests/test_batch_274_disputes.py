"""Batch 274 — a dispute that is recorded, and changes nothing.

Mark's only remedy for a figure he believed wrong was to argue with a coach that
agreed with him and could do nothing, and the argument evaporated into chat. A
contest now records the figure, the working the app showed (Batch 273), his reason
and the date, and tells Craig. A dissent records his disagreement with a day's
verdict beside the day, for the weekly review.

**The line this batch must not cross:** recording changes no rollup, verdict, VO2
block or chronic cluster. Suppressing a contested input is Batch 276, and the
boundary test below makes it impossible for that to arrive early by accident.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.config import settings
from src.models.coaching import Analysis, Dispute
from src.models.profile import Profile, UserRole
from src.services.disputes import KIND_FIGURE, KIND_VERDICT, DisputeService
from src.services.nudge_alerts import NudgeAlertService, build_admin_contest_alert_plan
from src.services.provenance import FIGURE_BEDROOM_PEAK, find_provenance

SERVICES = Path(__file__).resolve().parents[1] / "src" / "services"

BEDROOM_PEAK = {
    "figure": FIGURE_BEDROOM_PEAK,
    "label": "bedroom peak overnight",
    "value": 21.4,
    "units": "°C",
    "rule": "the highest reading inside the window — no sleep times were recorded",
    "window": {
        "kind": "night_fallback",
        "startUtc": None,
        "endUtc": None,
        "label": "a clock window",
    },
    "sources": {
        "table": "temperature_readings",
        "rowsInWindow": 17,
        "firstReadingUtc": "2026-09-08T13:07:00",
    },
    "threshold": {
        "name": "thermal disruption",
        "comparedAgainst": 20.0,
        "units": "°C",
        "source": "kb",
    },
}


def _morning_packet(*, with_working: bool = True, status: str = "Red") -> dict[str, Any]:
    thermal: dict[str, Any] = {"indoorPeakC": 21.4}
    if with_working:
        thermal["provenance"] = [BEDROOM_PEAK]
    return {
        "environment": {"thermalReview": thermal},
        "verdict": {
            "status": status,
            "reasons": ["Overnight HRV sets an Amber ceiling."],
            "acutePhysiology": {"requiresBikeRest": False},
        },
    }


# -- pure --------------------------------------------------------------------


def test_the_working_is_found_wherever_a_read_keeps_it() -> None:
    assert find_provenance(_morning_packet(), FIGURE_BEDROOM_PEAK) == BEDROOM_PEAK
    ride = {"execution": {"provenance": [{"figure": "execution.onTargetCount", "value": 11}]}}
    assert find_provenance(ride, "execution.onTargetCount") == {
        "figure": "execution.onTargetCount",
        "value": 11,
    }
    assert find_provenance(_morning_packet(with_working=False), FIGURE_BEDROOM_PEAK) is None


#: Every module that decides a rollup, a verdict, the VO2 block or a chronic cluster.
DECIDING_MODULES = (
    "morning_verdict.py",
    "morning_analysis.py",
    "verdict_scaling.py",
    "executable_coaching.py",
    "chronic_patterns.py",
    "reviews.py",
    "trends.py",
    "coach_sections.py",
    "ride_intervals.py",
    "weekly_restructure.py",
    "personal_baselines.py",
    "metric_statements.py",
)


@pytest.mark.parametrize("module", DECIDING_MODULES)
def test_nothing_that_decides_anything_reads_a_dispute(module: str) -> None:
    """The 274/276 boundary. A contested figure still feeds the next rollup, and a
    dissent moves no verdict, because none of these modules can see either."""
    source = (SERVICES / module).read_text()
    assert "disputes" not in source
    assert "Dispute" not in source


def test_the_alert_names_the_figure_and_quotes_mark() -> None:
    dispute_id = uuid.uuid4()
    plan = build_admin_contest_alert_plan(
        dispute_id=dispute_id,
        label="bedroom peak overnight",
        value=21.4,
        units="°C",
        subject_date=date(2026, 9, 9),
        reason="That 21.4 is from 14:07 — not my night.",
    )
    assert plan.tag == f"admin-figure-contest-{dispute_id}"
    assert plan.body == (
        "bedroom peak overnight (21.4 °C) on 2026-09-09: “That 21.4 is from 14:07 — not my night.”"
    )


@pytest.mark.asyncio
async def test_with_no_operator_configured_the_alert_only_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "admin_alert_user_id", "")
    sent = await NudgeAlertService(MagicMock()).notify_admin_figure_contest(
        dispute_id=uuid.uuid4(),
        label="bedroom peak overnight",
        value=21.4,
        units="°C",
        subject_date=date(2026, 9, 9),
        reason="Not my night.",
    )
    assert sent is False


# -- the service -------------------------------------------------------------


async def _mark(session: AsyncSession, *, name: str = "Dispute Test") -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name=name,
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.commit()
    return player


async def _read(
    session: AsyncSession, player: Profile, packet: dict[str, Any], day: date = date(2026, 9, 9)
) -> Analysis:
    analysis = Analysis(
        user_id=player.id,
        analysis_type="morning",
        subject_date=day,
        generated_at_utc=datetime(2026, 9, 9, 7, 30),
        prompt_version="morning-analysis-test",
        verdict=str(packet["verdict"]["status"]),
        context_packet=packet,
        output_markdown="Read",
        raw_response={},
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    return analysis


async def _disputes(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Dispute)) or 0)


@pytest.mark.asyncio
async def test_a_contest_keeps_the_working_mark_was_shown(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_alert_user_id", "")
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _mark(session)
        analysis = await _read(session, player, _morning_packet())
        before = json.dumps(analysis.context_packet, sort_keys=True)

        dispute = await DisputeService(session).contest_figure(
            player,
            analysis_id=analysis.id,
            figure=FIGURE_BEDROOM_PEAK,
            reason="  That 21.4 is from 14:07 — not my night.  ",
        )
        await session.refresh(analysis)

        assert dispute.kind == KIND_FIGURE
        assert dispute.figure == FIGURE_BEDROOM_PEAK
        assert dispute.snapshot == BEDROOM_PEAK
        assert dispute.reason == "That 21.4 is from 14:07 — not my night."
        assert dispute.subject_date == date(2026, 9, 9)
        assert dispute.analysis_id == analysis.id
        # Recording changes the read it contests not at all.
        assert json.dumps(analysis.context_packet, sort_keys=True) == before
        assert await _disputes(session) == 1


@pytest.mark.asyncio
async def test_a_contest_without_working_is_refused(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_alert_user_id", "")
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _mark(session)
        bare = await _read(session, player, _morning_packet(with_working=False))
        for figure in (FIGURE_BEDROOM_PEAK, "verdict.sleepCreditCeiling"):
            with pytest.raises(HTTPException) as refused:
                await DisputeService(session).contest_figure(
                    player, analysis_id=bare.id, figure=figure, reason="Looks wrong."
                )
            assert refused.value.status_code == 422
        with pytest.raises(HTTPException) as empty:
            await DisputeService(session).contest_figure(
                player, analysis_id=bare.id, figure=FIGURE_BEDROOM_PEAK, reason="   "
            )
        assert empty.value.status_code == 422

        someone_else = await _mark(session, name="Someone Else")
        theirs = await _read(session, someone_else, _morning_packet())
        with pytest.raises(HTTPException) as not_his:
            await DisputeService(session).contest_figure(
                player, analysis_id=theirs.id, figure=FIGURE_BEDROOM_PEAK, reason="Wrong."
            )
        assert not_his.value.status_code == 404
        assert await _disputes(session) == 0


@pytest.mark.asyncio
async def test_a_dissent_leaves_the_days_verdict_exactly_as_it_was(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _mark(session)
        analysis = await _read(session, player, _morning_packet(status="Red"))
        before = (analysis.verdict, json.dumps(analysis.context_packet, sort_keys=True))

        dissent = await DisputeService(session).dissent_from_verdict(
            player,
            subject_date=date(2026, 9, 9),
            reason="HRV was a point under a floor Garmin moved. I felt fine.",
        )
        await session.refresh(analysis)

        assert dissent.kind == KIND_VERDICT
        assert dissent.snapshot["status"] == "Red"
        assert dissent.figure is None
        assert (analysis.verdict, json.dumps(analysis.context_packet, sort_keys=True)) == before
        assert await _disputes(session) == 1

        in_week = await DisputeService(session).between(
            player.id, date(2026, 9, 7), date(2026, 9, 13), kind=KIND_VERDICT
        )
        assert [row.id for row in in_week] == [dissent.id]

        with pytest.raises(HTTPException) as no_verdict:
            await DisputeService(session).dissent_from_verdict(
                player, subject_date=date(2026, 9, 10), reason="Disagree."
            )
        assert no_verdict.value.status_code == 404


@pytest.mark.asyncio
async def test_with_an_operator_configured_the_contest_is_pushed_to_craig(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _mark(session)
        operator = await _mark(session, name="Operator")
        monkeypatch.setattr(settings, "admin_alert_user_id", str(operator.id))
        sent: list[tuple[uuid.UUID, str]] = []

        async def _record(self: NudgeAlertService, profile: Profile, plan: Any, **_: Any) -> bool:
            sent.append((profile.id, plan.tag))
            return True

        monkeypatch.setattr(NudgeAlertService, "_send_once", _record)
        analysis = await _read(session, player, _morning_packet())
        dispute = await DisputeService(session).contest_figure(
            player, analysis_id=analysis.id, figure=FIGURE_BEDROOM_PEAK, reason="Not my night."
        )

    assert sent == [(operator.id, f"admin-figure-contest-{dispute.id}")]
