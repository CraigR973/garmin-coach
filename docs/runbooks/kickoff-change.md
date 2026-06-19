# Runbook: Kickoff Time Change

Use this runbook when a match is rescheduled to a different kickoff time.

---

## When to use

FIFA or the tournament organiser announces a kickoff time change. This may or may not affect players' ability to edit predictions (depends on whether predictions were already locked).

---

## Step 1 — Find the match ID

```bash
curl "https://<your-api-domain>/api/v1/matches" \
  -H "Authorization: Bearer <admin-jwt-token>" | \
  jq '.[] | select(.match_number == <MATCH_NUMBER>) | {id, match_number, kickoff_utc, status}'
```

---

## Step 2 — Reschedule the match

```bash
curl -X POST "https://<your-api-domain>/api/v1/admin/matches/<MATCH_ID>/reschedule" \
  -H "Authorization: Bearer <admin-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"kickoff_utc": "2026-06-15T19:00:00Z"}'
```

**What happens automatically:**
- `original_kickoff_utc` is recorded if not already set
- If the match was `locked` and the new kickoff is later than the lock time, the match reverts to `scheduled` (predictions re-open)
- A `kickoff_changed` audit log entry is written
- Players with the notification preference enabled receive a push notification

---

## Step 3 — Verify

```bash
curl "https://<your-api-domain>/api/v1/matches/<MATCH_ID>" \
  -H "Authorization: Bearer <admin-jwt-token>" | \
  jq '{kickoff_utc, original_kickoff_utc, status}'
```

Confirm:
- `kickoff_utc` shows the new time
- `original_kickoff_utc` is set
- `status` is correct (reverted to `scheduled` if re-opened)

---

## Notes

- If the match has already been `completed`, do not reschedule — contact a developer.
- Notifications are sent asynchronously; allow a few seconds before checking delivery.
- Players in different timezones will see the updated kickoff in their local time automatically (the frontend converts UTC).
