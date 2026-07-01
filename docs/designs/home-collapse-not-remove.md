# Batch 37 — Collapse-not-remove Home sections

Status: Specced (not started). Decision #108 (assigned at `/batch-start`).
Tier: 🔴 High (revises a shipped Home model — the Batch 24 phase-swap — and needs
judgment on what stays expanded per state, collapse persistence, and whether time
nudges ordering).

## Goal

Change Home from **swapping whole section-sets by phase** to **keeping the
sections present but collapsing the ones that aren't primary right now** — so
nothing Mark might want ever disappears from Home; it's just one tap away. Keep
the driver = **data state** (Batch 24's `useDailyPhase`), *not* the clock; let
time only *nudge ordering*, never add or hide a section.

From Craig's 2026-07-01 Home idea: "does only showing certain views by time of day
make sense? maybe we just collapse them rather than totally remove them." My
review's answer, recorded here: collapse over remove (object permanence), and keep
state — not the clock — as the driver.

## Why (the problem)

Batch 24 made Home single-phase and read-first (the "read-first Home" referenced
in DECISIONS #91 / #97). `DashboardPage.tsx` renders **exactly one** of three
phase blocks, and the other phases' sections are simply **absent**:

- `pre_ride` / `rest_day` → verdict, sleep snapshot, overnight glance, day plan;
- `post_ride` → verdict, post-ride analysis, tomorrow, sleep-prep, bedroom.

So the day's transitions **remove** things: once Mark rides, the sleep snapshot
and the day-plan card vanish from Home entirely. If at 3 pm he wants "how did I
sleep?", it's gone from Home (still on `/brief`, but he has to know that). That's
the object-permanence cost of a remove-model — the thing Craig is reacting to.

Two clarifications this batch bakes in:

1. **It was never actually time-of-day driven.** Batch 24 keys off *state* (has a
   ride analysis landed today?), not the clock — which is the more robust signal
   and should stay. Don't hide the day's workout at 6 pm just because it's
   evening; Mark might not have ridden yet.
2. **Remove was deliberate** (Batch 24's "surface the one step that matters now").
   This batch keeps that *focus* — one primary section per state — but pays back
   the permanence cost by collapsing rather than dropping the rest.

## Product shape

Home always renders the **full section set**; the current state decides which
**one** is expanded and how the rest are ordered.

- **Primary (expanded) per state:**
  - pre-ride → **Today** (the workout to act on);
  - post-ride → **After your ride** (the analysis);
  - rest day → **Last night** (the read, since there's nothing to ride).
- **Secondary (collapsed):** every other section renders as a collapsed panel
  with a **one-line summary in its header**, so a glance still informs without
  expanding (e.g. collapsed "Last night's sleep — 7 h 12 m · REM normal · room
  Green"; collapsed "After your ride — Tempo 60 min, recovery on track").
- **Nothing is hard-hidden** — this *strengthens* Batch 24's "no hard-hide"
  principle: previously off-phase sections were absent from Home (reachable only
  via tabs/detail routes); now they're present-but-collapsed, so Home itself keeps
  object permanence.
- **Time nudges order, not presence.** After ~20:00 local, float the
  Tonight / bedroom-prep section up (it's what's next); it is never *added* or
  *removed* by the clock — it's always present, the clock only changes where it
  sits. This is the honest, bounded reading of Craig's "by time of day" that
  doesn't reintroduce the fragility of clock-gated content.

## Frontend

- Introduce a reusable **`CollapsibleSection`** (shadcn `Collapsible` /
  `Accordion`, already installable in the UI kit) — header with the one-line
  summary + a chevron, body lazy-rendered when open. Data-heavy bodies (e.g. the
  bedroom-overnight query) stay lazy so a collapsed section costs nothing.
- Rework `DashboardPage` so it renders the **superset** of sections once, then
  chooses `expanded` from `useDailyPhase` and an ordering array (with the evening
  nudge). Remove the three near-duplicate phase branches in favour of one ordered
  list of sections with `expanded`/`collapsed` state.
- **Collapse state is derived, not sticky, by default** — each Home load reflects
  the current state. (A future enhancement could remember a user's manual
  expand/collapse for the session; out of scope here to avoid a stale-open-panel
  feeling.)
- Keep `useDailyPhase` as the single source of truth for "what's primary" — no
  clock in the *selection*, only in the *ordering* nudge, so the behaviour stays
  correct whether Mark rides at 06:00 or 18:00.

## Backend

None. Same `/api/v1/daily-loop` payload; the bedroom-overnight glance keeps its
existing separate query. No new endpoint, no migration.

## Sequencing / dependencies

Ships **after Batch 35 and Batch 36**. Those two shrink Home to a few rich cards
(sleep + baselines + room merged; Today unified), so a collapse model reads as a
tidy short list of panels rather than a wall of drawers. Doing this first — over
today's many sibling cards — would produce exactly the over-collapsed "directory
of drawers" this batch is meant to avoid.

## Decisions to record at `/batch-start`

- **Supersedes the Batch 24 remove-model** for cross-phase sections: Home keeps
  them present-but-collapsed instead of absent. Batch 24's single-primary *focus*
  and its data-state (not clock) driver are **kept**; only "absent" becomes
  "collapsed", plus a clock-driven *ordering* nudge. Cite the "read-first Home"
  decisions (#91 / #97) that assume the Batch 24 model so future readers see the
  shift.

## Verification (planned)

- Web unit tests: for each state (pre-ride / post-ride / rest-day), the right
  section is expanded and the rest render **collapsed but present** (assert the
  collapsed summary text is in the DOM); expanding a collapsed section reveals its
  body; the evening ordering nudge moves the bedroom/sleep-prep section up past
  20:00 without changing which sections exist; offline state still renders.
- Rewrite `DashboardPage.test.tsx` around the section list + expanded/collapsed
  assertions (replacing the phase-swap assertions).
- Web lint + build clean; backend suite untouched.

## Deferred / non-goals

- **No clock-gated content** — the clock never adds or removes a section, only
  reorders. State remains the driver.
- **No persistence of manual collapse state** across loads (possible later).
- Assumes the Batch 35 + 36 consolidations have landed; if they haven't, this
  batch should still ship but the "wall of drawers" risk is higher — hence the
  sequencing note above.
- No backend/payload change, no migration.
