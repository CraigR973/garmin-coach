# Design: In-app guided strength player (Batch 38)

**Status:** Specced, not started. Designed with Craig on 2026-07-01 from the idea
that strength sessions should be *coached through in the app*, exactly the way a
cycling workout is coached through in **Zwift** after the app delivers it — rather
than just shown on Home. Decision number assigned at `/batch-start` (next free
**#109**, after the #106–#108 reserved for the specced Batches 35–37). Sibling
batch: **Batch 39 (in-app flexibility video)**, which reuses this batch's session
log + reconciliation and only swaps the player (a video vs. an interval runner) —
so the data model here is designed generically for both from the start.

Builds on / reuses:
- The **bike delivery rail** as the conceptual template — `PlannedWorkout.structured_workout`
  (JSONB, `format == "bike"`) → `build_structured_workout_ir` → `build_intervals_payload` /
  `build_zwo_xml` → Zwift (`services/executable_coaching.py`). Strength is the same
  shape with a different `format` and a **different delivery target: the PWA itself**.
- The **strength watching-brief** (Batch 19, Decision #49/#80): `services/strength_brief.py`
  (`StrengthBriefService.brief`, pure `compute_strength_rollup`, `is_strength_activity`)
  reads `activities` where `exclude_from_recovery=True` and is **advisory only** —
  it never touches verdict/recovery. This batch feeds it a second source without
  breaking that isolation.
- **Day categorisation** — `services/workout_categories.py` / `lib/workoutCategories.ts`
  already map `strength_*` → `DAY_CATEGORY_WEIGHTS`; the player attaches to a weights day.
- The **Batch 8 hourly Garmin activity poll** (the existing trigger that lands new
  strength activities in `activities`) — reconciliation piggybacks the data it
  already syncs, no new cron.
- The **Batch 5 seed pattern** (KB + plan seeded on first `/coach-state` load) — the
  two strength templates are seeded the same deterministic way.

## Goal

When Mark has a weights day, give him an **in-app guided player** that walks him
through the session in real time — current exercise, set number, a **work
countdown** (timed sets) or **rep target** (bodyweight), an auto-advancing **rest
countdown**, and "up next" — the strength equivalent of Zwift playing a structured
ride. Today the app can only *show* a strength brief; it cannot run the session.

His decisions, agreed up front (2026-07-01):
- **Video for flexibility → Batch 39**, not here. This batch is strength only.
- **Logging = "both, reconciled":** the app records that he completed a guided
  session **and** reconciles it with the Garmin strength activity his watch
  produces, so the watching-brief counts each real session **exactly once**.

## The parallel that makes this mostly composition, not new invention

A strength session *is* a structured interval sequence — his own document proves
it (below). The app already has the machinery to represent and run structured
interval workouts for the bike; the only genuinely new pieces are (a) a strength
flavour of the structured shape, (b) a player that renders it **in the PWA**
instead of shipping it to an external app, and (c) a completion log that
reconciles with Garmin.

| Concern | Cycling (exists) | Strength (this batch) |
|---|---|---|
| Structured spec | `structured_workout` `format:"bike"` → `%FTP` IR | `structured_workout` `format:"strength"` → exercise/set/work-rest IR |
| Who guides it | **Zwift** (external), fed via intervals.icu | **In-app player** (the PWA is the delivery target) |
| Completion data | Garmin ride activity → `activities` | Garmin strength activity **+** in-app `guided_sessions` log, reconciled |
| Verdict/recovery | full bike verdict + recovery | **advisory only** — unchanged (#49/#80) |

## His two sessions, straight from the document

From `~/Downloads/Dad Fitness/Dumbbell & Bodyweight 19.06.26.docx` (the doc he
refers to in his App-Optimisations wishlist — "my Monday 20 Minute Dumbbell
session and Saturday 16 Min Bodyweight workout session"). These are the seed set;
authoring arbitrary strength workouts is out of scope (a builder is a later idea).

**Dumbbell workout (~20 min, timed).** Cardio warm-up 2:00, then 8 exercises, each
**3 sets × 30 s work**, 15 s rest between sets, 30 s rest before the next exercise:
Biceps Curl · Shoulder Press · Lying Triceps Extension · Bent-Over Reverse-Grip Row ·
Lying Fly's · Shoulder Matrix (a tri-set: Lateral Raise / Y Raise / Bent-Over
Reverse Fly, one movement per "set") · Lying Dumbbell Pullover · Spiderman Crunch
(no dumbbell).

**Bodyweight workout (~16 min, rep-based).** 3 rounds of a 5-move circuit —
Squat / Dead Bug / Mountain Climber / Glute Bridge / Push-Up — **10 reps each**,
30 s rest between rounds.

Progression rule from the doc (surfaced, not auto-applied): dumbbells → add weight;
bodyweight → add reps.

## Structured strength representation (`format:"strength"`)

Store each session in the existing `PlannedWorkout.structured_workout` JSONB — no
new workout column — as an ordered step list. Each step is one of:

- `{"kind":"warmup","label":"Cardio Warm Up","durationSec":120}`
- `{"kind":"work","exercise":"Biceps Curl","set":1,"of":3,"durationSec":30}` (timed) **or**
  `{"kind":"work","exercise":"Squat","round":1,"of":3,"reps":10}` (rep-based)
- `{"kind":"rest","durationSec":15}` / `{"kind":"rest","durationSec":30}`

Plus `{"format":"strength","mode":"timed"|"reps","title","estMinutes","progression":"weight"|"reps"}`.
A pure `expand_strength_steps(structured_workout)` flattens this into the exact
run order the player steps through (mirroring how `build_structured_workout_ir`
expands a bike workout) — fully unit-testable with no DB.

The two seed workouts are authored as this structure and seeded deterministically
(Batch 5 pattern), with `workout_type` `strength_dumbbell` / `strength_bodyweight`
so `category_for_workout_type` already routes them to a weights day.

## The in-app player (the Zwift-equivalent runner)

New PWA player component, reached from the **Today card on a weights day**
("Start session"), driven purely by the expanded step list:

- Shows current step: exercise name + `set X of Y` (or `round X of Y`), and either
  a large **work countdown** or the **rep target** with a manual "Done set" advance.
- **Rest steps auto-run a countdown** and auto-advance; a transition cue
  (short beep / vibrate via the existing PWA capabilities) marks work↔rest.
- Progress: overall "step n of N" + a thin progress bar; "up next" line.
- Controls: pause/resume, skip step, and end-early. On finish (or end-early past a
  minimum), it **POSTs a completion** to the session log.
- Player *state* (which step, remaining seconds) is local/client — a pure reducer
  over the step list — so it's testable and survives without the network mid-set.

**Entry-point dependency:** the Today card is being reworked by the *specced*
Batch 36 (Unified Today card). This batch attaches "Start session" to the Today
card **as it exists at build time**; if 36 has shipped first, it slots into the
`WorkoutRow` for the weights session — settle exact placement at `/batch-start`.

## Logging + reconciliation ("both, reconciled")

**New table `guided_sessions` (migration), designed for strength *and* flexibility**
so Batch 39 reuses it with no second migration:

| Column | Notes |
|---|---|
| `id`, `user_id` | standard |
| `planned_workout_id` | nullable FK — which planned session this was |
| `format` | `"strength"` \| `"flexibility"` |
| `workout_type` | e.g. `strength_dumbbell` |
| `started_utc`, `completed_utc` | when he ran it in-app |
| `duration_sec` | actual in-app elapsed |
| `source` | `"app_guided"` (constant for now) |
| `matched_activity_id` | nullable FK → `activities.id`; set when reconciled |

**Reconciliation is a pure match, applied on read — no new cron.** A strength
session Mark records on his watch already lands in `activities`
(`exclude_from_recovery=True`) via the Batch 8 poll. A pure
`match_guided_to_activity(session, activities)` links a `guided_sessions` row to a
Garmin strength activity for the **same user, same local day, start within
`MATCH_WINDOW`** (proposed ±3 h; a named, tunable constant). This runs at
brief-read time (deterministic, no write); optionally the link is also persisted
opportunistically during the hourly poll so the player can show "recorded on your
watch too" — an enhancement, not required for correctness.

## Strength-brief integration — count each session once

`StrengthBriefService.brief` today reads only `activities`. Extend it to **union
in `guided_sessions` rows whose `matched_activity_id` is null** (app-only sessions
with no Garmin record — e.g. he didn't wear the watch), mapped to the existing
`StrengthSession` value the pure `compute_strength_rollup` already consumes:

- Garmin-recorded session → counted via `activities` (as today).
- App-logged **and** matched to a Garmin activity → counted **once**, via the
  activity (richer: HR/load); the log is suppressed from the rollup.
- App-logged, **no** Garmin match → counted via the log.

App-only sessions have no Garmin `training_load`; use a simple duration-based load
proxy (or leave `None` — the rollup already tolerates null load). Decide at
`/batch-start`. **Recovery isolation is preserved:** the log, like the brief,
never feeds verdict/recovery (#49/#80) — it only enriches the advisory rollup.

## API

- `GET /api/v1/strength-session/{plannedWorkoutId}` (or fold onto the existing
  daily-loop payload) — returns the expanded strength step list for the player.
- `POST /api/v1/strength-session/{plannedWorkoutId}/complete` — writes a
  `guided_sessions` row (`started_utc`/`completed_utc`/`duration_sec`).
- Shared Zod schema for the step list + completion in `@coach/shared`.
- No change to the bike delivery routes.

## Phases

- **38.1** Strength structured representation (`format:"strength"` step schema) +
  pure `expand_strength_steps`; author + deterministically seed the two workouts.
- **38.2** `guided_sessions` table + model + Alembic migration (generic over
  strength/flexibility for Batch 39 reuse).
- **38.3** API: fetch expanded steps for a planned weights session; POST a
  completion; shared schema.
- **38.4** Reconciliation: pure `match_guided_to_activity` + `MATCH_WINDOW`;
  extend `StrengthBriefService` to union unmatched app logs (count-once);
  optional opportunistic persist in the Batch 8 poll.
- **38.5** Frontend: in-app guided player (timed + rep modes, rest countdown +
  cue, progress, pause/skip/end) reached from the Today card weights session;
  completion POST on finish.
- **38.6** Tests + green gates (below).

## Testing

- **Pure:** `expand_strength_steps` flattens both seed workouts to the exact run
  order (warm-up, per-set work/rest, per-round reps); the player reducer advances
  work→rest→next and handles pause/skip/end; `match_guided_to_activity` links
  inside the window and *not* outside it / not across users / not across days.
- **Count-once:** brief rollup with (a) only Garmin, (b) only app-log, (c) both
  matched (single count via activity), (d) app-log with no match (counted) —
  asserting no double-count and unchanged trend maths.
- **DB-backed:** POST complete writes one `guided_sessions` row; GET returns the
  step list for a seeded weights day; the brief endpoint reflects an unmatched
  app session and suppresses a matched one.
- **Frontend:** player renders a timed step and a rep step, auto-advances a rest,
  fires the completion POST on finish; Today-card "Start session" appears on a
  weights day only.
- Backend pytest/ruff/mypy pass; web lint/test/build pass; shared typecheck/tests.

## Non-goals / out of scope

- **No change to the bike/Zwift/intervals.icu rail** — strength is delivered to
  the PWA, never to Zwift.
- **No change to verdict/recovery** — strength stays advisory (#49/#80); the new
  log never feeds recovery signals.
- **No workout builder** — only the two seeded templates + progression display; a
  general strength-authoring UI is a later idea.
- **No flexibility video** — that is Batch 39, reusing this batch's `guided_sessions`
  table and reconciliation.
- **No new cron** — reconciliation is on-read (deterministic), with an optional
  opportunistic persist on the existing hourly poll.

## Open decisions to settle at `/batch-start`

1. `guided_sessions` column final shape + whether `training_load` proxy is
   duration-derived or left null for app-only sessions.
2. `MATCH_WINDOW` value (proposed ±3 h same local day) and whether the match is
   persisted opportunistically or computed on-read only.
3. Player entry point vs. Batch 36 — attach to the current Today card, or the
   reworked `WorkoutRow` if 36 has shipped first.
4. Whether the step list rides the existing `/api/v1/daily-loop` payload or a new
   `/strength-session` route.

## Safety / invariants preserved

- Strength remains **advisory-only**; verdict and recovery are untouched (#49/#80).
- The bike delivery contract (propose → approve → push, Decision #29) is untouched.
- Reconciliation guarantees **exactly one** count per real session in the brief.
- No secrets, no external delivery — the strength "player" runs entirely in-app.
