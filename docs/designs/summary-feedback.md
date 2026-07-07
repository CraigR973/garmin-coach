# Design: Rate & correct any summary — subjective read in, corrections out (Batches 63–64)

Mark's 2026-07-07 ask: let him rate the accuracy of any summary the app generates —
sleep, workout, the morning verdict, or the coach's suggested workout edits — and
tell it when it's wrong.

## The ask, and the reframe

Challenged and reframed with Craig before scoping:

- **At n=1 a rating pipeline has no aggregate to learn from.** One user tapping
  stars never reaches statistical volume, so the value is not the *score* — it is
  the *correction* ("I actually slept fine, my watch missed my 03:00 wake"). One
  sentence of ground truth outweighs a hundred thumbs.
- **Capture the subjective read cheaply *before* the verdict, and correct *after*.**
  Most "the summary is wrong" moments are really "the Garmin data disagrees with how
  I feel" — better to feed his read in up front (so the coach misfires less) as well
  as let him push back afterward.
- **Mark named the real constraint:** a quick morning check-in "will be
  significantly less than what I'm doing now." The input must *undercut* his current
  manual routine, not add to it. Every field on the check-in spends against that
  budget. This is the "guide, not magic wand" thesis in his own words: a coach that
  takes a little ongoing input and adjusts, not a one-shot oracle.

Mark agreed with the combination of (1) a lighter check-in and (2) correcting reads
when they're off.

## What the code already gives us

1. **Every AI summary is one shape: an `analyses` row** (`coaching.py:413`) — stable
   UUID + `analysis_type` (`morning`, `post_workout`/`_walk`/`_strength`/
   `_flexibility`, `weekly_review`, `monthly_review`, `seasonal_trend`) +
   `output_markdown` + the `context_packet` that fed it. One feedback primitive keyed
   to `analysis_id` therefore covers the whole app in a single build.
2. **The subjective-read → verdict loop already exists.** The manual-entry PUT fires
   `regenerate_after_morning_checkin` (`daily_loop.py:1123`), so lightening the
   check-in is a UX job, not new plumbing. The current `/check-in`
   (`CheckInPage.tsx`) is the heavy multi-card form (typed 0–10, feel, notes, BP,
   supplements, food, per-workout adherence) that Mark is escaping.
3. **No feedback/rating table exists** — the correction primitive is net-new.
4. **Caveat — the `/sleep` review is client-side** (`sleepReview.ts`), *not* an
   `analyses` row, so it has no server id to attach feedback to. It defers: sleep
   feedback piggybacks on the day's morning analysis (which already carries the
   sleep read) rather than getting its own control in v1.

## What we build

### Batch 63 — Lighten the morning check-in (🟢 Mid, frontend)

The engine is already there; this is about friction.

- **63.1** Make the `/check-in` default a **quick check-in**: a tap button-group for
  overall (writes `manual_entries.subjective_score`) + 2–3 one-tap chips (slept well
  / energy / niggle) folded into `feel`/`notes`. BP, supplements/food, and
  per-workout adherence move behind a "More" disclosure. Reuses
  `manualEntryInputSchema` + `PUT /api/v1/daily-loop/{date}/manual-entry` — **no new
  endpoint, no migration** (quick inputs map onto existing columns).
- **63.2** Confirm the quick save still fires `regenerate_after_morning_checkin`
  (inherited via the manual-entry PUT), so the verdict + eased ride still reshape
  from his read.
- **63.3** One-tap quick-check-in affordance on Home; stays optional (Batch 60 /
  #134) — no blocking `!manualEntry` rung reintroduced.
- **63.4** Web tests + gates.

### Batch 64 — Rate & correct any summary (🔴 High, full-stack)

- **64.1** New `feedback` table + migration `013`: `id` uuid PK, `user_id` →
  `profiles` (CASCADE), `analysis_id` → `analyses` (CASCADE), `kind`
  (`summary`|`suggestion`), `rating` (short per-axis string), `correction_text` Text
  nullable, `created_utc`; unique `(user_id, analysis_id)` for upsert; index
  `(user_id, analysis_id)`. Keyed to `analysis_id` (not a generic `target_type`) for
  real referential integrity, since every summary is an `analyses` row.
- **64.2** `PUT /api/v1/analyses/{analysis_id}/feedback` (upsert) in the standard
  `{data, meta, errors}` envelope, **user-scoped** (404/403 if the analysis isn't the
  caller's); `feedbackInputSchema`/`feedbackSchema` in `packages/shared`; daily-loop
  serializers surface existing feedback on each analysis so the widget shows current
  state.
- **64.3** Reusable `FeedbackControl` component: one-tap axis buttons; a negative tap
  discloses an optional "what did we get wrong?" textarea. Mounted on `VerdictHero`,
  the post-session read cards, and `/reviews`.
- **64.4** Feed corrections forward: the morning + post-workout context-packet
  assemblers (`morning_analysis.py`) include the most recent corrections for that
  user so the next read can acknowledge/adjust; bump the affected `PROMPT_VERSION`.
- **64.5** Tests + gates.

## The two axes

Chosen per content type, because a suggestion can't be "inaccurate":

- **Summaries** (verdict, sleep/workout reads, reviews) → **spot on / a bit off / way
  off** (`kind = summary`).
- **Suggested edits** (the verdict's plan adjustments) → **agree / not for me /
  already doing** (`kind = suggestion`). In v1 these attach to the morning analysis
  that carries the adjustment — no separate suggestion entity.

The rating is the *doorway*; a negative tap reveals the correction box, and the
free-text correction is the payload that actually feeds generation.

## System interactions & safety

- **Verdict invariants untouched.** Corrections are context the next read *considers*
  — they never override the Red floor, the #133 soft-sleep rule, the #135
  Poor-readiness gate, or Red-never-VO2. The prompt weighs feedback; it does not
  obey it.
- **User-scoping (RLS-adjacent).** A user can only rate their own analysis; the write
  validates ownership. Feedback rows are per-user.
- **n=1 → no aggregation.** No rating dashboard, no trend view, no analytics. Just
  capture, surface, and feed forward.

## Boundaries (non-goals)

- No rating dashboard / aggregation.
- No auto-regenerate on correction — **feed-next-read only** (the manual-entry regen
  path already exists if we want immediate regen later).
- `/sleep` client-side review has no control in v1 (piggybacks on morning analysis).
- No separate suggestion entity — suggestion feedback attaches to the morning
  analysis.

## Verification plan

- **63:** quick-form render/save, chip→column mapping, regen-still-fires; web +
  backend + shared gates.
- **64:** migration/model, endpoint upsert + user-scoping (403/404), shared schema,
  widget render/axis/correction reveal, packet-includes-recent-corrections; full
  gates; closeout prod smoke on merge SHA.

## Resolved defaults (decided at spec time; `/batch-start` may adjust)

- Two batches, **63 then 64** (check-in relief first).
- Corrections **feed the next read**, not auto-regenerate.
- **Two axes** by content type.
- Feedback keyed to `analysis_id`; endpoint `PUT /api/v1/analyses/{id}/feedback`;
  migration `013`; proposed Decision **#137**.
