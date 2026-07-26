# Device access and recovery

Garmin Coach uses one credential type: a long-lived opaque device token created
from a short-lived, single-use activation link. There is no PIN, password, JWT,
or public sign-up path.

## Set up a new device

Run the activation CLI with production `DATABASE_URL` and `FRONTEND_ORIGIN`
injected, then send the printed link over a private channel:

```bash
railway run --service api python -m src.activate --profile Mark
```

The link expires after 30 minutes and can be exchanged once. Opening it on the
target device stores a one-year device token locally. Minting a new link revokes
any older unused activation link, but does not sign out working devices.

## Sign out this device

The app's **Log out** action calls `POST /api/v1/auth/revoke` with the current
device credential, then clears the token, profile snapshot, and cached health
data from that browser. The endpoint stores/logs no raw credential.

For an API check, use a disposable active token and revoke it immediately after:

```bash
curl -i -X POST \
  -H "Authorization: Bearer $SMOKE_DEVICE_TOKEN" \
  https://api-production-e2bc7.up.railway.app/api/v1/auth/revoke
```

Treat `SMOKE_DEVICE_TOKEN` as a secret and never paste it into logs, tickets, or
committed files.

## Lost device or suspected token exposure

Revoke every active device for the profile and mint a fresh recovery link in one
operator command:

```bash
railway run --service api python -m src.activate \
  --profile Mark \
  --revoke-existing-devices
```

Send the new single-use link privately and activate the retained/new phone. This
signs out every old device; repeat normal setup for any other trusted device.

## Deployment cutover

Migration `023` refuses to remove the PIN columns if an existing active profile
has neither an active device token nor an unused activation code. It then revokes
all residual `purpose='refresh'` credentials and drops the PIN/lockout columns.

Remove `JWT_ACCESS_SECRET` and `JWT_REFRESH_SECRET` from Railway only after the
Batch 160 deployment is healthy on its exact commit. The new runtime does not
read them; the previous production build still does, so removing them before
promotion would break rollback/current production.
