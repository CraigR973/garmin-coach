# Design: In-app flexibility video player (Batch 39)

**Status:** Specced, not started. Designed with Craig on 2026-07-01 as the sibling
of **Batch 38 (in-app guided strength player)**: the same "coach him through it in
the app" idea, but flexibility's equivalent of the guiding Zwift/interval runner is
a **follow-along video** he plays in-app. Decision number assigned at `/batch-start`
(next free **#110**, after Batch 38's #109). **Sequenced after Batch 38** — it
reuses Batch 38's `guided_sessions` log + reconciliation and only swaps the player.

His decisions, agreed up front (2026-07-01):
- **Video source = upload a file.** He supplies an actual video file; the app hosts
  it and streams it in-app (not a YouTube embed, not a link-out).
- **Logging = "both, reconciled":** the app records the completed in-app session and
  reconciles it with any Garmin record so history shows one session, not two.

Builds on / reuses:
- **Batch 38's `guided_sessions` table** (deliberately made generic over
  `format ∈ {strength, flexibility}`) + its pure `match_guided_to_activity`
  reconciliation — no second session-log migration.
- **Day categorisation** — `services/workout_categories.py`
  (`WORKOUT_TYPE_FLEXIBILITY = {"mobility"}`, `DAY_CATEGORY_FLEXIBILITY`) and
  `lib/workoutCategories.ts` already route `mobility` → a flexibility day; the
  player attaches there.
- **Batch 5's admin editor** (`/coach-state`, admin-only retained-state surface) as
  the pattern for the video-upload/replace admin flow.
- The **Batch 8 hourly Garmin poll** as the source of any Garmin-recorded session to
  reconcile against.

## Goal

On a flexibility day, let Mark **play his flexibility routine as a follow-along
video inside the app** and have that session recorded — instead of flexibility
being just an unactioned "mobility" label on the plan. The video is, for
flexibility, what Zwift is for the bike and the interval runner is for strength:
the thing that guides the session in real time.

## The parallel, and what's genuinely new here

Batch 38 established: a non-bike session is *coached in the PWA* and *logged +
reconciled with Garmin*. Flexibility inherits almost all of that. The only new
concern this batch actually introduces is **hosting and playing an uploaded video
file** — everything else (the log, the reconciliation, the day plumbing, the
completion action) is Batch 38 machinery with `format:"flexibility"`.

| Concern | Strength (Batch 38) | Flexibility (this batch) |
|---|---|---|
| Who guides it | in-app interval runner | in-app **video player** |
| Content | seeded step list (`structured_workout`) | **uploaded video file** (hosted) |
| Session log | `guided_sessions` (`format:"strength"`) | `guided_sessions` (`format:"flexibility"`) — **reused** |
| Reconciliation | `match_guided_to_activity` → strength brief | `match_guided_to_activity` → adherence/history (**no** brief yet) |

## What exists vs. the gap

- `mobility` already classifies to `DAY_CATEGORY_FLEXIBILITY` in both the API and the
  web category helpers (Batch 30 note: "`mobility` maps to flexibility"). So a
  flexibility day already renders as such — there is just **nothing behind it**.
- **The gap:** no hosted video, no player, no completion record for flexibility.

## Video hosting — the one real new piece

He uploads a video file; it must be stored **outside Postgres** (the Supabase DB is
on the shared free **500 MB cap**, DECISIONS #34 / STATUS gotcha — a video would
blow it) in **object storage**, served to the `<video>` element via a
**backend-minted signed, expiring URL** from a **private** bucket (this is a
private single-user app; no public asset URLs).

**Storage target — open decision, recommendation below.** The backend is Python /
FastAPI on **Railway** and already integrates the **Supabase** project, so:

- **Supabase Storage (recommended):** already-provisioned, has a Python client for
  server-mediated upload from FastAPI, private buckets + signed URLs, ~1 GB free
  storage that is **separate from the 500 MB Postgres cap**. Least new wiring given
  the existing stack.
- **Vercel Blob (alternative):** clean private storage too, but its natural home is
  the Vercel/Node side; from a Python/Railway backend it's HTTP-API/token work. Pick
  this only if we'd rather the upload live on the frontend.

Size is bounded — one or a few routine videos, replaced occasionally, not a library
that grows daily.

## Video reference / catalog

The bytes live in object storage; a **small `flexibility_videos` catalog row**
holds the reference + metadata: `id`, `title`, `storage_key`, `duration_sec`,
`content_type`, `uploaded_by`, `uploaded_utc`, `is_active`. A planned `mobility`
workout optionally references `flexibility_video_id`, defaulting to the **active**
video — so "one routine" is the degenerate case (a single active row) and "several
routines" (still open — see below) is naturally supported.

*Lighter alternative (open decision):* skip the catalog table and stash the single
active video's reference as a JSON blob on an existing retained-state row
(`knowledge_base` / a settings row), avoiding a migration. Recommend the catalog
table for honesty + multi-routine headroom; settle at `/batch-start`.

## The in-app video player

New PWA surface, reached from the **Today card on a flexibility day** ("Start
session"):

- An HTML5 `<video>` with the signed URL: play/pause, seek, fullscreen, and (PWA
  permitting) keep-awake while playing.
- Progress is the video's own timeline; "Done" is offered on `ended` (or a manual
  "Mark done" after a minimum watched fraction).
- On completion it **POSTs the same `guided_sessions` completion** as strength, with
  `format:"flexibility"`.
