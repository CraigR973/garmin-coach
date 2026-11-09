"""Operator tools for who moved a session and why (Batch 381).

Two commands, run inside the api container (``PYTHONPATH=/app python -m
src.tools.move_provenance ...``):

* ``move``: Craig moves a session. It goes through the app's own ``swap_day``, so the
  Zwift event and the swap rules behave exactly as for Mark's move, but the rows are
  stamped ``operator_move`` and the audit row records the reason. A reason is required.
  It changes Zwift as the app does, so there is no dry run; ``--yes`` is required.
* ``correct-2-nov``: the one correction Craig approved in advance on 8 Nov (Decision
  #485). The ten Dumbbells A moves of 2 Nov 2026 (Decision #462) ran ``swap_day`` before
  it knew who was moving, so they say Mark moved them from the Today card. Only the rows
  still active and still carrying that label are corrected; Mark moved one back himself
  two minutes later, and that move, like every other of his, is left alone. A dry run
  by default; ``--commit`` writes in one transaction and refuses unless it finds exactly
  the expected rows. Either way it prints the old values as JSON, so the write can be
  undone.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, PlannedWorkout
from src.models.profile import Profile
from src.services.move_provenance import (
    AUDIT_TYPE_MOVED,
    MOVE_REASON_KEY,
    MOVED_BY_KEY,
    MOVED_BY_OPERATOR,
    OPERATOR_MOVE_SOURCE,
    OWNER_MOVE_SOURCE,
    operator_move,
)

#: The 2 Nov 2026 move under Decision #462: ten audit rows written 13:00:09-13:00:27 UTC.
NOV_2_MOVE_FROM_UTC = datetime(2026, 11, 2, 13, 0, 0)
NOV_2_MOVE_TO_UTC = datetime(2026, 11, 2, 13, 1, 0)
NOV_2_TITLE_PREFIX = "Dumbbells A"
#: Craig's approval holds only for exactly this many rows (Decision #485).
NOV_2_EXPECTED_ROWS = 9

#: The reason recorded on the corrected rows, as Craig signed it off on 9 Nov (Decision #489).
NOV_2_REASON = (
    "Craig moved Dumbbells A from Mondays to Thursdays for this plan, so it no longer "
    "falls the day before Tuesday's VO₂ session; on Thursday it comes after the "
    "sweet-spot ride and 48 hours before Saturday's ride."
)

#: Recorded on each corrected audit row so the correction is visible and reversible.
CORRECTION_KEY = "provenanceCorrection"


@dataclass(frozen=True)
class CorrectionRow:
    workout: PlannedWorkout
    audit: Analysis

    def describe(self) -> dict[str, Any]:
        return {
            "plannedWorkoutId": str(self.workout.id),
            "workoutDate": self.workout.workout_date.isoformat(),
            "weekday": self.workout.workout_date.strftime("%a"),
            "title": self.workout.title,
            "version": self.workout.version,
            "status": self.workout.status,
            "oldSource": self.workout.source,
            "auditId": str(self.audit.id),
            "auditSubjectDate": self.audit.subject_date.isoformat(),
            "oldAuditContextPacket": dict(self.audit.context_packet or {}),
        }


async def nov_2_rows(session: AsyncSession) -> list[CorrectionRow]:
    """The 2 Nov operator moves whose row is still active and still labelled as Mark's."""
    audits = (
        (
            await session.execute(
                select(Analysis)
                .where(
                    Analysis.analysis_type == AUDIT_TYPE_MOVED,
                    Analysis.generated_at_utc >= NOV_2_MOVE_FROM_UTC,
                    Analysis.generated_at_utc < NOV_2_MOVE_TO_UTC,
                )
                .order_by(Analysis.generated_at_utc)
            )
        )
        .scalars()
        .all()
    )
    rows: list[CorrectionRow] = []
    for audit in audits:
        packet = audit.context_packet if isinstance(audit.context_packet, dict) else {}
        raw_id = packet.get("plannedWorkoutId")
        if not isinstance(raw_id, str):
            continue
        workout = await session.get(PlannedWorkout, uuid.UUID(raw_id))
        if (
            workout is None
            or workout.user_id != audit.user_id
            or not workout.is_active
            or workout.source != OWNER_MOVE_SOURCE
            or not workout.title.startswith(NOV_2_TITLE_PREFIX)
        ):
            continue
        rows.append(CorrectionRow(workout=workout, audit=audit))
    return sorted(rows, key=lambda row: row.workout.workout_date)


