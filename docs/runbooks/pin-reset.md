# Runbook: Player PIN Reset

Use this runbook when a player has forgotten their PIN and cannot log in.

There are two paths:

- **Self-service** (preferred) — player requests a reset email via the login page.
- **Admin-assisted** — admin generates a temporary PIN via the admin API (for players who have also lost access to their email).

---

## Path A — Self-service reset (email flow)

1. Player visits the login page and clicks **Forgot PIN?**
2. They enter their email address and submit the form.
3. They receive an email with a reset link (valid for 1 hour).
4. Clicking the link takes them to the PIN reset page where they set a new PIN.
5. Done — no admin involvement required.

If the player reports they never received the email, check the Resend dashboard for delivery status before falling back to Path B.

---

## Path B — Admin-assisted reset

### Step 1 — Find the player's ID

```bash
curl "https://<your-api-domain>/api/v1/admin/players" \
  -H "Authorization: Bearer <admin-jwt-token>" | \
  jq '.[] | select(.display_name == "<PLAYER_NAME>") | {id, display_name, email}'
```

### Step 2 — Generate a temporary PIN

```bash
curl -X POST "https://<your-api-domain>/api/v1/admin/players/<PLAYER_ID>/reset-pin" \
  -H "Authorization: Bearer <admin-jwt-token>"
```

The response contains a 4-digit temporary PIN:

```json
{"temp_pin": "4928"}
```

### Step 3 — Share the temporary PIN securely

Send the temporary PIN to the player via a private message (WhatsApp, iMessage, etc.). Do **not** share it in the group chat.

Instruct the player to:
1. Log in with their **email address** and the temporary PIN.
2. Immediately go to **Settings** and change their PIN to something only they know.

### Step 4 — Verify (optional)

Ask the player to confirm they can log in successfully and have changed their PIN.

---

## Notes

- The temporary PIN is generated with `secrets.randbelow` — it is cryptographically random.
- The old PIN is overwritten immediately on reset; the player cannot log in with it after Step B.2.
- There is no PIN history — you can reset as many times as needed.
- Login is now email-based. The player must know their registered email address to use Path A or the temporary PIN from Path B.
- If the player has also lost access to their email and their device (no cached session), contact a developer to update the email directly in the database before issuing a temporary PIN.
- If the player has a cached session but forgotten their PIN, they can still reach **Settings → Change PIN** while logged in.
- Session tokens expire within 30 days automatically. If immediate revocation is needed, contact a developer to rotate the JWT secret.
