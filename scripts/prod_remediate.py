#!/usr/bin/env python3
"""Token-gated remediation actions for the WC2026 prod monitor.

Mints a short-lived admin JWT (HS256, mirroring src.auth.create_access_token —
claims sub/role/iat/exp, signed with JWT_ACCESS_SECRET) and calls the admin API.
Admin authority is enforced server-side by site_role==superadmin on the profile
identified by `sub`, so MONITOR_ADMIN_PLAYER_ID must be the superadmin's UUID.

Actions
  sync-trigger    POST /api/v1/admin/sync/trigger  — idempotent auto-heal. SAFE,
                  runs without approval (re-runs the result sync; no-op if nothing new).
  backup          POST /api/v1/admin/backup        — snapshot before a riskier op.
  status          GET  /api/v1/admin/sync/status   — read-only confirmation.
  enter-result    POST (or PUT on 409) /api/v1/admin/results/{id} — APPROVED manual
                  result entry. The score is human-supplied (Craig's /approve), never
                  guessed. Used when the provider will not resolve a finished match.

Note: there is deliberately no "force re-score" action. The scoring trigger fires
only on a NULL->non-NULL score transition, so a match that is scored-but-unscored
(Inv-3/4) is a code/data bug, not an idempotent ops fix — those escalate to @claude.

Env: PROD_API_BASE_URL, JWT_ACCESS_SECRET, MONITOR_ADMIN_PLAYER_ID.
Exit 0 on success, 2 on failure. --dry-run prints the intended call without sending.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

try:
    import jwt  # PyJWT
except ModuleNotFoundError:  # pragma: no cover
    jwt = None  # type: ignore[assignment]

TOKEN_TTL_SECONDS = 3600  # short-lived; minted per invocation
HTTP_TIMEOUT = 60.0  # sync_results() can take a while server-side


class RemediationError(RuntimeError):
    pass


def mint_admin_token() -> str:
    if jwt is None:
        raise RemediationError("PyJWT not installed (pip install pyjwt).")
    secret = os.environ.get("JWT_ACCESS_SECRET")
    player_id = os.environ.get("MONITOR_ADMIN_PLAYER_ID")
    if not secret or not player_id:
        raise RemediationError("JWT_ACCESS_SECRET and MONITOR_ADMIN_PLAYER_ID are required.")
    now = int(time.time())
    payload = {"sub": player_id, "role": "admin", "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, secret, algorithm="HS256")


def _base_url() -> str:
    base = os.environ.get("PROD_API_BASE_URL")
    if not base:
        raise RemediationError("PROD_API_BASE_URL is required.")
    return base.rstrip("/")


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=_base_url(),
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    )


def _result(action: str, resp: httpx.Response) -> dict:
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text[:500]}
    return {"action": action, "ok": resp.is_success, "status_code": resp.status_code, "response": body}


def do_sync_trigger(token: str) -> dict:
    with _client(token) as c:
        return _result("sync-trigger", c.post("/api/v1/admin/sync/trigger"))


def do_backup(token: str) -> dict:
    with _client(token) as c:
        return _result("backup", c.post("/api/v1/admin/backup"))


def do_status(token: str) -> dict:
    with _client(token) as c:
        return _result("status", c.get("/api/v1/admin/sync/status"))


def do_enter_result(token: str, args: argparse.Namespace) -> dict:
    body = {
        "actual_home_score": args.home,
        "actual_away_score": args.away,
        "extra_time": bool(args.extra_time),
        "penalties": bool(args.penalties),
        "penalty_winner_id": args.penalty_winner,
    }
    path = f"/api/v1/admin/results/{args.match_id}"
    with _client(token) as c:
        resp = c.post(path, json=body)
        # 409 => a result already exists; override it instead (PUT).
        if resp.status_code == 409:
            resp = c.put(path, json=body)
        return _result("enter-result", resp)


def main() -> int:
    ap = argparse.ArgumentParser(description="Token-gated prod remediation for WC2026.")
    ap.add_argument("--dry-run", action="store_true", help="Print the intended action; do not call.")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("sync-trigger", help="Re-run the result sync (safe auto-heal).")
    sub.add_parser("backup", help="Take a manual DB backup.")
    sub.add_parser("status", help="Fetch sync status (read-only).")
    er = sub.add_parser("enter-result", help="Approved manual result entry.")
    er.add_argument("--match-id", required=True)
    er.add_argument("--home", type=int, required=True)
    er.add_argument("--away", type=int, required=True)
    er.add_argument("--extra-time", action="store_true")
    er.add_argument("--penalties", action="store_true")
    er.add_argument("--penalty-winner", default=None, help="Team UUID (knockout pen. shootout winner).")
    args = ap.parse_args()

    if args.dry_run:
        print(json.dumps({"action": args.action, "dry_run": True, "args": vars(args)}, indent=2))
        return 0

    try:
        token = mint_admin_token()
        if args.action == "sync-trigger":
            out = do_sync_trigger(token)
        elif args.action == "backup":
            out = do_backup(token)
        elif args.action == "status":
            out = do_status(token)
        elif args.action == "enter-result":
            out = do_enter_result(token, args)
        else:  # pragma: no cover - argparse enforces choices
            raise RemediationError(f"unknown action {args.action}")
    except RemediationError as exc:
        print(json.dumps({"action": getattr(args, "action", None), "ok": False, "error": str(exc)}))
        return 2

    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
