#!/usr/bin/env python3
"""Read-only production health & invariant checker for the WC2026 prediction league.

Detects problems that error-tracking (Sentry) structurally cannot see — silent
domain-invariant breaks such as a finished match whose predictions never got
scored — plus liveness/readiness and the result-sync heartbeat.

Detection is **read-only**: HTTP GETs against the public health endpoints, plus
SELECT-only SQL via a read-only DB role (monitor_ro, behind RLS read policies).
No mutations, no admin token. Remediation lives in prod_remediate.py and runs
only on auto-heal of a safe op or on /approve.

All time arithmetic on DB values is done server-side via `now() AT TIME ZONE 'UTC'`
because the timestamp columns are timezone-naive UTC; this avoids naive/aware
mismatches and does not depend on the connection's session timezone (important
behind a transaction-mode pooler).

Designed to run both in GitHub Actions and locally. Configuration is via env:

  MONITOR_DATABASE_URL   read-only Postgres DSN (monitor_ro). Optional; DB checks
                         are skipped (with an info finding) if unset.
  PROD_API_BASE_URL      e.g. https://wc2026-api-production-a0f4.up.railway.app
  FOOTBALL_DATA_API_KEY  optional; enables an upstream-provider probe.

Output: a JSON report on stdout (findings + match-window context). Process exit
code is the max severity found: 0 = clean, 1 = warn, 2 = critical. Use --text for
a human-readable summary instead of JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

try:
    import asyncpg  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - surfaced as a finding at runtime
    asyncpg = None  # type: ignore[assignment]

# --- Thresholds (minutes) -------------------------------------------------------
# The sync loop writes an audit_log 'sync_triggered' row every 5 min, so a gap
# beyond ~12 min means the scheduler/loop is stalled.
SYNC_HEARTBEAT_WARN_MIN = 12
SYNC_HEARTBEAT_CRIT_MIN = 30
# A finished match should be scored within ~90 min play + sync lag. Give a buffer.
RESULT_LATE_CRIT_MIN = 240
# Failure-rate thresholds.
NOTIF_FAIL_WARN_COUNT = 20
PUSH_DISABLE_CRIT_PLAYERS = 10

SEVERITY_RANK = {"ok": 0, "info": 0, "warn": 1, "critical": 2}
HTTP_TIMEOUT = 15.0
DB_TIMEOUT = 20.0


@dataclass
class Finding:
    check_id: str
    severity: str  # ok | info | warn | critical
    incident_class: str  # infra | ops | code | config
    title: str
    detail: str
    suggested_action: str = ""
    matched_runbook: str = ""
    auto_healable: bool = False
    incident_key: str = ""  # stable key the workflow dedups issues on

    def __post_init__(self) -> None:
        if not self.incident_key:
            self.incident_key = self.check_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    """Render a DB timestamp (naive UTC or aware) as an ISO string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# --- HTTP checks ----------------------------------------------------------------
async def check_api(base_url: str) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    context: dict[str, Any] = {}
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        # Liveness
        try:
            r = await client.get(f"{base}/api/v1/health")
            if r.status_code == 200:
                context["sha"] = r.json().get("sha")
            else:
                findings.append(Finding(
                    check_id="api_liveness", severity="critical", incident_class="infra",
                    title=f"API liveness returned HTTP {r.status_code}",
                    detail=f"GET {base}/api/v1/health → {r.status_code}: {r.text[:200]}",
                    suggested_action="Check Railway deploy/logs; consider rollback to last healthy deploy.",
                    matched_runbook="docs/runbooks/deploys-ongoing.md", incident_key="api_down",
                ))
        except Exception as exc:  # noqa: BLE001 - any failure is a critical signal
            findings.append(Finding(
                check_id="api_liveness", severity="critical", incident_class="infra",
                title="API unreachable",
                detail=f"GET {base}/api/v1/health failed: {type(exc).__name__}: {exc}",
                suggested_action="Check Railway service status; the external uptime monitor should corroborate.",
                matched_runbook="docs/runbooks/deploys-ongoing.md", incident_key="api_down",
            ))

        # Readiness (DB reachability) — 503 if the DB is unreachable.
        try:
            r = await client.get(f"{base}/api/v1/health/ready")
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            context["db_ready"] = body.get("db")
            if r.status_code != 200 or body.get("db") != "ok":
                findings.append(Finding(
                    check_id="db_readiness", severity="critical", incident_class="infra",
                    title="Database not reachable from the API",
                    detail=f"GET {base}/api/v1/health/ready → {r.status_code}: {body or r.text[:200]}",
                    suggested_action="Check Supabase status/connection limits; do not deploy until DB recovers.",
                    matched_runbook="docs/runbooks/restore.md", incident_key="db_unreachable",
                ))
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding(
                check_id="db_readiness", severity="critical", incident_class="infra",
                title="Readiness probe unreachable",
                detail=f"GET {base}/api/v1/health/ready failed: {type(exc).__name__}: {exc}",
                suggested_action="API is likely down; check Railway.",
                matched_runbook="docs/runbooks/deploys-ongoing.md", incident_key="api_down",
            ))
    return findings, context


