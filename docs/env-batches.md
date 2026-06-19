# Env / Ops Batches

Infrastructure and environment-variable tasks. No code commits required; acceptance = all vars verified present and correct via CLI.

Use `/next-batch-prompt env` to generate the paste prompt. Use `/strike-batch E1` (etc.) to mark complete.

| Batch | Model | Items | Rationale |
|---|---|---|---|
| ~~E1~~ | ~~🟢 Sonnet~~ | ~~E1.1–E1.5~~ | ✅ Shipped 2026-05-30 |
| ~~E2~~ | ~~🟢 Sonnet~~ | ~~E2.1–E2.5~~ | ✅ N/A — invite link copied to clipboard; email not needed |

---

## E1 — Dashboard Fixes

Quick no-code fixes: Sentry parity for staging, Vercel Development-target gaps, duplicate audit, scheduler cleanup.

### E1.1 — Sentry DSN on Railway staging

Add `SENTRY_DSN_BACKEND` to Railway staging (`wc2026-predictor` service, `staging` env, project `8778ecd8-0d8c-4c99-bc04-15a627cf78a2`, service `0df72706-b54f-4c55-b703-3365215c0155`). Use the **same DSN value** as Railway prod — Sentry's `environment` tag distinguishes them. Verify:

```bash
railway variables --project 8778ecd8-0d8c-4c99-bc04-15a627cf78a2 --service 0df72706-b54f-4c55-b703-3365215c0155 --environment staging 2>&1 | grep SENTRY
```

### E1.2 — Sentry DSN on Vercel staging

Add `VITE_SENTRY_DSN` to Vercel staging project (`wc2026-staging`, `prj_hVMpuWm33XjuNrVUWrCti27ZfIX7`, `--cwd apps/web`). Target **Production + Preview**. Use the same DSN value as prod Vercel (`wc2026-prod`). Verify:

```bash
vercel env ls --cwd /Users/craigrobinson/wc_2026_predictor/apps/web 2>&1 | grep SENTRY
```

### E1.3 — Vercel Development-target gaps (both projects)

`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and `VITE_VAPID_PUBLIC_KEY` are missing from the **Development** environment target on both Vercel projects. Without them, `vercel env pull` only yields `VITE_API_URL` — local dev is incomplete.

Add all three vars to the Development target on:
- `wc2026-staging` (`--cwd apps/web`) — copy values from its Production target
- `wc2026-prod` — copy values from its Production target

After adding, run `vercel env pull apps/web/.env.local --cwd apps/web --environment=development` and confirm all four `VITE_*` keys are present.

### E1.4 — Audit duplicate VITE_API_URL in prod Vercel

`wc2026-prod` shows two `VITE_API_URL` rows in the API response. Confirm whether these are two environment scopes (Production + Development — expected) or a genuine duplicate value pointing at wrong URLs. Remove any true duplicate.

```bash
TOKEN=$(cat ~/Library/Application\ Support/com.vercel.cli/auth.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['token'])"); curl -s "https://api.vercel.com/v9/projects/prj_xSA1k6vKHfk0KLRjGNPUTluZD8UT/env" -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; data=json.load(sys.stdin); [print(e['key'], e.get('target'), e.get('gitBranch','')) for e in data.get('envs',[]) if e['key']=='VITE_API_URL']"
```

### E1.5 — Scheduler cleanup in Railway staging

Check the value of `SCHEDULER_ENABLED` in Railway staging. The code default is `True`, so if the var is set to `true` it is redundant noise. If `false`, it is intentional (suppresses the scheduler in staging).

```bash
railway variables --project 8778ecd8-0d8c-4c99-bc04-15a627cf78a2 --service 0df72706-b54f-4c55-b703-3365215c0155 --environment staging 2>&1 | grep SCHEDULER
```

- If `true` → remove it (`railway variables delete SCHEDULER_ENABLED --environment staging ...`).
- If `false` → leave it; note the reason in a comment below this bullet.

**Acceptance:**
- `SENTRY_DSN_BACKEND` present in Railway staging (verified via CLI)
- `VITE_SENTRY_DSN` present in Vercel staging Production target (verified via CLI)
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_VAPID_PUBLIC_KEY` present in Development target on both Vercel projects
- `VITE_API_URL` confirmed correct and non-duplicate in prod Vercel
- `SCHEDULER_ENABLED` in staging either removed (if was `true`) or left with a documented reason (if `false`)
- `vercel env pull` from `apps/web/` now yields all four `VITE_*` keys locally

---

## E2 — Email Setup (Resend)

Invite emails are silently skipped today — the backend logs a warning and exits if `resend_api_key` is empty. This batch wires Resend in both environments and verifies end-to-end delivery.

**Human prerequisite before starting:** Create a Resend account and have access to DNS for the sending domain. The DNS verification step can take minutes to 24 h — start it early.

### E2.1 — Create Resend account and API key

Sign up at resend.com if not already done. Create an API key with "Sending" permission (not full access). Note the key — it will be set in Railway in E2.3 and E2.4.

### E2.2 — Verify sending domain in Resend

Add a sending domain in the Resend dashboard. Add the required DNS records (TXT + MX or DKIM) and wait for verification. The `EMAIL_FROM` address must use this domain (e.g. `noreply@yourdomain.com`).

### E2.3 — Set RESEND_API_KEY + EMAIL_FROM in Railway staging

Once the domain is verified, set both vars in Railway staging (`wc2026-predictor`, project `8778ecd8-0d8c-4c99-bc04-15a627cf78a2`, service `0df72706-b54f-4c55-b703-3365215c0155`, environment `staging`):

```bash
railway variables set RESEND_API_KEY=<key> EMAIL_FROM="WC2026 Predictor <noreply@yourdomain.com>" \
  --project 8778ecd8-0d8c-4c99-bc04-15a627cf78a2 \
  --service 0df72706-b54f-4c55-b703-3365215c0155 \
  --environment staging
```

Verify:
```bash
railway variables --project 8778ecd8-0d8c-4c99-bc04-15a627cf78a2 --service 0df72706-b54f-4c55-b703-3365215c0155 --environment staging 2>&1 | grep -E 'RESEND|EMAIL'
```

### E2.4 — Set RESEND_API_KEY + EMAIL_FROM in Railway prod

Same values targeting prod service (`wc2026-api`, service `df2ec773-52a8-4593-aa31-68e55cc0dca4`, environment `production`). Can reuse the same API key.

```bash
railway variables set RESEND_API_KEY=<key> EMAIL_FROM="WC2026 Predictor <noreply@yourdomain.com>" \
  --project 8778ecd8-0d8c-4c99-bc04-15a627cf78a2 \
  --service df2ec773-52a8-4593-aa31-68e55cc0dca4 \
  --environment production
```

### E2.5 — End-to-end test in staging

Trigger an invite flow in staging (league admin UI → invite a player, or direct API call to `/api/v1/leagues/{id}/invites`). Confirm the email arrives in the recipient inbox. Check Railway staging logs for absence of `resend_api_key not configured` warnings and for any Resend error responses.

**Acceptance:**
- `RESEND_API_KEY` and `EMAIL_FROM` present in Railway staging (verified via CLI)
- `RESEND_API_KEY` and `EMAIL_FROM` present in Railway prod (verified via CLI)
- Sending domain verified in Resend dashboard (green status)
- At least one invite email received end-to-end in staging (check inbox + Resend activity log)
- No `resend_api_key not configured` warnings in Railway staging logs
