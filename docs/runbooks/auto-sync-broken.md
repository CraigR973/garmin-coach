# Runbook: Auto-Sync Broken

Use this runbook when the automatic result-fetching job is failing or producing incorrect results.

---

## Symptoms

- Match results are not appearing after games finish
- Players are not receiving result notifications
- The admin sync status page shows repeated `sync_failed` errors
- Leaderboard has not updated after results were expected

---

## Step 1 — Check sync status

```bash
curl "https://<your-api-domain>/api/v1/admin/sync/status" \
  -H "Authorization: Bearer <admin-jwt-token>" | jq .
```

Look at:
- `last_sync_at` — when the last sync ran
- `last_sync_action` — should be `result_auto_fetched` after a successful sync
- `recent_errors` — the `changes.detail` field explains why it failed

Common errors:
- `"football-data.org request failed"` — API key issue or rate limit (see Step 2)
- `"Connection refused"` — database connectivity issue (see Step 3)
- `"timeout"` — external API slow; usually self-resolving

---

## Step 2 — Verify the football-data.org API key

```bash
curl "https://api.football-data.org/v4/competitions/WC/matches" \
  -H "X-Auth-Token: <FOOTBALL_DATA_API_KEY>"
```

- **200 OK** — key is valid; the issue may be a rate limit (429) or a service outage
- **403 Forbidden** — key is invalid or revoked; update `FOOTBALL_DATA_API_KEY` in the Railway environment and redeploy
- **429 Too Many Requests** — you have exceeded the API's rate limit (10 req/min on free tier); reduce sync frequency or upgrade the plan

To temporarily increase sync resilience, trigger a manual sync and watch the logs:

```bash
curl -X POST "https://<your-api-domain>/api/v1/admin/sync/trigger" \
  -H "Authorization: Bearer <admin-jwt-token>"
```

---

## Step 3 — Enter results manually

While sync is broken, enter results by hand for any completed match:

```bash
# First entry (no prior result)
curl -X POST "https://<your-api-domain>/api/v1/admin/results/<MATCH_ID>" \
  -H "Authorization: Bearer <admin-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "actual_home_score": 2,
    "actual_away_score": 1,
    "extra_time": false,
    "penalties": false
  }'

# Override an incorrect result
curl -X PUT "https://<your-api-domain>/api/v1/admin/results/<MATCH_ID>" \
  -H "Authorization: Bearer <admin-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"actual_home_score": 2, "actual_away_score": 1, "extra_time": false, "penalties": false}'
```

---

## Step 4 — Check Railway logs

In the Railway dashboard, open the backend service logs and search for `sync_results` or `football_data`. Look for stack traces or repeated error messages.

If the scheduler has stopped entirely (no log output from jobs), restart the service:

Railway dashboard → Backend service → **Restart**.

---

## Step 5 — Verify recovery

After fixing the root cause or entering results manually, confirm the leaderboard has updated:

```bash
curl "https://<your-api-domain>/api/v1/leaderboard" \
  -H "Authorization: Bearer <admin-jwt-token>" | jq '.[0:3]'
```

---

## Notes

- The sync job runs every 5 minutes (`scheduler.py: sync_results`). A single failure is logged but the job retries on the next cycle.
- During a period of sync failures, no points are lost — the scoring trigger fires as soon as a result is entered (auto or manual).
- If the scheduler is producing duplicate results (race condition), check that Railway is running only **one** instance of the backend.
