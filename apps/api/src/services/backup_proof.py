"""Read the public result of the real off-platform drill, never a scheduler skip."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

WORKFLOW = "backup-restore.yml"
REPOSITORY = "CraigR973/garmin-coach"
MAX_PROOF_AGE = timedelta(days=8)


def proof_counters(runs: list[dict[str, Any]], *, now: datetime) -> dict[str, int]:
    eligible = [
        r
        for r in runs
        if r.get("head_branch") == "main"
        and r.get("event") in {"schedule", "workflow_dispatch"}
        and r.get("head_repository", {}).get("full_name", "").lower() == REPOSITORY.lower()
    ]
    completed = [r for r in eligible if r.get("status") == "completed"]
    if not completed:
        raise RuntimeError("backup_restore_proof_missing")
    newest = max(completed, key=lambda r: r["run_number"])
    if newest.get("conclusion") != "success":
        raise RuntimeError("backup_restore_latest_run_failed")
    finished = datetime.fromisoformat(newest["updated_at"].replace("Z", "+00:00"))
    # created_at, not updated_at: rerunning an ancient archive check must not extend proof.
    started = datetime.fromisoformat(newest["created_at"].replace("Z", "+00:00"))
    age = now - started
    if not timedelta(0) <= age <= MAX_PROOF_AGE or finished > now:
        raise RuntimeError("backup_restore_proof_stale_or_future")
    return {
        "verified_run_id": int(newest["id"]),
        "proof_age_seconds": int(age.total_seconds()),
        "proof_started_epoch": int(started.timestamp()),
    }


async def check_offsite_proof() -> dict[str, int]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs",
            params={"branch": "main", "per_page": 30},
            headers={"Accept": "application/vnd.github+json"},
        )
        if not response.is_success:
            raise RuntimeError("backup_restore_proof_unavailable")
        runs = response.json()["workflow_runs"]
    return proof_counters(runs, now=datetime.now(UTC))