async def check_provider(api_key: str) -> list[Finding]:
    """Optional probe of the upstream result provider to disambiguate root cause."""
    url = "https://api.football-data.org/v4/competitions/WC/matches?status=FINISHED"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url, headers={"X-Auth-Token": api_key})
        if r.status_code == 200:
            return []
        sev = "warn" if r.status_code == 429 else "critical"
        return [Finding(
            check_id="provider_probe", severity=sev, incident_class="config",
            title=f"football-data.org returned HTTP {r.status_code}",
            detail=f"Upstream provider probe → {r.status_code}: {r.text[:160]}",
            suggested_action=("Rate-limited; sync will catch up." if r.status_code == 429
                              else "Verify/rotate FOOTBALL_DATA_API_KEY in Railway."),
            matched_runbook="docs/runbooks/auto-sync-broken.md", incident_key="provider_unhealthy",
        )]
    except Exception as exc:  # noqa: BLE001
        return [Finding(
            check_id="provider_probe", severity="warn", incident_class="config",
            title="Upstream result provider unreachable",
            detail=f"{type(exc).__name__}: {exc}",
            suggested_action="Transient network or provider outage; sync auto-retries every 5 min.",
            matched_runbook="docs/runbooks/auto-sync-broken.md", incident_key="provider_unhealthy",
        )]


