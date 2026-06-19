#!/usr/bin/env python3
"""GitHub-side orchestration for the WC2026 prod monitor (runs in GitHub Actions).

Two subcommands, both invoked each scheduled run:

  chatops  Execute owner slash-commands posted on open monitor issues from a phone
           (/sync, /backup, /status, /enter-result ..., /resolve) and reply with the
           result. This is the mobile approval surface for operational actions.

  scan     Run the healthcheck; auto-heal a stalled sync; then open / update / close
           deduped, diagnosed issues (assigned + @mentioning the owner so GitHub
           mobile pushes a notification); hand code-class incidents to @claude; and
           refresh the daily digest issue.

All GitHub side effects go through the `gh` CLI (present on GitHub runners). Use
--dry-run to print intended mutating calls instead of executing them, so the logic
can be rehearsed against a real or synthetic report locally.

Env: GH_TOKEN, GITHUB_REPOSITORY (owner/repo), OWNER_LOGIN (default: repo owner),
plus prod_healthcheck.py / prod_remediate.py env for the actions they perform.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = os.environ.get("GITHUB_REPOSITORY", "")
OWNER = os.environ.get("OWNER_LOGIN") or (REPO.split("/")[0] if REPO else "")
DRY = False

LABELS = {
    "prod-monitor": "5319e7",
    "severity:critical": "b60205",
    "severity:warn": "fbca04",
    "class:ops": "0e8a16",
    "class:code": "1d76db",
    "class:infra": "5319e7",
    "class:config": "c5def5",
    "auto-fix": "d93f0b",
    "monitor-digest": "bfdadc",
}
PY = sys.executable


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --- subprocess helpers ---------------------------------------------------------
def gh_read(args: list[str]) -> str:
    """Read-only gh call (always executed, even in dry-run)."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def gh_write(args: list[str], body: str | None = None) -> str:
    """Mutating gh call. In dry-run, prints instead of executing."""
    if DRY:
        shown = " ".join(args)
        print(f"  [dry-run gh] {shown}" + (f"\n    body<<<\n{body}\n    >>>" if body else ""))
        return ""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def run_script(script: str, args: list[str]) -> dict:
    """Run prod_healthcheck.py / prod_remediate.py and parse its JSON stdout."""
    if DRY and script == "prod_remediate.py":
        print(f"  [dry-run remediate] {' '.join(args)}")
        return {"ok": True, "dry_run": True}
    proc = subprocess.run([PY, str(HERE / script), *args], capture_output=True, text=True)
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": f"non-JSON output (rc={proc.returncode})",
                "stdout": proc.stdout[-500:], "stderr": proc.stderr[-500:]}


def healthcheck() -> dict:
    return run_script("prod_healthcheck.py", [])


def remediate(args: list[str]) -> dict:
    return run_script("prod_remediate.py", args)


# --- issue helpers --------------------------------------------------------------
TITLE_RE = re.compile(r"^\[monitor\]\s+([a-z0-9_]+):")


def ensure_labels() -> None:
    for name, color in LABELS.items():
        try:
            gh_write(["label", "create", name, "--color", color, "--force"])
        except subprocess.CalledProcessError:
            pass  # label management is best-effort


def open_monitor_issues() -> list[dict]:
    out = gh_read(["issue", "list", "--label", "prod-monitor", "--state", "open",
                   "--json", "number,title,body,labels", "--limit", "100"])
    return json.loads(out or "[]")


def issue_key(issue: dict) -> str | None:
    m = TITLE_RE.match(issue.get("title", ""))
    return m.group(1) if m else None


def comments(number: int) -> list[dict]:
    out = gh_read(["api", f"repos/{REPO}/issues/{number}/comments", "--paginate",
                   "--jq", "[.[] | {id, body, assoc: .author_association, login: .user.login}]"])
    return json.loads(out or "[]")


def safe_deploy_note(ctx: dict) -> str:
    if ctx.get("in_match_window"):
        return ("> ⚠️ **A match window is active** — avoid merging/deploying now "
                "(kickoff-freeze rule). Wait for the lull between matches.")
    nk = ctx.get("next_kickoff_utc")
    return (f"> Next kickoff: `{nk}` UTC. Safe to merge/deploy until ~30 min before it."
            if nk else "> No upcoming kickoff on record — safe to deploy.")


# --- scan -----------------------------------------------------------------------
TEST_REPORT = {
    "generated_at": "synthetic", "overall_severity": "warn", "overall_rank": 1, "actionable_count": 1,
    "context": {"sha": "test", "db_ready": "ok", "last_sync_at": "n/a",
                "next_kickoff_utc": None, "matches_today": 0, "matches_live": 0, "in_match_window": False},
    "findings": [{"check_id": "sync_heartbeat", "severity": "warn", "incident_class": "ops",
                  "title": "Result-sync loop stalled (SYNTHETIC TEST)",
                  "detail": "Forced test incident to verify the phone push + ChatOps. Reply /resolve to close.",
                  "suggested_action": "This is only a test — no real issue.",
                  "matched_runbook": "docs/runbooks/auto-sync-broken.md",
                  "auto_healable": False, "incident_key": "synthetic_test"}],
}


