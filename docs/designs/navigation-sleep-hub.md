# Batch 49 — Navigation & IA refactor + Sleep hub

Status: Specced, not started. Frontend-only, no migration.
Decision assigned at `/batch-start`.
Tier: 🟢 Mid (well-specified component/route work — the IA judgment calls are
settled here). **Revises the shipped nav model** (`navConfig.ts` three-primary
bar), so cite it.

From the 2026-07-03 UX read of the shipped app (Craig + Claude), the first of two
Home/nav batches: give the daily loop's **sleep** half a nav home and re-tier the
"More" menu. Batch 50 handles the Home page itself.

## Goal

Make the nav tell the two-loop story instead of the training half alone: give the
**sleep** side of the daily loop (last night's sleep, tonight's projection, the
bedroom fan the Batch 27 autopilot drives) a real front door, re-tier "More" so
genuine user-value destinations aren't buried next to developer tooling, and
de-jargon the labels for a 57-year-old non-technical daily user.

## Why (the problem)

The shipped primary tab bar is **Home / Plan / Trends** (`PRIMARY_TABS` in
`apps/web/src/lib/navConfig.ts`), rendered by `TabBar` (mobile) and `TopBar`
(desktop).

- **Sleep has zero nav presence.** `/brief` (morning read) and `/bedroom` (fan +
  overnight chart) are reachable **only** through Home detail-links. For a
  "fitness **and** sleep coach" whose second loop *is* sleep→training, half the
  product is invisible in the nav.
- **Trends holds a precious primary slot** but is a browse-when-curious surface
  ("effortless, **not empty**" — Mark enjoys the data), not a daily-loop one.
- **"Plan" (`/delivery`) overlaps Home's Today card** — both add/skip/swap/edit
  workouts (Batch 29/30) — and the generic label invites "do I manage my week on
  Home or on Plan?".
- **"More" mixes value with tooling.** Reviews (a real output of the *block* loop)
  sits in the same "Coach tools" group as Handover, Coach state, and Tests; and
  several labels are engineer-speak (`Tests`, `Coach state`, `Plan builder`).

## Product shape

Primary tabs become **Home / Week / Sleep**; everything else moves under **More**,
re-tiered into value vs setup.

```
PRIMARY_TABS: Home (/) · Week (/delivery) · Sleep (/sleep, NEW)

MORE_GROUPS
  For you   Reviews (/reviews) · Trends (/trends, demoted) · Holiday (/holiday)
  Coaching  New training block (/builder) · Experiments (/experiments)
  Setup     Coach memory (/coach-state) · Handover (/handover) · Settings (/settings)
```

New **`/sleep` hub** — two views, **Last night | Tonight** — composed from
components that already exist (no new feature, no new data):

- **Last night:** sleep-vs-baseline table (`MetricComparisonTable`), the
  overnight room glance + verdict (`OvernightGlance`), the overnight
  temp/fan/hypnogram chart (`BedroomOvernightChart`, moved off `/bedroom`), and a
  link into the full morning brief (`/brief`).
- **Tonight:** the evening sleep projection (`SleepPrepBody`, Batch 46) + the live
  bedroom/fan read and Auto / Off·Low·Med·High controls (`BedroomBody`, Batch 27).

`/bedroom` is **absorbed**: redirect → `/sleep` (Tonight). `/brief` stays as the
deep morning read, linked from Sleep.

## Frontend

- `lib/navConfig.ts`: new `PRIMARY_TABS` (Home / Week / Sleep) and re-tiered
  `MORE_GROUPS`; `SECONDARY_PATHS` recomputes automatically. `TabBar`,
  `MoreMenu`, and `TopBar` already render off this config generically — **no
  structural change** to any of the three.
- New `pages/SleepPage.tsx` with a Last night | Tonight segmented control. To feed
  it, **extract** the sleep/bedroom body components currently defined *inside*
  `DashboardPage.tsx` — `SleepSnapshotBody`, `SleepPrepBody`, `BedroomBody`,
  `OvernightGlance` — into reusable modules so both Home (compact) and `/sleep`
  (full) render the same pieces; move the `BedroomOvernightChart` mount off
  `BedroomPage`.
- `App.tsx`: add the `/sleep` route; redirect `/bedroom` → `/sleep`. Retire
  `BedroomPage` (or thin it to the redirect).
- Label de-jargon: **Plan→Week**, **Tests→Experiments**, **Plan builder→New
  training block**, **Coach state→Coach memory**; **keep "Handover"** — it is
  Mark's own word (the product thesis: he writes handover docs by hand).

## Backend

None. `/sleep` composes the existing `/api/v1/daily-loop` +
`/api/v1/bedroom/overnight` queries. No new endpoint, no payload change, no
migration.

## Sequencing / dependencies

Independent of Batch 50 and can ship first (nav is the load-bearing change).
Batch 50's evening Home cards deep-link into this Sleep hub, so 49-before-50 is
tidiest but not required (they can fall back to `/bedroom` if 49 hasn't landed).

## Decisions to record at `/batch-start`

- **Demote Trends to More** to free a primary slot for Sleep (kept one tap away
  under "For you"). Alt considered: 4 primary tabs + More — rejected (cramped
  phone bar).
- **Absorb `/bedroom` into `/sleep`** via redirect (one sleep destination) rather
  than keeping a separate deep page.
- **Rename Plan→Week** and the de-jargon set; **keep "Handover"** (Mark's
  vocabulary).
- Cite that this **revises the shipped nav model** (`navConfig.ts` three-primary
  bar) for future readers.

## Verification (planned)

- Nav tests: primary bar renders Home / Week / Sleep; "More" lights active for
  every secondary path incl. the new groups; renamed labels present; the desktop
  `TopBar` dropdown mirrors the mobile `MoreMenu`.
- New `SleepPage.test`: Last night renders the metrics table + overnight chart;
  Tonight renders the projection + fan controls; `/bedroom` redirects to `/sleep`.
- Home still renders after the body-component extraction (no visual regression on
  the compact cards).
- Web lint + build clean; backend suite untouched.

## Deferred / non-goals

- No new sleep *data* or endpoint — pure composition of existing surfaces.
- Home's own section set is unchanged here — **Batch 50** handles the Home page.
- No migration, no backend change.