# --- DB checks ------------------------------------------------------------------
# Single round-trip. All time windows are computed server-side against
# `now() AT TIME ZONE 'UTC'` so we never mix naive/aware datetimes in Python and
# never depend on the pooler session timezone.
_DB_QUERY = """
WITH n AS (SELECT (now() AT TIME ZONE 'UTC') AS utc)
SELECT
  (SELECT max(timestamp) FROM audit_log WHERE action_type='sync_triggered') AS last_sync,
  (SELECT EXTRACT(EPOCH FROM (n.utc - max(timestamp)))/60
     FROM audit_log WHERE action_type='sync_triggered') AS sync_gap_min,
  (SELECT count(*) FROM audit_log
     WHERE action_type='sync_failed' AND timestamp > n.utc - interval '90 minutes') AS sync_failed_90m,
  (SELECT count(*) FROM matches
     WHERE deleted_at IS NULL AND status NOT IN ('cancelled','postponed')
       AND kickoff_utc < n.utc - interval '150 minutes'
       AND (actual_home_score IS NULL OR actual_away_score IS NULL)) AS unresolved_count,
  (SELECT EXTRACT(EPOCH FROM (n.utc - min(kickoff_utc)))/60 FROM matches
     WHERE deleted_at IS NULL AND status NOT IN ('cancelled','postponed')
       AND kickoff_utc < n.utc - interval '150 minutes'
       AND (actual_home_score IS NULL OR actual_away_score IS NULL)) AS unresolved_oldest_min,
  (SELECT array_to_string((array_agg(DISTINCT match_number ORDER BY match_number))[1:10], ', ')
     FROM matches WHERE deleted_at IS NULL AND status NOT IN ('cancelled','postponed')
       AND kickoff_utc < n.utc - interval '150 minutes'
       AND (actual_home_score IS NULL OR actual_away_score IS NULL)) AS unresolved_sample,
  (SELECT count(*) FROM predictions p JOIN matches m ON m.id=p.match_id
     WHERE p.deleted_at IS NULL AND m.deleted_at IS NULL
       AND m.actual_home_score IS NOT NULL AND m.actual_away_score IS NOT NULL
       AND m.result_entered_at IS NOT NULL
       AND (p.points_awarded IS NULL OR p.points_breakdown IS NULL)) AS unscored_pred,
  (SELECT array_to_string((array_agg(DISTINCT m.match_number ORDER BY m.match_number))[1:10], ', ')
     FROM predictions p JOIN matches m ON m.id=p.match_id
     WHERE p.deleted_at IS NULL AND m.deleted_at IS NULL
       AND m.actual_home_score IS NOT NULL AND m.actual_away_score IS NOT NULL
       AND m.result_entered_at IS NOT NULL
       AND (p.points_awarded IS NULL OR p.points_breakdown IS NULL)) AS unscored_pred_sample,
  (SELECT count(*) FROM knockout_predictions kp JOIN matches m ON m.id=kp.match_id
     WHERE m.stage<>'group' AND m.deleted_at IS NULL
       AND m.actual_home_score IS NOT NULL AND m.actual_away_score IS NOT NULL
       AND m.result_entered_at IS NOT NULL AND kp.points_awarded IS NULL) AS unscored_ko,
  (SELECT array_to_string((array_agg(DISTINCT m.match_number ORDER BY m.match_number))[1:10], ', ')
     FROM knockout_predictions kp JOIN matches m ON m.id=kp.match_id
     WHERE m.stage<>'group' AND m.deleted_at IS NULL
       AND m.actual_home_score IS NOT NULL AND m.actual_away_score IS NOT NULL
       AND m.result_entered_at IS NOT NULL AND kp.points_awarded IS NULL) AS unscored_ko_sample,
  (SELECT max(result_entered_at) FROM matches
     WHERE result_entered_at > n.utc - interval '60 minutes') AS recent_result,
  (SELECT max(snapshot_at) FROM leaderboard_snapshots) AS last_snap,
  (SELECT count(*) FROM notification_log
     WHERE delivery_status='failed' AND sent_at > n.utc - interval '120 minutes') AS notif_failed,
  (SELECT count(DISTINCT player_id) FROM push_subscriptions
     WHERE is_active=false AND failed_send_count>=3
       AND last_used_at > n.utc - interval '60 minutes') AS push_players,
  (SELECT min(kickoff_utc) FROM matches WHERE kickoff_utc > n.utc
     AND deleted_at IS NULL AND status NOT IN ('cancelled','postponed')) AS next_kickoff,
  (SELECT count(*) FROM matches
     WHERE kickoff_utc::date = n.utc::date AND deleted_at IS NULL) AS matches_today,
  (SELECT count(*) FROM matches WHERE status='live' AND deleted_at IS NULL) AS matches_live
FROM n;
"""


async def _connect(dsn: str) -> "asyncpg.Connection":
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # monitor is read-only; avoid CA hassles in CI
    # statement_cache_size=0 is required behind a transaction-mode pooler (pgbouncer).
    return await asyncpg.connect(dsn=dsn, ssl=ctx, statement_cache_size=0,
                                 command_timeout=DB_TIMEOUT)