def build_issue_body(f: dict, ctx: dict) -> str:
    lines = [
        f"**{f['title']}**",
        "",
        f"- Severity: `{f['severity']}`  ·  Class: `{f['incident_class']}`  ·  Check: `{f['check_id']}`",
        f"- Detail: {f['detail']}",
    ]
    if f.get("matched_runbook"):
        lines.append(f"- Runbook: [`{f['matched_runbook']}`]({f['matched_runbook']})")
    if f.get("suggested_action"):
        lines.append(f"- Suggested fix: {f['suggested_action']}")
    lines += ["", safe_deploy_note(ctx), ""]
    if f["incident_class"] == "code":
        lines += ["**@claude** — please investigate this and open a **draft PR** with a fix. "
                  "Cite the relevant code path and keep the change minimal.", ""]
    lines += [
        "---",
        "**Reply from your phone to act:**",
        "- `/sync` — re-run the result sync · `/backup` — snapshot the DB · `/status` — sync status",
        "- `/enter-result <match_id> <home>-<away> [et] [pens] [winner=<team_uuid>]` — manual result",
        "- `/resolve` — close this issue",
        "",
        f"<sub>cc @{OWNER} · prod-monitor · {_now_iso()}</sub>",
    ]
    return "\n".join(lines)


def labels_for(f: dict) -> list[str]:
    out = ["prod-monitor", f"severity:{f['severity']}", f"class:{f['incident_class']}"]
    if f["incident_class"] == "code":
        out.append("auto-fix")
    return out


def actionable(report: dict) -> list[dict]:
    return [f for f in report["findings"] if f["severity"] in ("warn", "critical")]


def cmd_scan(report_path: str | None, test_incident: bool = False) -> int:
    ensure_labels()
    if test_incident:
        report = TEST_REPORT
    elif report_path:
        report = json.loads(Path(report_path).read_text())
    else:
        report = healthcheck()
    ctx = report.get("context", {})
    acts = actionable(report)
    healed: list[str] = []

    # Auto-heal: the only safe, idempotent op is re-running the result sync.
    if any(f.get("auto_healable") for f in acts):
        print("auto-heal: re-triggering result sync")
        remediate(["sync-trigger"])
        report = healthcheck() if not DRY else report  # re-check after heal
        ctx = report.get("context", ctx)
        new_keys = {f["incident_key"] for f in actionable(report)}
        healed = [f["incident_key"] for f in acts if f["incident_key"] not in new_keys]
        acts = actionable(report)

    existing = {issue_key(i): i for i in open_monitor_issues() if issue_key(i)}
    current_keys = {f["incident_key"] for f in acts}

    # Open / update issues for current incidents.
    for f in acts:
        key = f["incident_key"]
        title = f"[monitor] {key}: {f['title']}"[:240]
        if key in existing:
            num = existing[key]["number"]
            have = {lb["name"] for lb in existing[key].get("labels", [])}
            want = set(labels_for(f))
            if want - have:
                gh_write(["issue", "edit", str(num), *sum((["--add-label", l] for l in want - have), [])])
            # Re-notify only on escalation to critical (keep noise low otherwise).
            if f["severity"] == "critical" and "severity:critical" not in have:
                gh_write(["issue", "comment", str(num), "--body",
                          f"⏫ Escalated to **critical** at {_now_iso()}. {f['detail']}"])
        else:
            body = build_issue_body(f, ctx)
            gh_write(["issue", "create", "--title", title, "--assignee", OWNER,
                      *sum((["--label", l] for l in labels_for(f)), []),
                      "--body", body], body=body)

    # Auto-close incidents that have cleared (including auto-healed ones).
    for key, issue in existing.items():
        if key not in current_keys:
            reason = "auto-healed ✅" if key in healed else "cleared ✅"
            gh_write(["issue", "close", str(issue["number"]), "--reason", "completed",
                      "--comment", f"{reason} — no longer detected as of {_now_iso()}."])

    update_digest(report, healed)
    print(f"scan done: {len(acts)} actionable, {len(healed)} healed, "
          f"{len(current_keys - set(existing))} new incident(s)")
    return 0


