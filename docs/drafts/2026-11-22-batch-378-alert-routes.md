# Batch 378 — how alerts reach Craig (options, 22 Nov 2026)

**Where this stands.** Batch-start is done (Decision #509) and 378.1–378.3 are explored.
Nothing is built, and no account, credential or setting has changed. It waits on Craig's
choice (378.4).

## The last 24 hours, which is the case for this batch

- **00:04 UTC, 22 Nov.** The coach passed one of Mark's reports to Craig: a post-session
  read was missing for a 21 Nov session. It reached Sentry only. The cause is in the logs:
  `post-workout-backstop` crashed for that session at 20:30 on 21 Nov
  (`InvalidRequestError`, `Activity.raw_summary` under `raiseload`) and recorded the job
  as `degraded`, which the watchdog does not count.
- **00:06–01:30 UTC.** Anthropic refused four paid calls with "credit balance is too low"
  (`admin_alert=billing`, Sentry only). By 09:10 the credit had been topped up, because
  the morning brief was written.
- **03:00 UTC.** The weekly backup failed on a Backblaze 503 (no retry). It was fixed the
  same day (PR #452, Decision #508).
- **All day.** GitHub ran the 30-minute watchdog about 3.7 times a day. It caught the
  backup at 07:22 and then did not run for 8 hours.

None of these reached Craig through the app.

## Re-verified at batch-start (corrections to the row)

The row's facts hold: the 12 `admin_alert` kinds, the two `alert_route` values, the
pass-on refusing to claim success without a DSN, push subscriptions tied to a profile,
production's one profile, and the watchdog counts. Three corrections:

1. **A `degraded` job alerts nothing.** `/health/jobs` counts a job as failing only when
   its newest run `failed`. The 21 Nov backstop crash was `degraded`.
2. **Plain `log.error`s outside `admin_alert` carry no kind.** The backstop's
   "reader failed" is one of them. 337.1's rule (every operator error through
   `admin_alert`) is what fixes this.
3. **A week of alerts cannot be counted from Railway's logs.** They come per deployment
   and stop at the last 5,000 lines, about 2 days, so 390's queue should keep the count.

## Every alert today, and where it would go

| Kind | Means | Page Craig now? |
|---|---|---|
| `billing` | Anthropic credit or limit ran out | Yes, urgently (money) |
| `source_auth` | Garmin or Hive refused the login | Yes (his or Mark's account) |
| `delivery_rail` | Rides not reaching Zwift, or soon | Yes (Mark's account) |
| `backup_failed`, `backup_restore_drill_failed` | The backup or its proof failed | Yes |
| storage, egress stages | A free-plan limit is near | Yes (hosting) |
| `coach_feedback` | Mark asked the coach to pass something on | Yes |
| `figure_contest` | Mark disputed a figure | Yes |
| `generation_failure`, `longitudinal`, `coach_memory` | A paid generation failed for a fault | Yes, once a day |
| `brief_check`, `cross_surface_disagreement`, `live_ride_mismatch` | A check caught something | Yes, once a day |
| `metric_baselines_stale`, a job `degraded` or stale | A job is not doing its work | Yes, once a day |
| `plan_accepted_comparison` | Information only | No, the digest |

Once G14 is live, most of these go to the loop's queue (390). Only money, Craig's
accounts, deleting data, loosening a symptom rule and the loop failing twice still page
him (Decision #507).

## Routes to Craig's phone (378.1)

| Route | Cost and setup | Trade-off |
|---|---|---|
| **A. Pushover** | $4.99 once per platform; 10,000 messages a month free. Craig makes the account; the app gets a token (a Railway variable). | Emergency priority repeats until he acknowledges it (every 30 s or more, for up to 3 h). Pushover's servers see the text. One-way. |
| **B. Telegram bot** | Free. Craig makes a bot (BotFather token) and gives it his chat. | Two-way, so buttons and replies could approve things later. Telegram's servers see the text (bot chats are not end-to-end encrypted). Replies need an inbound webhook. |
| **C. The app's own web push** | Free, but the biggest build: an operator sign-in that never syncs or generates (the stray second profile of 24 Aug did both), every job filtering it out, and an operator page. | The most private option: the payload is encrypted end to end, and tapping it opens the app. Silent when the app itself is down. |
| **D. Email from the app** | Free tiers. Needs a sending credential or domain. | It lands in the inbox rather than paging him. The provider sees the text. |

Sentry email is out (Decision #481).

## Outside check (378.2)

| Check | Cost and setup | Trade-off |
|---|---|---|
| **1. UptimeRobot** keyword monitor on `/health/jobs` | Free: 50 monitors, every 5 min, for personal projects; Pushover is a free integration. Craig makes the account. | It alerts when the state changes, not on every run. It sees problem codes only. |
| **2. Healthchecks.io** dead-man's switch | Free: 20 checks. The app pings it after each run; a missing ping alerts. | It catches a stopped scheduler even while the API answers. It needs code to ping. |
| **3. GitHub's schedule** (today) | Free; nothing to set up. | Ran about 3.7 times a day; missed the 12 Nov freeze; emails on every failing run. |

## Recommendation

- **Route A (Pushover)** pages Craig for the kinds marked "Yes" and repeats only for
  `billing`. The payload is the kind plus the coach's one-line summary, never Mark's own
  words. Why not B: two-way is attractive for G14, but replies need a webhook and
  a second chat app, and G14's approvals can live in the app (392, 393). Why not C: it is
  the most private, but it is the largest build and silent when the app is down; revisit
  it with 390's operator page.
- **Check 1 (UptimeRobot)** watches `/health/jobs` every 5 minutes and alerts through the
  same Pushover app, so one app on Craig's phone carries both. `/health/jobs` starts
  reporting `degraded:<job>` too. GitHub's watchdog stays as a backstop until UptimeRobot
  has proved itself, then Craig decides whether to retire it.
- **Proof (378.6):** one synthetic pass-on and one synthetic operator alert arrive on
  Craig's phone; a UptimeRobot monitor pointed at a code that is not there goes "down" and
  alerts, without touching production.

## What Craig decides (378.4)

1. The route (recommended: Pushover), and which phone, iPhone or Android, for the
   $4.99 licence.
2. The outside check (recommended: UptimeRobot).
3. What a pass-on push carries (recommended: the coach's one-line summary, not Mark's words).
4. The two benign tests above.
5. Keep GitHub's watchdog until the new check proves itself (recommended: yes).

Sources (read 22 Nov 2026): pushover.net/pricing, pushover.net/api,
uptimerobot.com/pricing.md, healthchecks.io/pricing.

## Craig's answers (22 Nov) and his steps

**Chosen:** email, sent from a new Gmail used only by the app, to Craig's own address (kept
only in a Railway variable); UptimeRobot watching `/health/jobs`; the coach's one-line
summary in a pass-on email. Pushover, Telegram and web push are not used.

**Craig's steps** (none needs the build first; nothing is shared in chat or in the repo):

1. **Create the sender.** Make a new free Gmail account for the app only. Turn on 2-Step
   Verification, then create an app password (Google Account → Security → App passwords),
   named `garmin-coach`.
2. **Give it to Railway.** On the `api` service (production) → Variables, add
   `ALERT_EMAIL_FROM` (the new Gmail address), `ALERT_EMAIL_APP_PASSWORD` (the 16-character
   app password) and `ALERT_EMAIL_TO` (your address). Railway redeploys; nothing uses them
   until 378 ships.
3. **Create the outside check.** Make a free UptimeRobot account with your address. Add a
   monitor: type **Keyword**, URL
   `https://api-production-e2bc7.up.railway.app/api/v1/health/jobs`, keyword
   `"status":"ok"`, alert when the keyword **does not exist**, interval **5 minutes**,
   alert contact your email. It reports "down" until the 23 Nov 03:00 UTC backup clears
   `failing:backup`; that first alert proves the route.
4. **In your mail app,** mark the new Gmail address as a VIP (or a priority sender) so these
   emails notify you.

**What 378 builds (378.5):** every alert kind emails you through one sender (once a day
per kind while it lasts; billing every 6 hours while it lasts); every operator error goes
through it (337.1); a `degraded` job alerts and shows on `/health/jobs`; a coach pass-on
emails you the coach's summary, and the coach says it was passed on only after the mail
server accepts it. **Proof (378.6):** after your yes, one test pass-on and one test
operator alert land in your inbox, and the UptimeRobot alert above arrives.
