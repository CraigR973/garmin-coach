---
description: Promote staging -> main behind the full CI gate. Verifies staging is green, merges to main, watches CI + the Vercel/Railway prod auto-deploys, and confirms production is live. The gated counterpart to /ship-staging.
---

You are running the production-promotion loop. The user invokes this as:

```
/ship-prod
```

No arguments. `/ship-prod` never commits new code — it only promotes what is
already on the `staging` branch to `main`. All real work ships through
`/ship-staging` first; this command is the gate from a soaked staging build to
production.

## The model this enforces

Production migrations are **auto but gated**: `main` only ever receives commits
that already deployed and migrated successfully on `staging`. By the time a
migration reaches the prod database it has run against the staging database and
been soaked. If a prod migration ever fails on boot, the Railway container exits
and Railway keeps the last healthy deployment serving — no half-migrated prod.

## Pre-conditions

Stop and report (do not proceed) if any fail:

1. `~/Library/Application Support/com.vercel.cli/auth.json` exists and `.env`
   exposes `GITHUB_TOKEN`. If either is missing, stop and say what to add.
2. The local `staging` branch exists and matches `origin/staging`:
   `git fetch origin` then confirm `git rev-parse staging` == `git rev-parse origin/staging`.
   If they differ, stop — staging has un-pushed or un-pulled commits.
3. The **most recent CI run for the current `staging` HEAD SHA** concluded
   `success`. Fetch it:
   ```bash
   source /Users/craigrobinson/wc_2026_predictor/.env
   SHA=$(git -C /Users/craigrobinson/wc_2026_predictor rev-parse origin/staging)
   curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
     "https://api.github.com/repos/CraigR973/wc2026-predictor/actions/runs?branch=staging&head_sha=$SHA&per_page=1" \
     | python3 -c "import sys,json; r=json.load(sys.stdin)['workflow_runs']; print(r[0]['conclusion'] if r else 'NONE')"
   ```
   If this is not `success`, refuse — tell the user to `/ship-staging` and let
   CI go green first. **This is the gate. Do not bypass it.**
4. Working tree is clean (`git status --porcelain` empty).

## Kickoff-time freeze check (live tournament only)

During the tournament window (Jun 11 – Jul 19, 2026), do not deploy within 30
minutes of a scheduled kickoff.

`/api/v1/matches/upcoming` **cannot** be used here: the entire `/api/v1/matches/*`
router requires an authenticated player by design (private league) and returns
`401 {"detail":"Not authenticated"}` to an unauthenticated curl. Check the next
kickoff via the **authenticated PWA** instead — open the prod app
(`https://wc2026-prod.vercel.app`, where the operator is already signed in) and
read the next scheduled kickoff from the fixtures / dashboard "next match" tile.

If a match kicks off within ±30 min, warn the user and ask for explicit
confirmation before continuing. Outside the tournament window, skip this.

Track progress with a single TodoWrite list.

## Step 1 — Promote staging -> main

1. `git fetch origin`.
2. `git checkout main`.
3. `git pull --ff-only origin main` — if this fails, stop and report (main has
   diverged; do not force).
4. Merge staging. Prefer fast-forward; fall back to a merge commit:
   ```bash
   git merge --ff-only staging || git merge --no-ff staging -m "merge: staging -> main (prod release)"
   ```
   Resolve conflicts by stopping and reporting; never auto-resolve.
5. `git push origin main`.
6. `git checkout staging` — leave the user back on staging.

## Step 2 — Watch the production rollout

The push to `main` triggers three things in parallel:
- The `CI` workflow on `main` (full suite, minus the staging-only deploy job).
- **Vercel** auto-deploys the prod frontend (GitHub integration on `main`).
- **Railway** auto-deploys the prod backend (GitHub integration on `main`); the
  Dockerfile CMD runs `alembic upgrade head` before uvicorn, migrating the prod
  DB automatically.

1. Get the `main` CI run id (same pattern as `/ship-staging`, branch=`main`).
2. Poll until `completed` with a background `until` loop, 25-second polls.
   Never chain sleeps from the main turn.