def update_digest(report: dict, healed: list[str]) -> None:
    ctx = report.get("context", {})
    overall = report["overall_severity"].upper()
    icon = {"OK": "🟢", "WARN": "🟡", "CRITICAL": "🔴"}.get(overall, "⚪")
    body = "\n".join([
        f"# {icon} Prod monitor — daily digest",
        "",
        f"- Last check: **{_now_iso()}** · Overall: **{overall}**",
        f"- Result-sync last seen: `{ctx.get('last_sync_at')}`",
        f"- Next kickoff: `{ctx.get('next_kickoff_utc')}` · matches today: {ctx.get('matches_today')} "
        f"· live now: {ctx.get('matches_live')}",
        f"- Auto-heals this run: {', '.join(healed) if healed else 'none'}",
        f"- API SHA: `{ctx.get('sha')}`",
        "",
        "_Updated every run. Open incidents appear as separate issues that @mention you._",
    ])
    found = json.loads(gh_read(["issue", "list", "--label", "monitor-digest", "--state", "open",
                                "--json", "number", "--limit", "1"]) or "[]")
    if found:
        num = found[0]["number"]
        gh_write(["issue", "edit", str(num), "--body", body], body=body)
    else:
        gh_write(["issue", "create", "--title", "[monitor] Daily digest", "--label", "prod-monitor",
                  "--label", "monitor-digest", "--body", body], body=body)
        found = json.loads(gh_read(["issue", "list", "--label", "monitor-digest", "--state", "open",
                                    "--json", "number", "--limit", "1"]) or "[]")
    # One heartbeat comment per day, so a healthy weekend still pings once daily.
    if found:
        num = found[0]["number"]
        marker = f"digest-day:{_today()}"
        if marker not in "\n".join(c["body"] for c in comments(num)):
            gh_write(["issue", "comment", str(num), "--body",
                      f"{icon} {overall} as of {_now_iso()}. <!-- {marker} -->"])


# --- chatops --------------------------------------------------------------------
# A command may sit at the start of the body or after any whitespace/newline, so
# "ok /sync please" works as well as a command on its own line.
CMD_RE = re.compile(r"(?:^|\s)/(sync|backup|status|resolve|close)\b")
ENTER_RE = re.compile(r"(?:^|\s)/enter-result\s+(\S+)\s+(\d+)-(\d+)([^\n]*)")


def parse_command(body: str) -> list[str] | str | None:
    """Return remediate args, or 'resolve', or None."""
    m = ENTER_RE.search(body)
    if m:
        mid, home, away, rest = m.groups()
        args = ["enter-result", "--match-id", mid, "--home", home, "--away", away]
        if "et" in rest:
            args.append("--extra-time")
        if "pens" in rest:
            args.append("--penalties")
        win = re.search(r"winner=(\S+)", rest)
        if win:
            args += ["--penalty-winner", win.group(1)]
        return args
    m = CMD_RE.search(body)
    if not m:
        return None
    cmd = m.group(1)
    if cmd in ("resolve", "close"):
        return "resolve"
    return {"sync": ["sync-trigger"], "backup": ["backup"], "status": ["status"]}[cmd]


def cmd_chatops() -> int:
    issues = open_monitor_issues()
    handled = 0
    for issue in issues:
        num = issue["number"]
        cmts = comments(num)
        acked = set(re.findall(r"ack:(\d+)", "\n".join(c["body"] for c in cmts)))
        for c in cmts:
            if c["assoc"] != "OWNER" or str(c["id"]) in acked:
                continue
            parsed = parse_command(c["body"])
            if parsed is None:
                continue
            handled += 1
            if parsed == "resolve":
                gh_write(["issue", "close", str(num), "--reason", "completed",
                          "--comment", f"Closed by @{c['login']}. <!-- ack:{c['id']} -->"])
                break
            print(f"chatops: issue #{num} running {parsed}")
            result = remediate(parsed)
            ok = result.get("ok")
            summary = json.dumps(result.get("response", result))[:600]
            gh_write(["issue", "comment", str(num), "--body",
                      f"{'✅' if ok else '❌'} ran `/{parsed[0]}` (requested by @{c['login']}):\n"
                      f"```json\n{summary}\n```\n<!-- ack:{c['id']} -->"])
    print(f"chatops done: {handled} command(s) handled")
    return 0


def main() -> int:
    global DRY
    ap = argparse.ArgumentParser(description="GitHub orchestration for the WC2026 prod monitor.")
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--report", default=None, help="Path to a report.json (else runs healthcheck).")
    s.add_argument("--test-incident", action="store_true",
                   help="Use a built-in synthetic incident (to verify the push/ChatOps).")
    sub.add_parser("chatops")
    args = ap.parse_args()
    DRY = args.dry_run

    if not REPO:
        print("GITHUB_REPOSITORY not set", file=sys.stderr)
        return 2
    return cmd_scan(args.report, args.test_incident) if args.cmd == "scan" else cmd_chatops()


if __name__ == "__main__":
    sys.exit(main())
