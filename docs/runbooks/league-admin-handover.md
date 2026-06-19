# Runbook: League Admin Handover

Use this runbook when a league admin wants to transfer ownership to another member, or when the current admin leaves the league and a successor must be appointed.

---

## When is this needed?

- An admin is leaving the league and wants to hand it over.
- An admin account is deleted and the league would otherwise have no admin.
- A league was created by a placeholder account and needs a real owner.

---

## Self-service path (via the UI)

Admins can promote any active league member to admin and demote themselves to player directly from the league member management page:

1. Admin navigates to **League → Members**.
2. Clicks the menu next to the member to promote and selects **Make admin**.
3. (Optional) To step down, the original admin then selects **Change role → Player** on their own entry.

**Last-admin protection:** the API will refuse a demotion or removal that would leave a league with zero admins. Promote the successor first, then demote yourself.

All role changes are recorded in `audit_log` with `action_type = 'member_role_changed'`.

---

## Admin-assisted path (via the API)

If the outgoing admin has already lost access, a **superadmin** can change league membership roles directly.

### Step 1 — Identify the league and the new admin

```bash
curl "https://<your-api-domain>/api/v1/admin/leagues" \
  -H "Authorization: Bearer <superadmin-jwt>" | \
  jq '.[] | select(.slug == "<LEAGUE_SLUG>") | {id, slug, name}'

curl "https://<your-api-domain>/api/v1/leagues/<LEAGUE_SLUG>/players" \
  -H "Authorization: Bearer <superadmin-jwt>" | \
  jq '.[] | {id, display_name, role}'
```

### Step 2 — Promote the new admin

```bash
curl -X PATCH \
  "https://<your-api-domain>/api/v1/leagues/<LEAGUE_SLUG>/members/<PLAYER_ID>/role" \
  -H "Authorization: Bearer <superadmin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

### Step 3 — (Optional) Demote or remove the outgoing admin

If the outgoing admin's account still exists:

```bash
curl -X PATCH \
  "https://<your-api-domain>/api/v1/leagues/<LEAGUE_SLUG>/members/<OLD_ADMIN_ID>/role" \
  -H "Authorization: Bearer <superadmin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"role": "player"}'
```

If the account should be removed from the league entirely:

```bash
curl -X DELETE \
  "https://<your-api-domain>/api/v1/leagues/<LEAGUE_SLUG>/members/<OLD_ADMIN_ID>" \
  -H "Authorization: Bearer <superadmin-jwt>"
```

### Step 4 — Verify

```bash
curl "https://<your-api-domain>/api/v1/leagues/<LEAGUE_SLUG>/players" \
  -H "Authorization: Bearer <superadmin-jwt>" | \
  jq '[.[] | select(.role == "admin")]'
# Expect exactly one admin entry (the new owner).
```

---

## Database-level fallback (break-glass)

If the API path is unavailable (e.g. app is down during maintenance):

```sql
-- Find the league
SELECT id FROM leagues WHERE slug = '<LEAGUE_SLUG>';

-- Find the target member's membership row
SELECT id, player_id, role FROM league_memberships
WHERE league_id = '<LEAGUE_ID>'
  AND player_id = '<NEW_ADMIN_PLAYER_ID>'
  AND deleted_at IS NULL;

-- Promote
UPDATE league_memberships
SET role = 'admin', updated_at = NOW()
WHERE id = '<MEMBERSHIP_ID>';

-- Verify
SELECT p.display_name, m.role
FROM league_memberships m
JOIN profiles p ON p.id = m.player_id
WHERE m.league_id = '<LEAGUE_ID>' AND m.deleted_at IS NULL
ORDER BY m.role;
```

Insert a manual audit log row after the SQL update:

```sql
INSERT INTO audit_log (id, actor_id, actor_type, action_type, target_type, target_id, meta, created_at)
VALUES (
  gen_random_uuid(),
  '<SUPERADMIN_PLAYER_ID>',
  'player',
  'member_role_changed',
  'league_membership',
  '<MEMBERSHIP_ID>',
  '{"old_role": "player", "new_role": "admin", "note": "manual handover — runbook"}',
  NOW()
);
```

---

## Notes

- A league must always have at least one admin. The API enforces this; the SQL path does not — be careful.
- Role changes take effect immediately with no cache invalidation needed (JWT does not encode league role).
- The outgoing admin retains their predictions and points; only their league-level role changes.
- If the league should be archived rather than handed over, contact a developer — there is no self-service archive path in v1.