- Graceful states: video still uploading / none set yet / signed-URL fetch failed.

**Entry-point dependency:** same as Batch 38 — the Today card is being reworked by
the specced Batch 36; attach "Start session" to the Today card as it exists at
build time (or the reworked `WorkoutRow` if 36 shipped first).

## Logging + reconciliation ("both, reconciled") — the honest version

Reuse Batch 38 exactly: the completion writes a `guided_sessions` row
(`format:"flexibility"`), and the pure `match_guided_to_activity` links it to a
same-user/same-day/within-`MATCH_WINDOW` Garmin activity **if he also recorded the
routine on his watch**.

**Important accuracy point:** there is **no flexibility watching-brief** today (the
Batch 19 brief is strength-only, over `exclude_from_recovery` activities). So unlike
strength, this reconciliation is **not** preventing a brief double-count — it exists
to (a) keep **adherence/history** showing one session rather than two when both the
app and the watch recorded it, and (b) be forward-compatible with a *future*
flexibility brief. The completion also marks the planned flexibility session **done**
for adherence, consistent with the Batch 30 day-controls (exact wiring settled at
`/batch-start`). Flexibility Garmin activities are **not** `exclude_from_recovery`,
so the match keys on a flexibility/yoga/mobility activity type + time, not that flag.

## API

- `POST /api/v1/flexibility-videos` — **admin-only** multipart upload → object
  storage → catalog row (mirrors the Batch 5 admin-editor auth boundary).
- `GET /api/v1/flexibility-videos/active` — returns the active video's metadata +
  a freshly signed, expiring playback URL.
- `POST /api/v1/flexibility-session/{plannedWorkoutId}/complete` — writes a
  `guided_sessions` completion (thin variant of the Batch 38 completion route, or
  the same route with `format`).
- Shared Zod schema for the video metadata + completion in `@coach/shared`.

## Frontend

- **Admin upload surface:** extend `/coach-state` (or a small admin page) so Craig
  can upload / replace / set-active the flexibility video; admin-gated like Batch 5.
- **Player:** the video component above, reached from the flexibility Today card.

## Phases

- **39.1** Object-storage integration (recommended Supabase Storage): private
  bucket, server-side upload, backend-minted signed playback URL; secret-safe,
  never committing storage keys.
- **39.2** `flexibility_videos` catalog table + model + Alembic migration (or the
  lighter no-table reference, per the open decision).
- **39.3** API: admin upload, active-video fetch (signed URL), completion (reusing
  `guided_sessions`); shared schema.
- **39.4** Frontend admin upload/replace surface (Batch 5 pattern).
- **39.5** Frontend flexibility video player from the Today card; completion POST on
  `ended`.
- **39.6** Tests + green gates (below).

## Testing

- **Pure/unit:** signed-URL builder returns an expiring URL and never a raw key;
  active-video selection picks the single active row; `format:"flexibility"`
  completion maps to a `guided_sessions` value; the Batch 38 `match_guided_to_activity`
  still links only within window / same user / same day for a flexibility type.
- **DB-backed:** admin upload writes one catalog row + one storage object (storage
  faked in tests); `active` returns metadata + a signed URL; completion writes one
  `guided_sessions` row; a matched Garmin flexibility activity de-dupes history.
- **Auth:** upload is admin-only (401/403 otherwise), consistent with `/coach-state`.
- **Frontend:** player renders with a stubbed signed URL, fires completion on
  `ended`, shows the no-video / upload-failed states; admin upload surface posts the
  file; "Start session" appears on a flexibility day only.
- Backend pytest/ruff/mypy pass; web lint/test/build pass; shared typecheck/tests.

## Non-goals / out of scope

- **No YouTube/embed/link-out** — he chose an uploaded, hosted file.
- **No flexibility watching-brief / analysis** — logging only; a flexibility brief
  (analogous to Batch 19) is a possible later batch, and this log is built to feed it.
- **No verdict/recovery impact** — flexibility never affects the Green/Amber/Red
  verdict or recovery (consistent with strength staying advisory, #49/#80).
- **No video editing/trimming/transcoding** — store and play the file as uploaded
  (optionally validate size/type on upload).
- **No new session-log table** — reuse Batch 38's `guided_sessions`.

## Open decisions to settle at `/batch-start`

1. **Storage target:** Supabase Storage (recommended) vs. Vercel Blob.
2. **Catalog:** `flexibility_videos` table vs. a lighter single-reference blob on an
   existing retained-state row (no migration).
3. **One routine vs. several** (still unconfirmed with Craig): if several, the
   planned `mobility` day picks which `flexibility_video_id`; if one, the active
   row is implicit.
4. **Playback delivery:** direct signed object-storage URL vs. an auth-gated
   backend proxy stream.
5. Player entry point vs. Batch 36 (as in Batch 38).

## Dependency & sequencing

- **Requires Batch 38's `guided_sessions` table + reconciliation.** If Batch 39 were
  ever built first, it would own that migration instead — but the agreed order is
  **38 → 39**.
- Independent of the Home-refinement Batches 35–37 except the shared Today-card
  entry point noted above.

## Safety / invariants preserved

- Flexibility is **advisory/adherence only** — no verdict/recovery effect (#49/#80).
- Video lives in **private object storage off the Postgres cap**, served via
  short-lived signed URLs; no public asset exposure, no secrets committed.
- Reconciliation guarantees history shows **one** session when both app and watch
  recorded it.
- Upload is **admin-only**, matching the Batch 5 retained-state boundary.
