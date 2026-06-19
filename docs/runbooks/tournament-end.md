# Runbook: Tournament End

Use this runbook after the World Cup 2026 Final has been played and all points have been awarded.

---

## Step 1 — Take a final backup

```bash
curl -X POST "https://<your-api-domain>/api/v1/admin/backup" \
  -H "Authorization: Bearer <admin-jwt-token>"

# Download the file immediately (Railway /tmp is ephemeral)
curl -OJ "https://<your-api-domain>/api/v1/admin/backups/<FILENAME>" \
  -H "Authorization: Bearer <admin-jwt-token>"
```

Store this backup somewhere permanent (personal cloud storage, local hard drive).

---

## Step 2 — Award special predictions

If special prediction winners have not been auto-scored:

```bash
# Award tournament winner
curl -X POST "https://<your-api-domain>/api/v1/admin/specials/award" \
  -H "Authorization: Bearer <admin-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"prediction_type": "tournament_winner", "correct_team_id": "<TEAM_UUID>"}'

# Award golden boot (player name, case-insensitive string match)
curl -X POST "https://<your-api-domain>/api/v1/admin/specials/award" \
  -H "Authorization: Bearer <admin-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"prediction_type": "golden_boot", "correct_player_name": "Kylian Mbappe"}'

# Award top scoring team
curl -X POST "https://<your-api-domain>/api/v1/admin/specials/award" \
  -H "Authorization: Bearer <admin-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"prediction_type": "top_scoring_team", "correct_team_id": "<TEAM_UUID>"}'
```

---

## Step 3 — Verify the final leaderboard

```bash
curl "https://<your-api-domain>/api/v1/leaderboard" \
  -H "Authorization: Bearer <admin-jwt-token>" | jq '.[] | {rank, player_name, total_points}'
```

Confirm that:
- All players have a rank
- Total points look reasonable (typical range: 50–200 pts for a full tournament)
- The winner is correct

---

## Step 4 — Announce the winner

Share the final leaderboard screenshot in the group chat. Celebrate appropriately.

---

## Step 5 — Wind down the infrastructure (optional)

If you no longer need the live service:

1. **Download all backups** from `/api/v1/admin/backups` for archival.
2. In the Railway dashboard, **suspend** both services (backend + database) to stop billing.
3. Optionally export the database from the Supabase dashboard (Supabase → Database → Backups).

The frontend on Vercel can remain live indefinitely on the free tier — players can browse the final leaderboard and their prediction history.

---

## Notes

- Do not delete the Supabase project unless you are sure no one wants to review their predictions.
- The daily backup job (`scheduler.py: run_scheduled_backup`) continues until the backend is suspended.
- JWT tokens expire: access tokens after 24h, refresh tokens after 30d. After 30 days players will be "logged out" and cannot re-authenticate if the service is down. This is expected.
