# Gmail alert relay (Batch 378, Decision #511)

Operator alerts and the coach's pass-ons reach Craig by email. Railway's Hobby plan
blocks outbound SMTP (ports 25, 465, 587; seen 24 Nov 2026), so the app posts over HTTPS
to a Google Apps Script web app inside a Gmail account used only by the app. The script
checks a shared secret and emails the one address held in its own properties, so even a
stolen secret cannot send mail anywhere else.

```text
app (operator_email) ─HTTPS POST {secret, subject, body}─► Apps Script web app
                                                             │ secret matches?
                                                             ▼
                                         MailApp.sendEmail(RELAY_TO, subject, body)
                                                             │
                                                             ▼
                                                     Craig's inbox
```

The app succeeds only when the script answers `{"status": "sent"}`. Anything else (a
wrong secret, a script error, Google's quota of 100 emails a day on a personal account)
is a failed send, logged by class and status only.

## The script

Paste this into `Code.gs`. It holds no secret: both values live in Script Properties.

```javascript
// Garmin Coach alert relay (Batch 378, Decision #511).
// Sends one email from this Gmail account to the address in the RELAY_TO script
// property, when the request carries the RELAY_SECRET script property.
function doPost(e) {
  var props = PropertiesService.getScriptProperties();
  var secret = props.getProperty('RELAY_SECRET');
  var to = props.getProperty('RELAY_TO');
  var data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply_('bad_request');
  }
  if (!secret || !to || !data || data.secret !== secret) {
    return reply_('forbidden');
  }
  var subject = String(data.subject || '').slice(0, 150);
  var body = String(data.body || '').slice(0, 5000);
  if (!subject) {
    return reply_('bad_request');
  }
  MailApp.sendEmail(to, subject, body);
  return reply_('sent');
}

function reply_(status) {
  return ContentService
    .createTextOutput(JSON.stringify({ status: status }))
    .setMimeType(ContentService.MimeType.JSON);
}
```

## Setting it up (Craig's steps)

Never paste the secret or the URL into a chat. They go only into the script and Railway.

**A. Make a secret.** In Terminal on the Mac:

```bash
openssl rand -hex 24
```

Copy the 48 characters it prints.

**B. Create the script, signed in as the app Gmail.** Use a private window or another
browser profile, so it is not your own Google account.

1. Go to `script.google.com` and tap **New project**.
2. Tap **Untitled project** at the top left, type `garmin-coach-relay`, then **Rename**.
3. In `Code.gs`, delete the sample code, paste the script above, then tap **Save** (the
   disk icon).
4. Tap **Project Settings** (the gear on the left), scroll to **Script Properties** and tap
   **Add script property**:
   - **Property** `RELAY_SECRET`, **Value** the secret from A.
   - **Add script property** again: **Property** `RELAY_TO`, **Value** your own address.
   - Tap **Save script properties**.
5. Tap **Deploy** (top right), then **New deployment**. Tap the gear beside **Select
   type** and choose **Web app**. Set:
   - **Description**: `alerts`
   - **Execute as**: **Me** (the app Gmail)
   - **Who has access**: **Anyone**
   - Tap **Deploy**.
6. Tap **Authorize access** and choose the app Gmail. Google says it hasn't verified the
   app, because it is your own script: tap **Advanced**, then **Go to garmin-coach-relay
   (unsafe)**, then **Allow** (it asks to send email as that account).
7. Copy the **Web app URL** (it ends in `/exec`) and tap **Done**.

**C. Railway.** On the `api` service, open **Variables**:

1. Add `ALERT_EMAIL_RELAY_URL` with the Web app URL.
2. Add `ALERT_EMAIL_RELAY_SECRET` with the secret from A.
3. Delete `ALERT_EMAIL_FROM`, `ALERT_EMAIL_APP_PASSWORD` and `ALERT_EMAIL_TO`; nothing
   uses them now.
4. Press **Deploy** if Railway shows the changes as waiting.

**D. Tidy up Google.** At `myaccount.google.com/apppasswords` (as the app Gmail), remove
`garmin-coach`. The relay does not need an app password.

## Changing it later

- **New secret:** change `RELAY_SECRET` in Script Properties and
  `ALERT_EMAIL_RELAY_SECRET` in Railway together; until both match, sends fail
  (`forbidden`).
- **New script code:** **Deploy → Manage deployments → Edit (pencil) → Version: New
  version → Deploy** keeps the same URL. A **New deployment** makes a new URL, which then
  goes into Railway.
- **Proof that it works:** the two benign test emails in
  `scratchpad/batch-378-email-alerts/benign_378.py` (git-ignored), run inside the
  deployed container.