async def correct_nov_2(
    session: AsyncSession,
    *,
    commit: bool,
    expected_ids: set[uuid.UUID] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Dry run, or the one-transaction write, of the 2 Nov correction."""
    rows = await nov_2_rows(session)
    report: dict[str, Any] = {
        "dryRun": not commit,
        "found": len(rows),
        "expected": NOV_2_EXPECTED_ROWS,
        "newSource": OPERATOR_MOVE_SOURCE,
        "reason": NOV_2_REASON,
        "rows": [row.describe() for row in rows],
    }
    if not commit:
        return report
    if len(rows) != NOV_2_EXPECTED_ROWS:
        raise SystemExit(
            f"Refusing to write: found {len(rows)} rows, Craig approved exactly "
            f"{NOV_2_EXPECTED_ROWS}"
        )
    if expected_ids is None:
        raise SystemExit("Refusing to write: list the dry run's row ids with --expect-ids")
    if {row.workout.id for row in rows} != expected_ids:
        raise SystemExit("Refusing to write: the rows found are not the rows listed")
    stamp = (now_utc or datetime.now(UTC).replace(tzinfo=None)).isoformat()
    for row in rows:
        row.workout.source = OPERATOR_MOVE_SOURCE
        packet = dict(row.audit.context_packet or {})
        packet[MOVED_BY_KEY] = MOVED_BY_OPERATOR
        packet[MOVE_REASON_KEY] = NOV_2_REASON
        packet[CORRECTION_KEY] = {
            "previousSource": OWNER_MOVE_SOURCE,
            "previousMovedBy": None,
            "correctedAtUtc": stamp,
            "basis": "Craig's 8 Nov approval of this correction",
        }
        row.audit.context_packet = packet
    await session.commit()
    report["written"] = len(rows)
    return report


async def undo_nov_2(session: AsyncSession, old: dict[str, Any]) -> int:
    """Put back the values a ``correct-2-nov --commit`` report recorded."""
    restored = 0
    for item in old["rows"]:
        workout = await session.get(PlannedWorkout, uuid.UUID(item["plannedWorkoutId"]))
        audit = await session.get(Analysis, uuid.UUID(item["auditId"]))
        if workout is None or audit is None:
            continue
        workout.source = item["oldSource"]
        audit.context_packet = dict(item["oldAuditContextPacket"])
        restored += 1
    await session.commit()
    return restored


async def operator_move_session(
    session: AsyncSession,
    *,
    planned_workout_id: uuid.UUID,
    target_date: date,
    reason: str,
) -> PlannedWorkout:
    """Move one session on Craig's behalf through the app's own move."""
    from src.services.executable_coaching import ExecutableCoachingService

    provenance = operator_move(reason)
    workout = await session.get(PlannedWorkout, planned_workout_id)
    if workout is None:
        raise SystemExit("No such planned session")
    player = await session.get(Profile, workout.user_id)
    if player is None:
        raise SystemExit("The session's profile is missing")
    return await ExecutableCoachingService(session).swap_day(
        player,
        planned_workout_id=planned_workout_id,
        target_date=target_date,
        provenance=provenance,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.tools.move_provenance")
    commands = parser.add_subparsers(dest="command", required=True)
    move = commands.add_parser("move", help="Craig moves a session, with a reason")
    move.add_argument("--workout-id", required=True, type=uuid.UUID)
    move.add_argument("--to", required=True, type=date.fromisoformat)
    move.add_argument("--reason", required=True)
    move.add_argument("--yes", action="store_true", help="really move it (Zwift too)")
    correct = commands.add_parser("correct-2-nov", help="the 2 Nov Dumbbells A correction")
    correct.add_argument("--commit", action="store_true")
    correct.add_argument("--expect-ids", help="comma-separated planned workout ids")
    undo = commands.add_parser("undo-2-nov", help="restore from a correct-2-nov report")
    undo.add_argument("--report", required=True, help="path to the JSON report")
    return parser


async def _main(argv: list[str]) -> int:
    from src.database import AsyncSessionLocal

    args = _parser().parse_args(argv)
    async with AsyncSessionLocal() as session:
        if args.command == "move":
            operator_move(args.reason)  # validate before anything else
            if not args.yes:
                print("Not moved: pass --yes to move it (this changes Zwift as the app does)")
                return 2
            moved = await operator_move_session(
                session,
                planned_workout_id=args.workout_id,
                target_date=args.to,
                reason=args.reason,
            )
            print(json.dumps({"moved": str(moved.id), "workoutDate": str(moved.workout_date)}))
            return 0
        if args.command == "correct-2-nov":
            expected = (
                {uuid.UUID(item) for item in args.expect_ids.split(",") if item}
                if args.expect_ids
                else None
            )
            report = await correct_nov_2(session, commit=args.commit, expected_ids=expected)
            print(json.dumps(report, indent=2, default=str))
            return 0
        with open(args.report, encoding="utf-8") as handle:
            restored = await undo_nov_2(session, json.load(handle))
        print(json.dumps({"restored": restored}))
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
