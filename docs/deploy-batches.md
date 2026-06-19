# Deployment & Real-World Testing Batches

Same idea as `phase-batches.md`, but for the work between "all 59 phases shipped" and "tournament kicks off on 11 June 2026". Each row is one focused session of work.

## How to use this file

`/next-batch-prompt` and `/strike-batch` **do not work here** — they're hard-coded to `phase-batches.md` + `wc2026-architecture.md`. Instead:

- **To start the next batch:** open the first un-struck row below and paste the "Session prompt" block into a fresh session.
- **To mark a batch shipped:** edit this file by hand — wrap the batch row's number, owner, and scope cells in `~~...~~` and replace the Status cell with `✅ Shipped YYYY-MM-DD`.

## Status

All 59 implementation phases shipped 2026-05-17. Tournament starts 11 June 2026 — 25-day buffer.

## Batches

| # | Owner | Scope | Status |
|---|---|---|---|
| ~~D1~~ | ~~me~~ | ~~Pre-deploy polish~~ | ✅ Shipped 2026-05-17 |
| ~~D2~~ | ~~you+me~~ | ~~Provision staging~~ | ✅ Shipped 2026-05-17 |
| D3 | both | Staging soak | Pending |
| ~~D4~~ | ~~you+me~~ | ~~Provision production~~ | ✅ Shipped 2026-05-18 |
| D5 | both | Production soak + open invites | Pending |
| D6 | me | Tournament-day runbook + alerts | Pending |

---

### D1 — Pre-deploy polish

**Owner:** me · no infra credentials needed · ~30 min

**Goals:**
- Tighten local mypy config to match CI (CI has `redundant-cast` enabled, local was looser; bit us once on `bootstrap_admin.py`)
- Add `apps/web/vercel.json` with explicit SPA rewrites so the deployment config lives in the repo rather than Vercel's UI
- Optionally add `apps/api/nixpacks.toml` pinning `postgresql-client` in the Railway image (pre-empts the `pg_dump` backup risk flagged in `deploy.md`'s "Common failure modes" table) — **superseded:** Railway now builds the repo-root `Dockerfile` (not Nixpacks), which `apt-get install`s `postgresql-client` directly; no `nixpacks.toml` exists or is needed

**Session prompt:**
```
Run Batch D1 from docs/deploy-batches.md — pre-deploy polish.
Tighten local mypy to match CI; add apps/web/vercel.json with SPA
rewrites; decide whether to add apps/api/nixpacks.toml.
Commit on a chore/ branch, push, wait for CI, ff-merge to main,
then strike the D1 row.
```

---

### D2 — Provision staging

**Owner:** you (run the commands) + me (alongside to debug) · ~1–2 hours

**Goals:**
- Walk `docs/runbooks/deploy.md` Steps 1–10 end-to-end against fresh Supabase + Railway + Vercel **staging** projects
- Amend the runbook in real-time wherever it's wrong, vague, or missing a step
- Confirm `/api/v1/health/ready` returns `db: ok`, login works, push notification "Send test" delivers to a real device

**Session prompt:**
```
Run Batch D2 from docs/deploy-batches.md — provision staging.
Follow docs/runbooks/deploy.md Steps 1–10 end-to-end against
new staging projects. I'll run the CLI/dashboard commands; you
watch for runbook gaps, debug failures, and amend the runbook
as we go. Goal at end of session: green smoke test on staging.
```

---

### D3 — Staging soak

**Owner:** both — you exercise the deployed app, I fix bugs · iterative, may span multiple sessions

**Goals:**
- Solo walk-through of every feature on the staging URL (predictions, knockout picks, specials, bracket, leaderboard, profile, compare)
- Invite 1–2 trusted friends with a real invite link; gather feedback
- Verify in real conditions (not unit tests):
  - Push notifications arrive on iOS + Android home-screen PWA
  - Offline → online resync of queued predictions
  - Auto-sync against football-data.org (no live WC matches yet, expect `last_sync_action: no_changes`)
  - First 03:00 UTC daily backup completes successfully
- Track surfaced bugs in a `staging-bugs.md` scratchpad or just close-out tickets; fix and redeploy iteratively

**Session prompt:**
```
Run a slice of Batch D3 from docs/deploy-batches.md — staging soak.
Here are the bugs/feedback I gathered since the last session:
- <paste bug list>
Fix what's actionable; redeploy to staging; we'll re-soak.
```

---

### D4 — Provision production

**Owner:** you + me · ~1 hour (faster than D2 because the runbook should be polished)

**Goals:**
- Repeat Steps 1–10 of `deploy.md` against **separate** Supabase, Railway, and Vercel **production** projects
- **Generate fresh VAPID keys** for prod — staging keys must not leak across (cite "Common failure modes" in deploy.md)
- Use `bootstrap_admin` directly (no manual SQL)
- Wire Sentry DSNs (Step 9 in the runbook) — prod gets observability that staging didn't necessarily need

**Session prompt:**
```
Run Batch D4 from docs/deploy-batches.md — provision production.
Follow the (now-amended) docs/runbooks/deploy.md Steps 1–10 against
brand-new prod projects with fresh VAPID keys + Sentry DSNs. Goal:
green smoke test on the prod URL.
```

---

### D5 — Production soak + open invites

**Owner:** both — you operate, I fix · 3–7 days elapsed, may span several short sessions

**Goals:**
- ~3 days of solo + 1-friend soak on prod before opening up
- Monitor Sentry + Railway logs daily
- Once stable, issue invite links to the full 15 players via WhatsApp/email
- Be on standby to fix bugs that surface as the player base grows

**Session prompt:**
```
Run a slice of Batch D5 from docs/deploy-batches.md — prod soak / invites.
Since the last session:
- <paste status: how many players joined, what they reported, any
  Sentry alerts, any backup or sync errors>
Triage and fix; redeploy if needed.
```

---

### D6 — Tournament-day runbook + alerts

**Owner:** me · ~1 session · do this **before opening invites in D5**, ideally right after D4

**Goals:**
- Write `docs/runbooks/tournament-day.md` covering:
  - Pre-kickoff checklist (scheduler running, last backup OK, football-data.org quota healthy)
  - What to check when push notifications don't arrive
  - What to check when a result doesn't appear after FT
  - When to invoke `restore.md` / `cancelled-match.md` / `kickoff-change.md` / `pin-reset.md` / `auto-sync-broken.md`
- Wire Sentry alerts → email/Slack so you don't have to log-poll during matches
- Verify the `/admin/sync` UI's "Sync Now" button works end-to-end on prod

**Session prompt:**
```
Run Batch D6 from docs/deploy-batches.md — tournament-day readiness.
Write docs/runbooks/tournament-day.md and wire Sentry alerts.
Verify on the prod URL.
```
