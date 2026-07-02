# Batch 35 — "Last night" as the single morning hub

Status: Implemented on `feat/batch-35-last-night-hub`; awaiting review/closeout. Decision #106.
Tier: 🟢 Mid (frontend-only component work over data already on the payload).

## Goal

Make the "Last night's sleep" card the one morning read: fold the baseline
**range** into the comparison table and tint last night's number by whether it
sat in range, then **retire the standalone `/baselines` page**; and pull the
*retrospective* overnight-room read into the same card so sleep and the room it
happened in are read together. The live fan/bedroom controls stay in the evening
card — this batch only moves *last night's* context, never *tonight's*.

Combines two of Craig's 2026-07-01 Home ideas: (1) "add baseline values to the
sleep table and colour the number, so the separate baselines page isn't needed"
and (2) "make the temperature section part of last night's sleep."

## Why (the problem)

- **The baseline range lives on a second page for no reason.** Home's
  `MetricComparisonTable` already receives the full `metricsVsBaselines` rows —
  including `lowerQuartile` / `upperQuartile` / `baselineMedian` — and already
  computes the in/out-of-band tone (`baselineDiff`). The only thing the
  `/baselines` page (`MetricsBaselineTable`) adds is the raw range column
  ("48–55") and a Normal/High/Low status derived from the **same** quartile
  logic. That logic is literally duplicated between the two components
  (`HIGHER_IS_BETTER` / `LOWER_IS_BETTER` / the 3 % tolerance band). So the page
  is a near-duplicate reachable only from the sleep card's chevron — not from any
  tab or the More menu (verified: `/baselines` appears only in `App.tsx`'s route
  table and the two `SleepSnapshotCard` links).
- **Last night's room is split from last night's sleep.** Sleep quality and room
  temperature are correlated (Batch 34 exists precisely to test that). Yet the
  overnight-room read (`OvernightGlance`, with the Batch 33 room verdict badge)
  renders as a *sibling* below the sleep card, and the overnight low is a stat in
  the evening `BedroomSummaryCard`. The retrospective half of the bedroom story
  belongs *with* the night it describes.

## Product shape

**One card, three stacked reads:** sleep headline → metrics-vs-baseline table
(range folded in, number tinted) → last-night room line (verdict badge + glance).

### 1. Baseline range folded into the table, number tinted

Rework `MetricComparisonTable` so each row reads:

| Metric | Last night | vs your age |
|---|---|---|
| Resting HR | **48** bpm · _normal 46–52_ | 3 below (green) |

- "Last night" shows the value **tinted by the baseline in/out-of-band tone**
  (green in range, amber out), with the baseline range as a muted sub-line
  beneath it (`formatBaseline`'s `lower–upper` string, reused).
- The old **"vs your normal" column is dropped** — a tinted number plus the
  visible range already answers "is this in my normal?", so the separate diff
  column is redundant. This keeps the table at **three columns**, which is what
  makes it read cleanly on a phone; it does not grow to five.
- Colour stays an **enhancement, not the only signal**: the "vs your age" cell
  keeps its ✔/⚠ icon + text, and the range is always shown as text, so the read
  survives for a colour-blind user or a greyscale screenshot. (This preserves the
  Batch 28 accessibility stance.)
- Rejected alternative: keep "vs your normal" and add a fourth "Baseline" column.
  Five columns total is too tight on Mark's phone; the tint + sub-line carries the
  same information in less width.

### 2. Retire the `/baselines` page

- Delete `pages/BaselinesPage.tsx` + `pages/BaselinesPage` route in `App.tsx`
  (and its `lazy` import) + its test.
- Remove the `baselinesLink` `DetailLinkCard` from `SleepSnapshotCard` (both the
  prop and the two call sites in `DashboardPage`). Keep the **"Full morning
  brief" (`/brief`)** link — that one is the only Home entry point to the full
  read and is unaffected.
- `MetricsBaselineTable.tsx` becomes dead once the page is gone. Its exported
  `MetricBaselineRow` **type** is still imported by `MetricComparisonTable` and
  `DashboardPage`, so move that type into `MetricComparisonTable.tsx` (or a small
  `types` module) and delete `MetricsBaselineTable.tsx` + `.test.tsx`. Nothing is
  lost: the reliability note (`excludedSampleCount` / `reliabilityStartDate`)
  already exists in `MetricComparisonTable`.
- This **partially reverses Batch 28's** deliberate "keep the `/baselines` detail
  link" choice (#98). Record the reversal in the new decision: the range is now
  inline, so the detail page no longer earns its place.

### 3. Last-night room read into the sleep card

- Move `OvernightGlance` (already fetched via `useBedroomOvernight`, already
  carrying the Batch 33 `roomVerdict` badge + the "19→21 °C, fan ran 3.5 h" glance
  text) from a Home sibling **into** `SleepSnapshotCard`, rendered under the
  table. It stays a link through to `/bedroom` for the full chart.
- The sleep card now owns **last night's** room summary (verdict + glance, and
  optionally the overnight low as a stat). The evening `BedroomSummaryCard` keeps
  **tonight's live** read — indoor-now, thermostat, fan control — i.e. the
  prospective half. This keeps the temporal split the code already comments on
  (`OvernightGlance` docstring): retrospective pairs with sleep, live/forward
  stays in the evening card.
- **The one judgment call for `/batch-start` to settle with Craig:** whether the
  "Overnight low / Wind" stats also move out of `BedroomSummaryCard` into the
  sleep card, or stay as forward-weather context in the bedroom card. Default
  recommendation: move *overnight low* to the sleep card (it's retrospective),
  leave *wind* + live stats in the bedroom card.

## Backend

None. `metricsVsBaselines` (with quartiles) and the bedroom-overnight summary are
already on their respective payloads. No new endpoint, no migration.

## Verification (planned)

- Web unit tests: table renders the range sub-line and tints the number by band
  (in-range → success tone, out → warn tone); "vs your normal" column is gone;
  "vs your age" ✔/⚠ preserved; the room glance + verdict badge render inside the
  sleep card; the `/brief` link stays and the `/baselines` link is gone.
- Delete `BaselinesPage.test.tsx` and the `/baselines` route test; update
  `DashboardPage.test.tsx` for the merged card and the removed sibling glance.
- Web lint + build (`tsc` + Vite) clean; backend suite untouched (run once to
  confirm no incidental break).

## Deferred / non-goals

- **No change to tonight's live bedroom/fan card** beyond (optionally) shedding
  the overnight-low stat to the sleep card — the fan controls and live indoor
  read stay put.
- No backend change, no migration, no new endpoint.
- Does not touch the Today card (Batch 36) or the Home collapse model (Batch 37).
