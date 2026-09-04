# Command: batch-verify

Verify that a completed batch meets its acceptance criteria before closeout.

## Inputs

- Batch id, for example `1` or `Batch 1`. If omitted, infer from the current
  branch name and recent changes.

## Procedure

1. Read `STATUS.md`, `AGENTS.md`, `docs/phase-batches.md`, and the current diff.
2. Find the target batch row and turn its acceptance criteria into a checklist.
3. Inspect the implementation against every checklist item.
4. Run the relevant verification commands:
   - Backend: `PYTHONPATH=/Users/craigrobinson/garmin-coach/apps/api /Users/craigrobinson/garmin-coach/apps/api/.venv/bin/python -m pytest`
   - Backend lint: `PYTHONPATH=/Users/craigrobinson/garmin-coach/apps/api /Users/craigrobinson/garmin-coach/apps/api/.venv/bin/python -m ruff check /Users/craigrobinson/garmin-coach/apps/api`
   - Backend type check: `PYTHONPATH=/Users/craigrobinson/garmin-coach/apps/api /Users/craigrobinson/garmin-coach/apps/api/.venv/bin/python -m mypy /Users/craigrobinson/garmin-coach/apps/api/src`
   - Frontend: `PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/garmin-coach/apps/web test`
   - Frontend build: `PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/garmin-coach/apps/web build`
   - Frontend lint: `PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/garmin-coach/apps/web lint`
5. For frontend-visible batches, inspect the Vercel preview or local app in a
   browser and record what was checked.
6. **Ask the JSONB question once, here, rather than remembering it.** For every
   multi-row read the batch added or touched: does it `select(Model)` on one of
   the four JSONB-carrying models — `sleep`, `daily_metrics`,
   `temperature_readings`, `analyses` — when the caller reads only typed columns?
   If so it belongs in `services/bulk_history_reads.py`, which is the documented
   entry point for the pattern. `select(Model)` is still the default idiom in
   this codebase and nothing lints it, which is why both of this app's egress
   incidents (Batch 232's pooler refusals, Batch 235's 34.8 GB) came from it and
   why new instances kept appearing in code written *after* Batch 235
   (`CR236-13`). The check is cheap: `grep -n "select(Sleep)\|select(DailyMetric)\|select(TemperatureReading)\|select(Analysis)" <changed files>`.
7. Report pass/fail by acceptance criterion, with exact remaining gaps.
8. Do not merge, deploy, or strike the batch row. `/closeout` does that only
   after the user asks.

## Guardrails

- If a command cannot run because dependencies/secrets are missing, record the
  blocker and substitute the narrowest useful local verification.
- Avoid mutating production data from preview deployments; previews currently
  proxy `/api/*` to production Railway/DB.
