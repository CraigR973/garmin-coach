# Runbook — Proactive prod monitor (away-from-keyboard coverage)

A three-layer system that finds, diagnoses, and (where safe) fixes production
issues, and reaches you on your **phone** for one-tap approval of anything riskier —
without needing your laptop on. Built for the WC opening weekend (first live test of
the result-sync → scoring → leaderboard → notifications pipeline).

## Architecture

| Layer | Runs on | Does | Depends on |
|---|---|---|---|
| **0 — Paging floor** | UptimeRobot/Better Stack + Sentry | Pages your phone if the API/DB is down or errors spike. Bulletproof, independent of everything below. | external dashboards |
| **1 — Smart monitor** | GitHub Actions cron (`prod-monitor.yml`, ~15 min) | Read-only invariant checks Sentry can't see; auto-heals a stalled sync; opens diagnosed issues that @mention you. | repo secrets |
| **2 — Auto-fix** | `claude.yml` | On `@claude`, drafts a fix **PR** for one-tap mobile merge. Nothing deploys without your merge. | `ANTHROPIC_API_KEY` |

Merging a PR to `main` **auto-deploys prod** (Railway + Vercel), so approval-on-mobile = deploy. No laptop needed.

## What Layer 1 checks (`scripts/prod_healthcheck.py`, read-only)

- **API liveness / DB readiness** — `GET /api/v1/health` and `/api/v1/health/ready` (503 = DB down).
- **Sync heartbeat** — `audit_log` gets a `sync_triggered` row every 5 min; a >12 min gap = stalled (auto-healable). `sync_failed` rows in the last 90 min.
- **Inv-1** finished matches with no result entered (provider/sync lag) — *auto-healable* (re-trigger sync).
- **Inv-3 / Inv-4** predictions / knockout picks still unscored despite a final result — a **scoring-trigger bug** (→ `@claude`, needs a code fix; not auto-healable).
- **Inv-5** leaderboard snapshot didn't advance after a result.
- **Inv-6 / Inv-7** push delivery failures / mass subscription auto-disable (possible VAPID/key problem).

## How you interact (all from your phone)

1. **Notification** → GitHub mobile push (the issue is assigned to you and @mentions you). Install the GitHub app and enable notifications.
2. **Operational fix** → reply on the issue with a slash-command (you must be the repo OWNER):
   - `/sync` — re-run the result sync (safe; this is also auto-tried)
   - `/backup` — take a DB snapshot
   - `/status` — fetch sync status
   - `/enter-result <match_id> <home>-<away> [et] [pens] [winner=<team_uuid>]` — manual result entry
   - `/resolve` — close the issue
   The next monitor run (≤15 min) executes it and replies with the result.
3. **Code fix** → comment `@claude` on the issue; it opens a draft PR. Review the diff and **merge** to deploy. (If `MONITOR_PAT` is set, `@claude` issues are filed automatically; otherwise tap `@claude` yourself.)
4. **Daily digest** → a single `[monitor] Daily digest` issue, refreshed each run, with one heartbeat comment per day so a healthy weekend still pings once.

The monitor **auto-closes** an incident issue once the condition clears.

## Layer 0 — set up first (~30 min, does not need the repo)

**Uptime monitor** (UptimeRobot free tier or Better Stack):
- Monitor 1: `https://wc2026-api-production-a0f4.up.railway.app/api/v1/health/ready`, interval 1–5 min, alert on non-200 (503 = DB down). Optional keyword check for `"db":"ok"`.
- Monitor 2: `https://wc2026-prod.vercel.app` (frontend up).
- Alert contact: the provider's mobile app push + SMS.

**Sentry alert rules** (both projects — frontend `VITE_SENTRY_DSN`, backend `SENTRY_DSN_BACKEND`):
- Rule, env=`production`: "a new issue is created" **and** "an issue is seen more than ~10 times in 1 hour" → notify via Sentry mobile app / email / SMS.

## GitHub configuration (Settings → Secrets and variables → Actions)

**Variable** (not secret):

| Name | Value |
|---|---|
| `PROD_API_BASE_URL` | `https://wc2026-api-production-a0f4.up.railway.app` |

**Secrets:**

| Name | Value / where to get it |
|---|---|
| `MONITOR_DATABASE_URL` | Read-only pooler DSN — see below. |
| `JWT_ACCESS_SECRET` | Copy from Railway prod service env (same value the API uses). |
| `MONITOR_ADMIN_PLAYER_ID` | `6122c7fe-dfe3-4f22-839d-26dfc7bb906b` (the superadmin profile). |
| `ANTHROPIC_API_KEY` | For the `@claude` auto-fix workflow. |
| `FOOTBALL_DATA_API_KEY` | *Optional* — enables an upstream-provider probe. |
| `MONITOR_PAT` | *Optional* — fine-scoped PAT (repo: issues + contents) so bot-filed `@claude` issues auto-trigger the fix workflow. Without it, you tap `@claude`. |

**Read-only DB role + DSN.** Run the role SQL from the chat (creates `monitor_ro` with `SELECT` + RLS read policies — RLS is ON, so the policies are mandatory or it sees zero rows). Then build `MONITOR_DATABASE_URL` from the Supabase **Transaction pooler** string (Dashboard → Database → Connect → Transaction pooler — it's IPv4, which GitHub Actions needs):

```
postgresql://monitor_ro.kznxjyaanotrejcevngy:<PASSWORD>@<pooler-host>:6543/postgres
```

i.e. take the pooler URI and swap the user `postgres.<ref>` → `monitor_ro.<ref>` and the password. The healthcheck sets `statement_cache_size=0` for transaction-mode pooling.

## Thursday 11 Jun — dry-run before you leave (make-or-break)

First live match kicks off **Thu 11 Jun 19:00 UTC** — rehearse against it.

1. **Local:** `python scripts/prod_healthcheck.py --text` with `PROD_API_BASE_URL` + `MONITOR_DATABASE_URL` set → connects, all green.
2. **CI dry-run:** Actions → prod-monitor → Run workflow → `dry_run: true` → green, reads prod, prints intended actions.
3. **Synthetic incident:** temporarily lower a threshold (e.g. `SYNC_HEARTBEAT_WARN_MIN`) or point at a stale condition; run for real → confirm a diagnosed issue is created **and your phone buzzes** (GitHub mobile). Reply `/status` → confirm the next run executes it and comments back. Then `/resolve`.
4. **Auto-fix:** comment `@claude` on a test issue → confirm a draft PR opens.
5. **Layer 0:** use the uptime provider's "test"/pause to confirm an **SMS/push reaches your phone**; fire a test Sentry event.
6. Revert the synthetic threshold change.

## Operating notes

- **Pause the monitor:** Actions → prod-monitor → ⋯ → Disable workflow. Layer 0 keeps paging.
- **Kickoff freeze:** every issue/PR shows whether a match window is active — don't merge/deploy during one.
- **After the trip:** rotate `JWT_ACCESS_SECRET` (it lived in GitHub secrets), or `DROP ROLE monitor_ro;` if retiring the monitor.
- **Least privilege:** detection uses the read-only role only; the admin token is minted just-in-time for `/sync`, `/backup`, `/enter-result` and is short-lived (1 h).
