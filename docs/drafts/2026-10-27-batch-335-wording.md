# Batch 335 — the words Mark sees (for Craig's sign-off)

**Signed off by Craig, 27 Oct 2026, about 20:25 London:** "I sign off the exact words in the #404 draft (docs/drafts/2026-10-27-batch-335-wording.md). Merge after both CI waves are green, outside 06:00-11:00, regenerating nothing."

Batch 335 makes a swap or move carry the planned ride, never another morning's easing, and
makes the screens say what Zwift holds. These are every new Mark-facing line, word for word,
and the one line that goes. Nothing about the call changes. `apps/web/src/lib/liveRide.test.ts`
holds the app's lines to this file.

## 1. What Zwift holds (Home's session card, Week, the brief page)

Shown only when the ride on Zwift is not the plan row's own. The name in quotes is the
workout's name as Zwift shows it; minutes and the top effort come from the ride itself.

When the ride is a change made for this day (an easing he approved, a pick, his own edit):

> On Zwift: “Recovery substitution: Sweet Spot (1 × 30 min @ 89%)”, 29 min, up to 60% FTP.

If rides are not reaching Zwift (intervals.icu paused or unlinked, or can't be checked), the
line starts "Sent to intervals.icu:" instead of "On Zwift:".

When the ride belongs to another day or an older version of the plan (10 Oct's case), the same
line, then:

> That is not the ride planned for this day.

with one button:

> Put the planned ride on Zwift

and, once it has gone:

> The planned ride is on Zwift.

(or "The planned ride is sent to intervals.icu." while rides are not reaching Zwift).

The daily check at 03:15 also puts such a ride back on its own and tells you, so Mark should
rarely see this.

## 2. One choice for one session (the Today list on Home and the brief page)

On a hard morning the app can offer two fixes for one session: move it, or ride the easier
version today. They now share one card, headed:

> Choose one

> Move it or ride the easier version today, not both. Taking one takes the other away.

The two existing rows ("Move … Apply" and "Substitute recovery … Approve") sit inside it,
unchanged. Once he takes either, the other goes.

On Home's "Rearrange the week" card, while the easier ride is also on offer, one line is added
under the card's existing sentence:

> Or ride the easier version below instead. Taking one takes the other away.

## 3. Removed

Batch 334.5's stopgap line goes, and Home's swap offers come back for a changed ride:

> ~~The ride on Zwift was already changed today. Moving it could carry that changed ride to another day.~~

## Not words, but visible

- The move offer, its Today-list row and the week's mix ("Sweet Spot 0/1 → Sat") follow the
  plan as it stands, so they no longer linger after he has moved the session.
- The 10:45 "Something changed" message no longer announces a shortfall he has already fixed.
- Craig, not Mark, hears about a ride the daily check put back (a Sentry `admin_alert`,
  kind `live_ride_mismatch`).