async def check_db(dsn: str) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    context: dict[str, Any] = {}
    if asyncpg is None:
        return [Finding(
            check_id="db_checks", severity="critical", incident_class="infra",
            title="asyncpg not installed", detail="Cannot run invariant SQL.",
            suggested_action="pip install asyncpg.", incident_key="monitor_broken",
        )], context

    try:
        conn = await _connect(dsn)
    except Exception as exc:  # noqa: BLE001
        return [Finding(
            check_id="db_connect", severity="critical", incident_class="infra",
            title="Monitor cannot reach the database",
            detail=f"{type(exc).__name__}: {exc}",
            suggested_action="Check MONITOR_DATABASE_URL / monitor_ro role / Supabase status.",
            matched_runbook="docs/runbooks/restore.md", incident_key="db_unreachable",
        )], context

    try:
        r = await conn.fetchrow(_DB_QUERY)
    finally:
        await conn.close()

    # Sync heartbeat
    context["last_sync_at"] = _iso(r["last_sync"])
    if r["last_sync"] is None:
        findings.append(Finding(
            check_id="sync_heartbeat", severity="warn", incident_class="ops",
            title="No sync heartbeat ever recorded",
            detail="audit_log has no 'sync_triggered' rows.",
            suggested_action="Confirm SCHEDULER_ENABLED=true and the scheduler started.",
            matched_runbook="docs/runbooks/auto-sync-broken.md",
            auto_healable=True, incident_key="sync_stalled",
        ))
    else:
        gap = float(r["sync_gap_min"])
        sev = ("critical" if gap >= SYNC_HEARTBEAT_CRIT_MIN
               else "warn" if gap >= SYNC_HEARTBEAT_WARN_MIN else "ok")
        if sev != "ok":
            findings.append(Finding(
                check_id="sync_heartbeat", severity=sev, incident_class="ops",
                title=f"Result-sync loop stalled (~{gap:.0f} min since last run)",
                detail=f"Last 'sync_triggered' at {_iso(r['last_sync'])}; expected every 5 min.",
                suggested_action="Re-trigger sync (POST /admin/sync/trigger). If still stalled, "
                                 "check Railway logs and the scheduler.",
                matched_runbook="docs/runbooks/auto-sync-broken.md",
                auto_healable=True, incident_key="sync_stalled",
            ))

    # Recent sync failures
    if r["sync_failed_90m"]:
        n = r["sync_failed_90m"]
        findings.append(Finding(
            check_id="sync_failures", severity="critical" if n >= 3 else "warn",
            incident_class="ops",
            title=f"{n} sync failure(s) in the last 90 min",
            detail=f"audit_log 'sync_failed' count (90 min) = {n}.",
            suggested_action="Re-trigger sync; if failures persist, verify FOOTBALL_DATA_API_KEY "
                             "and check for rate-limiting (429).",
            matched_runbook="docs/runbooks/auto-sync-broken.md",
            auto_healable=True, incident_key="sync_failing",
        ))

    # Inv-1: finished matches with no result entered
    if r["unresolved_count"]:
        oldest = float(r["unresolved_oldest_min"] or 0)
        findings.append(Finding(
            check_id="unresolved_finished_matches",
            severity="critical" if oldest >= RESULT_LATE_CRIT_MIN else "warn",
            incident_class="ops",
            title=f"{r['unresolved_count']} finished match(es) still missing a result",
            detail=f"Oldest ~{oldest:.0f} min past kickoff. Match #s: {r['unresolved_sample']}.",
            suggested_action="Re-trigger sync. If the provider has no result yet, enter it "
                             "manually (POST /admin/results/{id}) — needs your approval.",
            matched_runbook="docs/runbooks/auto-sync-broken.md",
            auto_healable=True, incident_key="unresolved_finished_matches",
        ))

    # Inv-3: predictions for scored matches that never got points (silent trigger miss)
    if r["unscored_pred"]:
        findings.append(Finding(
            check_id="unscored_predictions", severity="critical", incident_class="code",
            title=f"{r['unscored_pred']} prediction(s) unscored despite a final result",
            detail=f"Scored matches with NULL points — scoring trigger did not fully fire. "
                   f"Match #s: {r['unscored_pred_sample']}.",
            suggested_action="Force a recompute (PUT /admin/results/{id} with the same scores) — "
                             "needs approval. If it recurs, the scoring trigger has a bug; @claude.",
            auto_healable=False, incident_key="unscored_predictions",
        ))

    # Inv-4: knockout predictions unscored
    if r["unscored_ko"]:
        findings.append(Finding(
            check_id="unscored_knockout", severity="critical", incident_class="code",
            title=f"{r['unscored_ko']} knockout pick(s) unscored despite a final result",
            detail=f"Knockout matches with NULL winner points. Match #s: {r['unscored_ko_sample']}.",
            suggested_action="Force a recompute (needs approval). If it recurs, @claude — trigger bug.",
            auto_healable=False, incident_key="unscored_knockout",
        ))

    # Inv-5: leaderboard snapshot did not advance after a recent result
    if r["recent_result"] is not None:
        last_snap = _as_aware(r["last_snap"])
        recent_result = _as_aware(r["recent_result"])
        if last_snap is None or last_snap < recent_result - timedelta(seconds=30):
            findings.append(Finding(
                check_id="leaderboard_stale", severity="warn", incident_class="code",
                title="Leaderboard snapshot did not advance after a result",
                detail=f"Latest result_entered_at={_iso(r['recent_result'])}, "
                       f"latest snapshot_at={_iso(r['last_snap'])}.",
                suggested_action="Usually paired with unscored_predictions; force a recompute.",
                auto_healable=False, incident_key="leaderboard_stale",
            ))

    # Inv-6: notification delivery failures
    if r["notif_failed"] and r["notif_failed"] >= NOTIF_FAIL_WARN_COUNT:
        findings.append(Finding(
            check_id="notification_failures", severity="warn", incident_class="ops",
            title=f"{r['notif_failed']} failed push deliveries in the last 120 min",
            detail="Elevated push failure rate.",
            suggested_action="Often expired subscriptions (self-healing). If paired with mass disable, "
                             "check VAPID keys.",
            auto_healable=False, incident_key="notification_failures",
        ))

    # Inv-7: mass push-subscription auto-disable (possible VAPID/key issue)
    if r["push_players"] and r["push_players"] >= PUSH_DISABLE_CRIT_PLAYERS:
        findings.append(Finding(
            check_id="push_mass_disable", severity="critical", incident_class="config",
            title=f"{r['push_players']} players' push subs auto-disabled in 60 min",
            detail="Widespread push failure — likely a VAPID key/config problem, not per-device.",
            suggested_action="Verify VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY in Railway match the "
                             "frontend's VITE_VAPID_PUBLIC_KEY — needs approval to change.",
            matched_runbook="docs/runbooks/env-manifest.md",
            auto_healable=False, incident_key="push_mass_disable",
        ))

    # Match-window context (cadence + safe-deploy annotation)
    nk = _as_aware(r["next_kickoff"])
    context["next_kickoff_utc"] = _iso(r["next_kickoff"])
    context["matches_today"] = r["matches_today"]
    context["matches_live"] = r["matches_live"]
    in_window = bool(r["matches_live"])
    if nk is not None and timedelta(0) <= (nk - _now()) <= timedelta(minutes=30):
        in_window = True
    context["in_match_window"] = in_window
    return findings, context


