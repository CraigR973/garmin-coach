# Batch 50 — Action-first Home

Status: Specced, not started. Frontend-only, no migration.
Decision assigned at `/batch-start`.
Tier: 🔴 High (revises the shipped Home selection model — Batch 37 collapse +
Batch 48 phase→primary — and adds an action-override layer; needs judgment on the
action priority and the override rule).

Second of the two 2026-07-03 Home/nav batches. Batch 49 gives sleep a nav home;
this catches the **Home page** up to being push-first.

## Goal

Make the single expanded section, and a new "next action" strip, driven by **what
needs Mark** first and time-of-day second — not time alone. Surface pending
actions regardless of phase, and let a collapsed section signal when it needs a
tap.

## Why (the problem)

Since Batch 45 the app is **push-first** — the morning verdict and every
post-workout read push the moment they land — so Mark now arrives on Home to
*act*. But Home is still time/data-phase-driven:

- The one expanded section is chosen by `primarySection(phase)` in
  `lib/homeSections.ts` — by time-of-day / data stage. An **actionable** item in a
  *non-primary* collapsed section is invisible until expanded. Concretely: a
  pending coach adjustment (`workout.delivery.changed && isBike && !ignored`,
  Batch 29) lives in the Today card, but when the phase makes `afterRide` primary,
  the one thing needing a decision is collapsed.
- The only explicit CTA is a lone **"Check in"** button; the morning act-flow
  (read verdict → approve/adjust → check in) is implicit and scattered.
- **Collapsed summaries are state-blind:** `todaySummary` is just the session
  titles, so a collapsed Today reads identically whether or not the coach changed
  the plan.
- The **verdict renders twice** — `VerdictHero` plus the Today section header
  `Badge`.

## Product shape

- **A "Next" strip** directly under `VerdictHero`: one context-aware primary
  action resolved from the payload, replacing the lone Check-in button (which
  becomes the fallback — still reachable in the Today footer + on Sleep).
- **Action-aware expansion:** the section holding the top pending action is the
  expanded one, **overriding** the phase primary. Still exactly one expanded —
  chosen by *need*, then *time*.
- **State-signalling collapsed summaries:** a collapsed section carries a warning
  tone + a dot in its header when it needs action.
- **De-dupe the verdict:** drop the Today header badge; `VerdictHero` is canonical.
- **Evening defers to Sleep** (given Batch 49): Home's `tonight` / `bedroom`
  become compact cards that deep-link into the Sleep hub rather than duplicating
  full controls.

### The next-action priority (deterministic, payload-only)

1. a bike workout with a pending coach change → **"Review today's eased ride"** →
   expand `today`.
2. a `postWorkoutAnalyses` item with `postRideCheckIn == null` → **"Log how your
   ride felt"** → expand `afterRide`.
3. `!manualEntry` (no check-in today) → **"Check in"** → `/check-in`.
4. evening & `sleepProjection.tone === 'protect'` → **"Protect tonight's sleep"**
   → `/sleep` (Tonight).
5. none of the above → a quiet **"You're all set"**.

## Frontend

- New pure `lib/homeActions.ts`: `nextAction(data, { phase, isEvening })`
  returning `{ label, to?, sectionKey?, tone }` from the priority list above —
  fully unit-testable, payload-only.
- `lib/homeSections.ts`: `primarySection` gains an override —
  `actionSection(nextAction) ?? primarySection(phase, { hasRide })` — so a
  pending-action section wins over the phase primary. `orderedSections` /
  evening-float logic otherwise unchanged.
- `components/CollapsibleSection.tsx`: header accepts a `tone` and renders a
  `--fill-warning` dot when `tone === 'warning'`.
- `pages/DashboardPage.tsx`: render the Next strip; make the section-summary
  helpers (`todaySummary`, `afterRideSummary`, …) return `{ text, tone }` (Today →
  warning on a pending change; After-your-ride → warning on an unlogged ride
  check-in); remove the Today verdict `Badge`; make the `tonight` / `bedroom`
  bodies compact and deep-link to `/sleep`.

## Backend

None. Every signal — `delivery.changed`, `postRideCheckIn`, `sleepProjection.tone`,
`manualEntry` — is already on `/api/v1/daily-loop`. No new endpoint, no migration.

## Sequencing / dependencies

After **Batch 49** (the evening deep-links target the new Sleep hub; without 49
they fall back to `/bedroom`). Otherwise self-contained.

## Decisions to record at `/batch-start`

- **Action overrides phase always**, not morning-only — an unactioned adjustment
  matters at 18:00 too.
- The **next-action priority order** above (pending change > unlogged ride
  check-in > daily check-in > protect-sleep > all-clear).
- **One primary action** in the strip (CDS restraint); Check-in demoted to the
  fallback.
- This **revises the Batch 37/48 phase→primary selection** by adding an action
  override on top; the phase remains the fallback (cite for future readers).

## Verification (planned)

- Pure `homeActions.test`: each priority rung fires in order; ties resolve
  deterministically; all-clear when nothing is pending.
- `homeSections.test`: the action override beats the phase primary; ordering and
  the evening float are otherwise preserved.
- `DashboardPage.test`: the Next strip renders the right CTA per state; the
  action's section is expanded even against the phase primary; a collapsed Today
  shows the warning dot + copy on a pending change; the verdict renders once;
  offline still renders. (These encode the current phase→section expectations —
  updated by this batch, as the Batch 48 pinned-section/evening tests were.)
- Web lint + build clean; backend suite untouched.

## Deferred / non-goals

- No new push/notification logic (that is Batch 45) — this only *surfaces* the
  action on Home.
- No backend/payload change; no persistence of manual expand/collapse state.
- A multi-action queue — only the single top action is surfaced; deferred.