3. While CI runs, the platform deploys usually finish first (~90 s frontend).

## Step 3 — Verify production

1. Frontend: `curl -sI https://wc2026-prod.vercel.app` returns HTTP 200. Fetch
   the HTML, extract the `index-*.js` chunk, fetch it, grep for a marker the
   user expects from this release.
2. Backend health checks — both must return 200:
   ```bash
   curl -s https://wc2026-api-production-a0f4.up.railway.app/api/v1/health
   curl -s https://wc2026-api-production-a0f4.up.railway.app/api/v1/health/ready
   ```
   `/health/ready` returning `db: ok` confirms the backend booted **after** its
   migrations applied — i.e. the prod migration succeeded.

3. **SHA gate (R8.1 — hard gate, do not skip):** Assert the running commit SHA
   matches the `main` HEAD that was just pushed:
   ```bash
   EXPECTED_SHA=$(git -C /Users/craigrobinson/wc_2026_predictor rev-parse main)
   ACTUAL_SHA=$(curl -s https://wc2026-api-production-a0f4.up.railway.app/api/v1/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('sha','unknown'))")
   echo "expected=$EXPECTED_SHA actual=$ACTUAL_SHA"
   [ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || echo "FAIL"
   ```
   If `ACTUAL_SHA` differs from `EXPECTED_SHA` **or** is `"unknown"`, **stop
   and fail the promotion** with:
   > "Backend is still serving a previous image (sha mismatch: expected
   > `<expected>`, got `<actual>`). Check the Railway source/branch trigger
   > (Operator action OP2 in `docs/review-batches.md`). Do not proceed."

4. **Post-deploy synthetic (R8.5 — hard gate):** Send a CORS preflight-style
   request to a **public** read-only route through the prod frontend origin to
   catch prod-only env/CORS mismatches. Use `/api/v1/health` — it is
   unauthenticated and returns a JSON body, so it can actually pass. (Do **not**
   use `/api/v1/matches/upcoming` or any other `/api/v1/matches/*` route here:
   that router requires an authenticated player by design — private league — and
   returns `401 {"detail":"Not authenticated"}` to an unauthenticated curl, so it
   can never satisfy this gate.)
   ```bash
   ORIGIN="https://wc2026-prod.vercel.app"
   API="https://wc2026-api-production-a0f4.up.railway.app/api/v1/health"
   # 1) body + status: must be 200 with a JSON {status: ...} body
   curl -sf -H "Origin: $ORIGIN" "$API" \
     | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok', f'unexpected shape: {d}'; print('health ok, sha:', d.get('sha','?'))"
   # 2) CORS: the prod origin must be echoed back in access-control-allow-origin
   ACAO=$(curl -s -D - -o /dev/null -H "Origin: $ORIGIN" "$API" \
     | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2}')
   echo "access-control-allow-origin=$ACAO"
   [ "$ACAO" = "$ORIGIN" ] || echo "FAIL: CORS origin mismatch (expected $ORIGIN)"
   ```
   If either step fails (non-2xx, wrong body shape, or the ACAO header is missing
   or does not equal the prod origin), **stop and fail the promotion**: the prod
   environment has a misconfiguration that staging did not catch. Do not proceed.

5. If `main` CI concluded `failure` OR any prod check above is unhealthy, treat
   it as a bad release: surface the failing job/log tail and point the user to
   the rollback section of `docs/runbooks/deploys-ongoing.md` (Vercel "Promote
   to Production" on the last good deploy; Railway redeploys the prior image).

## Step 4 — Report

Two sentences max:
- Production state now (prod URL + deployed SHA + backend health), or what
  failed (job name / unhealthy check) and the rollback pointer.
- Suggest the user reload the PWA on iPhone.

## Bash discipline

- Never `cd` (`AGENTS.md`). Use absolute paths or `git -C /Users/craigrobinson/wc_2026_predictor`.
- For long polls, use a background shell command with an `until` loop.
- Don't dump full CI logs into the conversation — grep / tail.
