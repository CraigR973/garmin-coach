# Runbook: Cancelled or Voided Match

Use this runbook when a match is cancelled or declared void by the tournament organisers.

---

## When to use

- A match is cancelled before it is played (e.g. both teams disqualified, extreme weather)
- A match is declared void after being played

---

## Step 1 — Find the match ID

```bash
curl "https://<your-api-domain>/api/v1/matches" \
  -H "Authorization: Bearer <admin-jwt-token>" | \
  jq '.[] | select(.match_number == <MATCH_NUMBER>) | {id, match_number, kickoff_utc, status}'
```

---

## Step 2 — Cancel the match

```bash
curl -X POST "https://<your-api-domain>/api/v1/admin/matches/<MATCH_ID>/cancel" \
  -H "Authorization: Bearer <admin-jwt-token>"
```

**What happens automatically:**
- Match status changes to `cancelled`
- No points are awarded for this match (predictions exist but `points_awarded` stays null)
- A `match_cancelled` audit log entry is written
- The predictions page shows this match as "Voided" with reduced opacity

---

## Step 3 — Verify

```bash
curl "https://<your-api-domain>/api/v1/matches/<MATCH_ID>" \
  -H "Authorization: Bearer <admin-jwt-token>" | \
  jq '{status, actual_home_score, actual_away_score}'
```

Confirm `status` is `cancelled`.

---

## Step 4 — Communicate to players (manual)

The system does not automatically notify players of a cancellation beyond showing it in the UI. Send a message to the league group chat explaining that the match is void and no points will be awarded.

---

## Notes

- A cancelled match cannot be uncancelled via the API. Contact a developer if you need to revert this.
- Leaderboard totals are not affected because no points were ever written for the cancelled match.
- If a match was `completed` with results entered and then needs to be voided, contact a developer — this requires a database-level correction.
