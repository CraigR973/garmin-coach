# Lewis soak guide — The Steele Spreadsheet System

A one-pager to get you up and running on the staging build. Spend
two or three days using it like it's the real league. We're testing
the *feel* of the app before we open it up to the wider group, so
nothing you say is too small.

Staging URL: **https://wc2026-staging.vercel.app**

---

## 1. Join the league

1. Open the invite link Craig sends you.
2. Pick a display name (this is what shows on the leaderboard — go
   with whatever you'd use in the WhatsApp group).
3. Set a 4-digit PIN. You'll use this every time you log in, so
   make it memorable but not your bank one.
4. Skim the welcome screen and then land on the **Dashboard**.

If anything in this flow looks wrong, screenshot it and send it
over — first impressions matter.

---

## 2. Make your group-stage predictions

The bottom bar has five tabs: **Home · Schedule · Predict · Leader ·
More**.

Tap **Predict** to enter the predictions area. By default you're
on the group-stage sub-tab. You'll see every group-stage fixture
in a single scrollable list, grouped by matchday.

For each match:

- Tap the home or away score and use the spinner to pick a number
  (0–9).
- The save indicator changes from a faint dot to a tick when the
  prediction is locked in.
- You can change predictions any time **before the match's kickoff
  whistle**. Once kickoff hits, that match locks for everyone.

There's no submit-all button on purpose — every change auto-saves
the moment you set both scores.

---

## 3. The three specials

Tap **Predict → Specials** at the top.

You're picking three things that get awarded at the end of the
tournament:

| Special | Points if right |
|---|---|
| Tournament Winner | 20 |
| Golden Boot (top scorer) | 15 |
| Top Scoring Team | 10 |

**Specials lock the moment the opening match kicks off**, so you
need to lock these in early. There's no second chance.

---

## 4. Knockouts (expected to be locked)

Tap **Predict → Knockout**. You'll see an empty/teaser state —
that's correct. Knockout picks open up only once the group stage
finishes and the bracket is drawn. We've left the page accessible
so you can see what it'll look like when it goes live.

If you see actual knockout fixtures with score spinners, that's a
bug — flag it.

---

## 5. Install the app to your home screen

The app is a PWA — it installs like a real app without going
through the App Store.

**iPhone (Safari):**

1. Tap the **Share** icon (square with arrow up) at the bottom of
   the browser.
2. Scroll and tap **Add to Home Screen**.
3. Confirm the name and tap **Add**.

**Android (Chrome):**

You should get a "Install app?" prompt within the first few
visits — tap **Install**. If you don't see one, tap the
three-dot menu in Chrome and choose **Add to Home screen** or
**Install app**.

Once installed, launch it from the home-screen icon, not from the
browser. It should open full-screen with no browser chrome.

---

## 6. Push notifications

Open the app from the home screen, then tap **More → Settings**.

There's a push-notifications toggle near the top. Flip it on; the
browser will ask for permission — say yes. You'll start getting
pings 15 minutes before kickoff when you haven't submitted
predictions for that match.

If the permission prompt doesn't appear, or the toggle won't
stay on, flag it. iOS in particular is fussy about web push and
this is one of the things we most want to verify.

---

## 7. What to look for

Spend a couple of sessions wandering around. Tap on everything,
including:

- **Home** — the welcome line, next-match hero, mini leaders
- **Schedule** — filter pills, jump-to-today behaviour
- **Predict (groups / knockout / specials)** — every fixture
- **Leader** — sort, the history chart, the head-to-head compare
- **Groups** — open a single group, look at the standings
- **A match detail page** — tap a match from any list
- **More → Settings** — theme toggle (try light + dark), profile
- **Profile pages** — find one for me (Craig) and see what shows

We're sweating the small stuff:

- Anything that looks **wrong, broken, or low-effort**
- Copy that's confusing, robotic, or just bad ("Submit your
  prediction" → "Lock it in", that kind of thing)
- Transitions and animations — are they smooth, distracting,
  pointless, or missing where they'd help?
- Tap targets that are too small or too close to other things
- Anything that feels slow, janky, or laggy
- Colours / contrast — especially in **light mode** (the bulk of
  testing has been dark mode)
- Anything that just doesn't feel **premium**

There's no wrong answer. "I don't know why but this feels off"
is genuinely useful — Craig can work out the why.

---

## 8. How to report

Just message Craig directly — WhatsApp is fine, screenshots
encouraged. Format:

> **Where:** Predict → Specials
> **What:** Tournament Winner dropdown doesn't show flag emojis
> **Severity:** small thing, looks unfinished

Three buckets for severity:

- 🔴 **Broken / blocked** — couldn't complete something
- 🟡 **Annoying / unpolished** — works but feels wrong
- 🟢 **Nice to have** — small wish

Don't worry about classifying perfectly. Anything you flag gets
triaged.

---

## Thank you

Your eye on this is the difference between launching something
half-cooked and launching something the rest of the group will
actually enjoy using all summer. Anything you spot now is one
less embarrassment later.

— Craig