# --- Orchestration --------------------------------------------------------------
async def run(base_url: str | None, db_url: str | None, provider_key: str | None) -> dict[str, Any]:
    findings: list[Finding] = []
    context: dict[str, Any] = {}

    tasks = []
    if base_url:
        tasks.append(check_api(base_url))
    else:
        findings.append(Finding(
            check_id="config", severity="info", incident_class="infra",
            title="PROD_API_BASE_URL not set", detail="Skipped HTTP health checks."))
    if db_url:
        tasks.append(check_db(db_url))
    else:
        findings.append(Finding(
            check_id="config", severity="info", incident_class="infra",
            title="MONITOR_DATABASE_URL not set", detail="Skipped DB invariant checks."))

    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(result, BaseException):
            findings.append(Finding(
                check_id="monitor_error", severity="critical", incident_class="infra",
                title="Healthcheck raised an exception",
                detail=f"{type(result).__name__}: {result}", incident_key="monitor_broken"))
            continue
        f, c = result
        findings.extend(f)
        context.update(c)

    if provider_key:
        findings.extend(await check_provider(provider_key))

    overall = max((SEVERITY_RANK[f.severity] for f in findings), default=0)
    actionable = [f for f in findings if SEVERITY_RANK[f.severity] >= 1]
    return {
        "generated_at": _now().isoformat(),
        "overall_severity": {0: "ok", 1: "warn", 2: "critical"}[overall],
        "overall_rank": overall,
        "actionable_count": len(actionable),
        "context": context,
        "findings": [asdict(f) for f in findings],
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Prod healthcheck @ {report['generated_at']}",
        f"Overall: {report['overall_severity'].upper()}  ({report['actionable_count']} actionable)",
        f"Context: {json.dumps(report['context'])}",
        "",
    ]
    if not report["findings"]:
        lines.append("  (no findings)")
    for f in report["findings"]:
        lines.append(f"  [{f['severity'].upper():8}] {f['check_id']}: {f['title']}")
        if f["detail"]:
            lines.append(f"            {f['detail']}")
        if SEVERITY_RANK[f["severity"]] >= 1 and f["suggested_action"]:
            lines.append(f"            → {f['suggested_action']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only prod healthcheck for WC2026.")
    ap.add_argument("--text", action="store_true", help="Human-readable output instead of JSON.")
    ap.add_argument("--base-url", default=os.environ.get("PROD_API_BASE_URL"))
    ap.add_argument("--db-url", default=os.environ.get("MONITOR_DATABASE_URL"))
    args = ap.parse_args()

    provider_key = os.environ.get("FOOTBALL_DATA_API_KEY") or None
    report = asyncio.run(run(args.base_url, args.db_url, provider_key))

    print(render_text(report) if args.text else json.dumps(report, indent=2))
    return report["overall_rank"]


if __name__ == "__main__":
    sys.exit(main())
