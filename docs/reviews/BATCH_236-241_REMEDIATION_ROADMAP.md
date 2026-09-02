# Batch 236–241 remediation roadmap

**Synthesised 2026-09-01**, from the six passes of audit wave #4. Ninety-nine
findings across code, ops, AI, coaching, physiology and UX, reduced to an
ordered set of work packages. Follows the format of the Batch 188–192 roadmap.

**The passes:** [236 code](BATCH_236_CODE_REVIEW.md) (19) ·
[237 data/security/ops](BATCH_237_DATA_SECURITY_OPS_REVIEW.md) (17) ·
[238 AI](BATCH_238_AI_ENGINEERING_REVIEW.md) (17) ·
[239 coaching integrity](BATCH_239_COACHING_INTEGRITY_REFRESH.md) (12) ·
[240 health science](BATCH_240_HEALTH_SCIENCE_REVIEW.md) (19) ·
[241 UX](BATCH_241_UX_LIVE_APP_REVIEW.md) (15).
Scope and guardrails in [BATCH_236-241_AUDIT_SCOPE.md](BATCH_236-241_AUDIT_SCOPE.md).

---

## The bottom line

**The app's deterministic core is sound and its security boundary is genuinely
good. What is weak is every mechanism that is supposed to notice when something
goes wrong.** That sentence is not a summary written for effect — it is what
four independent passes converged on without coordinating:

- 236 proved the scheduler's **error handlers raise from inside themselves**.
- 237 found production has **no operator alert route at all** — and that two
  jobs failed in the last fortnight, discovered only because a review looked.
- 238 found **nothing in the system inspects generated output**, so a model swap
  deleted two shipped batches' worth of Mark's brief with every test green.
- 241 found `/brief` — *where the push lands* — renders "failed", "generating"
  and "not checked in" **byte-identically**, with no retry.

Each pass found one layer of the same hole. Stacked, they mean a failure in this
app is silent at the handler, silent at the alert, silent in the output, and
silent on the screen. That is the wave's headline and it drives the ordering
below.

**The second theme is narrower and more serious.** The morning verdict is
presented to Mark as a health judgement and is a *sleep-and-readiness* gate. A
resting heart rate 40 bpm above his own ceiling returns Green (240, proved). And
on the one path where the light does say stop, **the un-eased session still
reaches the trainer** — 239 found a Red written at 08:41 on 2026-07-22 and a
6 × 12 s @ 185% FTP (518 W) workout pushed at 09:19 carrying
`adjustment: {"changed": false, "verdict": null}`. The delivery path did not
override the verdict; it never received it. Independently re-verified against
production during synthesis.

**Grade movement:** coaching integrity **A− → B+**, the first downward move in
the document's history. The light is better than it was; the *session* is what
regressed, and the audit grades the coaching.

---

## Disposition legend

| Tag | Meaning |
|---|---|
| **Do now** | Ships in this remediation wave, in the order given. |
| **Decision-gated** | Craig chooses the shape before anyone builds. Listed in "Zero-code decisions". |
| **Defer — trigger** | Correct to leave; the row records what must happen first. |
| **Accept and close** | Real, understood, not worth changing at one user. Recorded so it is not rediscovered. |

---

## At a glance

| # | Package | Findings | Tier | Why this position |
|---|---|---|---|---|
| **W0** | Make one alert ring | DS237-01 | 🔴 | Two env vars, zero code. Every other finding is cheaper to fix than to detect; this is what changes that. |
| **W1** | The error handlers stop raising | CR236-01, CR236-03 | 🔴 | Proved, silent, production-reachable — and it disables the alerting W0 just switched on. W0 is inert until this lands. |
| **W2** | A Red reaches the trainer | CI239-02, CI239-03, CI239-04, CI239-05 | 🔴 | Safety. The app's own named rule is unenforced on the path that writes the workout. |
| **W3** | The brief says what it is for | AI238-01, UX241-01, UX241-04, AI238-02 | 🔴 | Live regression, today, on Mark's daily read. The prompt fix is one paragraph; the guard is what stops wave five repeating it. |
| **W4** | Extract the verdict | CR236-07 | 🟢 | Pure refactor with no behaviour change — **ordering gate for W5**. |
| **W5** | The verdict gets an acute-physiology rail | HS240-01, HS240-02, HS240-03, HS240-04, CI239-11, UX241-10 | 🔴 | The safety half of the wave. Lands on the extracted module, not the 261-line function. |
| **W6** | Runway: storage, backup, meter | DS237-02, DS237-04, DS237-03 | 🔴 | ~90% of the storage cap with nothing watching, and no backup ever restored. ~4 weeks of headroom — ample, so this sits here on merit rather than on a deadline. |
| **W7** | The failure loop closes | AI238-03, AI238-04, UX241-02, UX241-11, AI238-11 | 🟢 | Two past outages remain reachable exactly as they occurred. |
| **W8** | Statistics that carry their advice | HS240-06, HS240-07, HS240-11, CI239-12 | 🟢 | The app states as measured what it has not measured well enough. |
| **W9** | The REM premise gets audited | HS240-05, HS240-14, HS240-10 | 🟡 | **Decision-gated.** The app's most repeated claim about Mark's body may be a device artefact. |
| **W10** | One morning pipeline | CR236-02, CR236-06, CR236-09 | 🟢 | Every morning-path defect in the ledger is drift between three copies. |
| **W11** | Coaching residuals | CI239-01, CI239-06, CI239-07, CI239-10, HS240-16 | 🟢 | Real coaching defects, none safety-critical. |
| **W12** | Correctness and hygiene cleanup | CR236-04/05/08/12/13/19, DS237-09/16/17, AI238-06/07/10/12/13, UX241-06/07/08/09 | 🟢 | Mechanical, individually small, collectively the drift-prevention layer. |
| **W13** | Presentation residuals | UX241-05, UX241-12, UX241-13, UX241-14, UX241-15, HS240-12, HS240-13 | 🟢 | Readability for a 61-year-old reader on a phone. |

---

## W0 — Make one alert ring *(Do now — first, and it is two environment variables)*

**DS237-01 (High).** Production has no operator alert route. `SENTRY_DSN_BACKEND`
is unset so `main.py` never initialises Sentry; `ADMIN_ALERT_USER_ID` is unset so
Batch 141's admin push is dormant; and the `alert_route:
provider_log_or_external_monitor` field that four helpers stamp onto their log
lines names a consumer that does not exist. Two jobs failed in the last
fortnight — `longitudinal-analysis` 2026-08-25, `morning-sync` 2026-08-28 — both
found only because the review went looking.

**Decided 2026-09-01 — Sentry only.** Set `SENTRY_DSN_BACKEND` on both Railway
services. **`ADMIN_ALERT_USER_ID` stays unset, deliberately.** Then add a
ledger-freshness check that runs *outside* the scheduler it watches.

**Why the push half is not taken.** `notify_admin_generation_failure` emits
`log.error("brief_generation_admin_alert", …)` **unconditionally, before it reads
`admin_alert_user_id`** (`nudge_alerts.py:707`), so Sentry captures every alert
helper *and* every `log.exception` in the scheduler — strictly more than the web
push would. The push would add a phone notification and nothing else, and it
cannot be had safely today: Garmin credentials are **global**
(`settings.garmin_tokenstore_b64`), not per-profile, and every scheduler job
iterates `Profile.is_active == True`, so a second active profile syncs Mark's
Garmin data and generates its own paid brief — the observed 2026-08-24 stray-profile
incident. An inactive profile is rejected by the alert function itself
(`not admin.is_active` → `False`), so there is no configuration-only path.

**Deferred — trigger:** operator web push. Requires an `operator` role excluded
from `_active_profiles` first. Revisit if Sentry proves too slow to notice, or if
a second real user arrives.

**Acceptance:** a deliberately failed job produces an operator signal that
arrives somewhere a human sees, proved once by inducing one.

**Note the sequencing trap:** setting these variables makes the alerting
*configured*, not *working* — W1 is what makes the handlers that would fire it
survive long enough to do so. Do W0 first anyway; it is free and it is the
prerequisite.

---

## W1 — The error handlers stop raising *(Do now — the root of the wave's theme)*

**CR236-01 (High, proved by execution).** `Session.rollback()` expires every
object in the identity map regardless of `expire_on_commit=False`. Under an
`AsyncSession` the next attribute read on an expired object is IO outside a
greenlet and raises `MissingGreenlet`. `scheduler.py:593` rolls back and
`:596` then reads `profile.id` — **inside the `except GenerationRequestInProgress`
handler Batch 232.1 shipped so that a designed cron overlap would not be recorded
as a failure.** It now records it as a failure and aborts the job. The sibling
`except Exception` dies before reaching `record_failure` and
`notify_admin_generation_failure`.

The codebase already knows: `scheduler.py:294-297` carries the comment *"Snapshot
before the try block: a rollback expires ORM attributes, so failure logging must
not trigger implicit async IO"* and hoists `profile_id = profile.id`
accordingly. **One job in twenty-four does this.** Verified independently during
synthesis — the correct pattern and the defect are 300 lines apart in one file.

**CR236-03 (High).** The morning pipeline's failure isolation is tested entirely
against `session = AsyncMock()` and `profile = MagicMock()`. A mock session's
`rollback()` expires nothing and a `MagicMock` is never in an identity map, so
the behaviour under test is structurally unobservable — including in the one
real-Postgres test written to prove the CR189-02 fix.

**Do:** (1) hoist `profile_id`/`timezone` into locals before every `try` in
`scheduler.py` — mechanical, un-risky, lands immediately. (2) One session per
profile iteration — the structural fix. (3) Convert the isolation tests to real
`AsyncSession` + real profile rows so it cannot return.

**Acceptance:** a test that fails before (1) and passes after; the designed
weekly-review cron overlap recorded as `skipped`, not `failed`; a forced job
exception reaching `record_failure` and the W0 alert.

---

## W2 — A Red reaches the trainer *(Do now — safety)*

**CI239-02 (High, observed in production).** `reconcile_deliveries` (Decision
#99) and `WorkoutDeliveryService.push` write to the Zwift rail with no
`blocks_red_vo2` check. On 2026-07-22 a Red was written 08:41:17; at 09:19:01 an
`as_planned` IR carrying **6 × 12 s at 185% FTP (518 W)** reached `pushed` with
`adjustment: {"changed": false, "verdict": null}`; the eased Red alternative was
generated at 10:00:10 and never pushed. **Eleven of eighteen eased offers ever
made were never pushed.** Re-verified from `coach.workout_delivery_proposals`
during synthesis.

**CI239-03 (Med-High).** Red prescribes a *longer* ride than Amber on the same
Z2 session — 102 min vs 90. Batch 215 set Red's 0.85 scale without checking
Amber's 0.75. The combined-load gate is Red-only, so Amber never sees the day's
other session.

**CI239-04 (Med-High).** The easing transform shortens the intervals themselves:
a Rønnestad 30/15 becomes 22 s/11 s at 94% on Amber and 15 s/8 s at 60% on Red —
5.5 minutes of work in a 30-minute session. That is not an eased VO₂ session; it
is a different session wearing its name. Ease the *number of reps* or the
session type, never the interval geometry that defines the protocol.

**CI239-05 (Med).** The Amber instruction is bike-only and emitted verbatim on
strength, mobility and walk days.

**Acceptance:** the delivery path receives the day's verdict and refuses to push
an un-eased hard session on a Red; a monotonicity test proving Red ≤ Amber ≤
planned on both duration and load; interval geometry preserved under easing;
the 2026-07-22 scenario replayed as a regression test.

---

## W3 — The brief says what it is for *(Do now — live regression on Mark's daily read)*

**AI238-01 (High, proved by one-variable replay).** `morning_analysis.py:229`
asks for *"concise markdown with a sleep summary line, a metrics-vs-baselines
read, a thermal/environment review, and a Green/Amber/Red workout verdict"* — a
closed four-item list written when the brief had four sections. Sonnet 5 obeys it
literally. Replaying Mark's stored 08-31 packet at production settings produced
4 sections and 4,421 chars *with* 3,801 thinking tokens, against 4.6's 8 sections
and 8,482 chars. Post-workout and post-strength are unchanged, so this is not
"Sonnet 5 is terser" — it is the one prompt whose enumerated contract is narrower
than the content it carries.

**UX241-01 (High).** The user-visible face: the four `experiment_update` rows
were written at **08:24:58.374** and the brief at **08:25:19.954** — 21.6 seconds
later, mentioning none of them (re-verified during synthesis). The Chronic REM
Pattern section left and took its **two carried actions** with it, so the brief
still diagnoses low REM and no longer says what to do about it. The packet was
never the problem: it carried `experimentLoop.experiments` (4),
`chronicSuggestions.items` (1), `recentCorrections` (5) and the respiration and
SpO₂ baseline entries. All sent, none delivered.

**UX241-04 (High).** On `/brief` the verdict heading sits at y=3,080 of 3,809 px —
81% down, 4.5 screenfuls — and the section breaks that made that scroll skimmable
are the ones AI238-01 removed. The two compound.

**AI238-02 (High).** Nothing inspects generated output. Every prompt test asserts
an instruction is *present in the prompt*; none asserts it was *obeyed*.

**Do:** re-baseline the contract sentence to describe the brief's actual
obligations, driven by what the packet carries rather than a frozen list. Then
add the cheap structural guard — assert the sections the packet requires appear
in the output, and log a warning when they do not. **Do not revert the model,
raise effort, or add tokens**; the replay rules all three out.

**Acceptance:** a brief generated from the 09-01 packet carries the experiment
section, the chronic-REM actions and the stage detail; the guard fails a
deliberately truncated output; the verdict rises above the fold on `/brief`.

---

## W4 — Extract the verdict *(Do now — ordering gate for W5)*

**CR236-07 (Medium).** The product's central decision is a 261-line,
complexity-32 function a thousand lines below its caller. HS240-01, -02 and -17
are all edits to it.

**Do:** extract `services/morning_verdict.py` with its own test module. **No
behaviour change** — a pure move, proved by the existing suite passing unchanged.

**Why it is a gate:** doing this first is the difference between three reviewable
safety diffs and three high-risk ones. This is the highest-leverage ordering
decision in the wave.

---

## W5 — The verdict gets an acute-physiology rail *(Do now — the safety half)*

**HS240-01 (Safety, High, proved).** `_resting_hr_elevated` compares today's RHR
against Mark's 84-day upper quartile, returns a clean boolean — and that boolean
feeds exactly one consumer, gated behind `readiness_level == "poor"`. Driving the
real `_morning_verdict` with his own baseline (Q3 = 49): RHR 60 → Green, 70 →
Green, **85 → Green**. His real range is 40–49 across 185 nights. Garmin has
emitted `POOR` on **2 of 72 mornings**, so the one escape path is reachable 2.8%
of the time.

**HS240-02 (Safety, High).** An acute one-night HRV collapse is invisible to the
verdict — `hrv_last_night_avg_ms` is a never-reached fallback rather than its own
signal.

**HS240-03 (Safety, High).** Overnight SpO₂ and respiration are collected,
baselined, and evaluated by nothing.

**HS240-04 (Safety, Med-High).** There is no medical boundary anywhere Mark
reads, and no statement of what the app cannot see.

**CI239-11 (Low).** A total data blackout returns Green.

**UX241-10 (Medium).** Nothing Mark reads says what the app cannot see.

**Do:** one acute-physiology rail, absolutely anchored, **independent of
Garmin's readiness category**: RHR against his own median with an absolute delta
floor (e.g. ≥ +7 bpm, or above Q3 on two consecutive mornings); HRV read as its
own signal; an SpO₂/respiration surveillance rule; and a missing-data floor so
absence cannot produce Green.

### The medical boundary — approved copy (2026-09-01)

**Both strings are deterministic text, not model-generated** — anything the model
composes is exactly what W3 proved can vanish silently on a model swap. The
expandable "what this can't see" card was considered and not taken, on
screen-space grounds given UX241-04.

**The design principle behind the pairing:** the standing line appears every
morning and the escalation appears a handful of times a year. A daily disclaimer
becomes wallpaper within a week; a rare, specific warning gets read. So the
weight goes where it is rare — a light standing line, a substantive escalation.

**Standing line (S1) — permanent footer on every brief:**

> This read comes from your watch and your room sensors. It can't see how you
> actually feel — if those two disagree, trust yourself.

**Escalation (E2) — emitted only when the acute-physiology rail trips.** Craig
approved all three variants before Batch 246 started. Every variant carries **the value,
his own baseline, and the window** — the app's established "numbers with meaning"
voice — then the plain-language cause list, then why training through it is
wrong, then the action and the medical route.

*Resting heart rate (approved):*
> Your resting heart rate is 61 this morning against a usual 44 — outside
> anything in your last six months. In practice that usually means one of: an
> infection starting, dehydration, alcohol, or simply being run down. Training
> hard through it tends to make it worse. Take today off the bike, and if you
> feel unwell alongside it, see your GP rather than just resting.

*HRV collapse (approved):*
> Your overnight HRV is 28 ms this morning against a usual 47 — a drop that size
> in a single night is unusual for you. It usually means one of: an infection
> starting, a heavy drink, a badly broken night, or real stress carried into
> sleep. Training hard through it tends to deepen it. Take today off the bike,
> and if you feel unwell alongside it, see your GP rather than just resting.

*SpO₂ / respiration (approved) — deliberately a different action:*
> Your overnight oxygen saturation averaged 89% last night against a usual 96%,
> and your breathing rate was 17 against a usual 11. Sustained low overnight
> oxygen has causes worth checking properly — a chest infection, or disrupted
> breathing during sleep. This one isn't something training or rest changes.
> Mention this to your GP if it happens again.

**Why the third variant ends differently, and it matters.** Repeated overnight
desaturation with elevated respiration in a 57-year-old man points at sleep-
disordered breathing, which is a *diagnose it* finding rather than a *rest it*
finding. Telling him to take a day off would be the wrong action and would let a
treatable condition keep presenting as a training problem. The rail's three
inputs do not share one piece of advice.

**Missing-data floor:** not an escalation. Absence of data must render as
"insufficient data to judge today", never as Green, and never with escalation
copy attached.

**Acceptance:** the HS240-01 probe table inverts — 85 bpm no longer returns
Green; a blackout returns "insufficient data", not Green; the boundary text is
present on the brief and cannot be dropped by a model (it is deterministic, not
generated).

**Clinical framing, stated plainly:** an overnight RHR rise of 5–15 bpm against a
stable baseline is the most useful early signal a wrist wearable produces, and in
a 57-year-old man its main causes are febrile illness, infection, dehydration,
alcohol and new-onset AF. This is the "don't train today" signal, and it is the
one input the app measures accurately and discards.

---

## W6 — Runway: storage, backup, meter *(Do now — time-boxed by growth)*

**DS237-02 (High).** `pg_database_size` is **451,267,731 bytes** against a 500 MB
free-plan cap — ~90%, growing ~1.85 MB/day, roughly four weeks of headroom.
`coach.activity_timeseries` is 353 MB of it. This app has filled its disk once
before (Decision #93, 2026-06-28, at ~625 MB, where `VACUUM FULL` could not run
because there was no room to write the copy). Egress got a meter after its
incident; storage got nothing.

**DS237-04 (High).** No backup has ever been restored. `backup-drill` has **zero**
`job_runs` rows in the table's history, is not registered in the scheduler, and
`BACKUP_RESTORE_DATABASE_URL` is unset. Retention is seven days on one Railway
volume, no off-site copy, and 353 MB / 665,259 rows of `activity_timeseries` are
excluded from every archive by design.

**DS237-03 (High).** The egress meter is wrong in three independent ways; on
2026-08-30 it recorded 16,312,169 bytes and stage `ok` against Supabase's
6.475 GB — a ~397× understatement.

**Do:** add `pg_database_size()` to the `egress-budget` job's counters with a
staged threshold (the job already runs every 15 min, already writes counters,
already dedupes alerts); apply the retention window decided below; provision a
disposable database and **run one restore by hand**, then register it weekly; and
either fix the meter's direction or re-label its alert copy "HTTP response
bytes", which is all it can honestly claim.

**`activity_timeseries` retention — decided 2026-09-01: 90 days.** Measured
2026-09-01: **666,672 rows / 354 MB / 833 activities**, 2025-06-24 → 2026-09-01;
the last 90 days are 201,579 rows (30%). Frees ~247 MB, taking the database from
451 MB (**90%** of the 500 MB cap) to ~204 MB (**41%**).

**What that costs, precisely.** The only readers are `post_workout_analysis.py`
and `post_walk_analysis.py`, each reading **one activity at a time** by
`activity_id` at analysis time; `garmin_sync` writes it and `ride_intervals`
consumes samples handed to it. **Nothing reads it across a window and
`longitudinal_analysis` never touches it.** So the loss is (1) regenerating a
post-workout or post-walk read for a ride older than 90 days — the analysis prose
stays in `analyses` permanently, only the per-second samples go, (2) interval
re-grading on old rides, and (3) optionality for any future feature wanting
per-second history. **It is also excluded from every backup by design**, so this
data is already unprotected against disk loss regardless of retention.

Archiving to a file before truncation was considered and not taken.

**Acceptance:** a storage threshold alert fires in a rehearsal; one archive is
provably restored with a row count; the meter's copy matches what it measures.

---

## W7 — The failure loop closes *(Do now, after W1)*

**AI238-03.** The two daily paths alert only on `billing`, and `classify_anthropic_error`
does not recognise the spend-cap wording — an HTTP 400 `invalid_request_error`
reading *"You have reached your specified API usage limits"* classifies as
`invalid_request` → 502 → generic copy → no alert. Functionally the 2026-07-21
credit freeze under a sentence Batch 141 never knew.

**AI238-04.** Transport failures bypass classification and nothing retries.
`httpx.TimeoutException` still classifies as `other`; no test exercises a real
timeout. This is the 2026-08-30 outage's illegibility, unfixed.

**UX241-02 (High).** `/brief` — where the "brief is ready" push lands — renders
`failed`, `generating` and `not-checked-in` byte-identically with no retry.
Batch 141's failure card is Home-only.

**UX241-11.** Stale-brief detection is Home-only and can only be fixed there.

**AI238-11.** `BriefChatError` is uncaught and the chat ceiling is unmeasured.

**Acceptance:** two past outages replayed as tests and both now produce a
classified error, a retry where retryable, an operator alert, and a distinct
user-visible state on `/brief` with a working Retry.

---

## W8 — Statistics that carry their advice *(Do now — Medium)*

**HS240-06 (High).** The lever gate is not statistically defensible, and **the
one lever production has ever issued does not survive the most obvious
confound**: adjusted for calendar time the partial correlation is **−0.145**
against a raw −0.235 and the app's own gate of 0.15. Its own rule would have
declined to issue it.

**HS240-07 (High).** The experiment loop reaches conclusions from noise — 3
nights per arm against a measured SD of 4.43 points cannot distinguish a 2-point
effect from nothing, and reaches a directional verdict from noise a quarter to a
half of the time.

**HS240-11.** `sleep_projection` names a "measured driver" with none of Batch
231's protections, on two surfaces plus a push.

**CI239-12.** CI211-01 unresolved and growing.

**Do:** replace the `moderate`/`high` confidence word with the coefficient's 95%
CI and n; refuse to name a lever whose interval crosses zero; adjust for calendar
time before ranking; apply the same gate on `sleep_projection`; raise the
experiment-loop thresholds.

**Acceptance:** the one issued lever is re-evaluated under the new gate and the
result — whichever way it falls — is recorded.

---

## W9 — The REM premise gets audited *(Decision-gated)*

**HS240-05 (High).** The chronic REM deficit is the app's single most repeated
claim about Mark's body — 82% of nights over 185 nights — and it is **more likely
a wrist-device stage-classification artefact than a physiological finding**. His
light sleep runs above its ceiling by almost exactly the amount his REM runs
below its floor, his deep sleep sits at the *top* of its band, and every other
marker he has is excellent. No code path has ever considered the complementarity
hypothesis. It drives a 12-lever library, a correlation engine, an experiment
loop and a line in every brief.

**HS240-14.** The Ohayon denominator gap is stage-dependent and larger than the
record says.

**HS240-10.** The 12-lever library mixes A-grade physiology with folk mechanisms
at identical confidence.

**Do not remove the flag on suspicion — make it say what it actually knows.**
State the measurement basis wherever the band is applied (the discipline
`REM_PCT_BASIS` already applies to the denominator), re-derive the bands on the
measured-sleep denominator, and grade the levers individually.

### The composition test is already done, and it did not support the simple story

Run during synthesis over **435 nights**: deep 17.1%, light 65.5%, REM 10.1%,
awake 7.4%. Correlations with REM%: **light −0.414, awake −0.452, deep +0.072**.

If light were being mislabelled as REM, light↔REM should dominate. It does not —
awake↔REM is equally negative, which fits *fragmented nights lose REM* (real
physiology: REM is back-loaded, so disrupting the back half costs REM
disproportionately). And because light is 65% of the total, a negative light↔REM
correlation is partly arithmetic. `remSleepData` is also `true` on every recent
night, so this is not a device-capability gap. **Recorded as evidence against the
simple complementarity hypothesis, not as a clean bill of health.**

### Decided 2026-09-01 — run the architecture and truncation tests

Both are free, both use `raw_payload.sleepLevels` (14–26 stage segments per night
with `startGMT`/`endGMT`/`activityLevel`), and together they should settle it:

1. **Episode architecture.** REM minutes by night-quarter, episode count, mean
   episode duration, and whether the last cycle carries the longest episode. Real
   REM clusters in the back half and lengthens through the night; noise does not.
   *Architecturally normal but short ⇒ the deficit is real. No architecture ⇒
   artefact.*
2. **Sleep-window truncation.** Does REM% track sleep *end* time and total
   duration? If short REM is mostly short or early-ended nights, the deficit is a
   schedule artefact. **Note this also tests the app's own carried action,
   "protect the final 90-minute cycle", which has never been validated.**

Firmware step-change and external EEG validation were considered and **not**
taken — revisit only if 1 and 2 disagree.

**Still open for Craig, after the tests report:** if the deficit turns out to be
substantially an artefact, the app has told Mark something about his body every
morning for months. Correct it quietly as evidence lands, or tell him explicitly
that a long-standing read is being revised?

---

## W10 — One morning pipeline *(Do now — Medium)*

**CR236-02 (High).** Three entry points, two incompatible transaction contracts,
no owner. The check-in path runs `commit=False` under one transaction; the 11:00
backstop commits each step and rolls back on error; the wake job does a third
thing. The router reaches into the scheduler for a private helper
(`from src.scheduler import _sync_morning_inputs`, a function-scope import to
dodge a cycle). **Every morning-path defect in the ledger — 141, 144, 222,
232.1 — is drift between these three, and each was fixed in the copy where it was
noticed.**

**CR236-06.** A transport exception carries domain control flow across four
layers. **CR236-09.** `routers/daily_loop.py` is a serialization layer wearing a
router's name.

**Acceptance:** one `MorningBriefPipeline` all three triggers call; the
transaction contract is a parameter, not an accident; `BriefGenerationStatus` has
one owner.

---

## W11 — Coaching residuals *(Do now — Medium)*

**CI239-01 (High).** The first live Red since Batch 194's fix (2026-08-28) was
excused from the chronic cluster as `expected_training_debt` *because of* 2,590
minutes (43 h) of recovery debt — uncapped, undecaying, uncorroborated, with no
check-in claimed. It is the one branch carrying none of the four bounds Batch 194
added. Batch 211's reserved question is answered, against the app.

**CI239-06.** Perfect execution can never earn an FTP increase: `over_rate ≥ 0.30`
requires exceeding target by >5 pp, 30-second VO₂ reps are peak-graded and cannot
grade "over" by construction, and ERG holds sweet spot exactly on. Progression is
gated on disobeying the prescription — against Batch 152's ERG-trust rule.

**CI239-07.** Strength is invisible to every load rule but counted as a spacer
between two hard bike days. **CI239-10.** Two Zone-2 anchors coexist and the
endurance ceiling binds. **HS240-16.** The VO₂ interval target is probably below
the intensity that elicits VO₂max.

---

## W12 — Correctness and hygiene cleanup *(Do now — Medium, after user-facing work)*

CR236-04 (four post-activity services 68–78% identical) · CR236-05
(`workout_type` free text, ten classifiers, two disagree) · CR236-08 (Alembic
offline path omits `version_table_schema`) · CR236-12 (Batch 184's "shared"
projection is still a copy) · CR236-13 (`select(Model)` is the default idiom and
nothing lints it) · CR236-19 · DS237-09 (F4 PII unmoved and wider than described)
· DS237-16 · DS237-17 (three residual Batch 235-class full-row reads) · AI238-06
(one honesty rule, eight hand-written copies) · AI238-07 · AI238-10 (two JSON
strategies; the fragile one writes memory) · AI238-12 (two `basis` strings for one
fact, and the model quoted the wrong one) · AI238-13 · UX241-06 (the coach thread
is the one fetch with no schema guard) · UX241-07 · UX241-08 · UX241-09.

---

## W13 — Presentation residuals *(Do now — Low)*

UX241-05 (268 messages held, 60 shown, **208 unreachable**, growing ~4/day) ·
UX241-12 (25 hard-coded sub-14 px sizes, on an app read by a 61-year-old) ·
UX241-13 · UX241-14 · UX241-15 (cold time-to-content 4.9–11.7 s) · HS240-12
(band classification is one-sided, so no rebound signal can exist) · HS240-13
(outcome-framed descriptors are literally false for lower-is-better metrics).

---

## Defer — trigger

| Finding | Trigger |
|---|---|
| **DS237-05** RLS does not constrain the application (0/29 `FORCE`) | A genuine second user, or a least-privilege application login. Unchanged since Batch 190; external boundary genuinely passes. Batch 209 holds the shape. |
| **DS237-06** thirteen live 365-day device tokens, no way to see them | Any token compromise, or a second user. |
| **DS237-11 / DS237-12** co-resident public app | Batch 208 holds it. 237 adds a concrete mechanism the row lacks. |
| **CR236-10** `scheduler.py` is an application inside a module | Follows W10; splitting before the pipeline consolidates would move the drift, not remove it. |
| **CR236-11** `DashboardPage.tsx` is 2,230 lines holding 34 components | Next substantial frontend change touching it. |
| **CI239-08 / CI239-09** plan-import validation; the 13-week generator has never produced a live plan | Next plan authored, or the generator's first live use. |

## Accept and close

| Finding | Why |
|---|---|
| **DS237-07** unused RLS-bypassing key required at startup | Real, low exposure at one user; remove opportunistically. |
| **DS237-08** the audit log records one thing and it is not a user action | Documented mismatch; no consumer depends on it. |
| **DS237-10** activation rate limit is one global bucket | One user, no public sign-up. |
| **DS237-13** the only production profile is `admin` | True and intended today. |
| **DS237-14** activation codes travel in a query string | Single-use, short-lived, private link. |
| **DS237-15** stale-deploy detection is human-only | Both surfaces currently serve the same SHA; W0's alerting is the better investment. |
| **CR236-14/15/16/17/18** orphaned backfills, schema-drift check, ignored coverage, docstring drift, one-way migration check | Individually trivial; fold into W12 opportunistically rather than scheduling. |
| **HS240-18** `workload_budget.py` is not a physiological workload budget | Scope correction, not a defect. |
| **HS240-19** SpO₂ survived the model swap; respiration and the experiment section did not | Correction to the wave's own pre-audit note; folded into W3. |
| **AI238-14/15/16/17** age bands composed by the model; unwired duplicate rule; over-broad classification; the effort decision's unreproducible measurement | Recorded. AI238-17 matters if effort is ever revisited. |

---

## Coverage check — all 99 mapped

| Pass | Findings | Do now | Decision-gated | Defer | Accept |
|---|---:|---:|---:|---:|---:|
| 236 code | 19 | 12 | 0 | 2 | 5 |
| 237 ops | 17 | 6 | 0 | 3 | 8 |
| 238 AI | 17 | 13 | 0 | 0 | 4 |
| 239 coaching | 12 | 10 | 0 | 2 | 0 |
| 240 health | 19 | 13 | 3 | 0 | 3 |
| 241 UX | 15 | 15 | 0 | 0 | 0 |
| **Total** | **99** | **69** | **3** | **7** | **20** |

---

## Zero-code decisions for Craig

**All six were decided on 2026-09-01. Recorded here so the reasoning travels with
the work rather than living in a chat log.**

1. ~~Who is the operator?~~ **Sentry only.** `SENTRY_DSN_BACKEND` set;
   `ADMIN_ALERT_USER_ID` deliberately left unset. The error log fires
   unconditionally, so Sentry captures strictly more than the push would — and
   the push cannot be had safely until an `operator` role exists, because Garmin
   credentials are global and every job sweeps `is_active` profiles. Full
   reasoning in W0.
2. ~~The REM premise — quiet correction or explicit?~~ **The disclosure question
   is deferred until the evidence lands; the investigation is decided.** Run the
   **episode-architecture** and **sleep-window-truncation** tests, both free and
   on stored data. The composition test was already run and did not support the
   simple complementarity story. Re-open disclosure once they report. See W9.
3. ~~Where does the medical boundary go, and how strongly worded?~~ **A standing
   one-line footer plus escalation on the rail — copy approved (S1 + E2), both
   deterministic rather than model-generated.** Craig chose the light standing
   line and the medium escalation, on the reasoning that a daily disclaimer goes
   unread while a rare warning does not. **Residual:** the HRV and SpO₂/respiration
   escalation variants are drafted but not yet signed off — and the SpO₂ one
   deliberately ends in "see your GP" rather than "rest", because sleep-disordered
   breathing is a diagnose-it finding, not a rest-it one. See W5.
4. ~~`activity_timeseries` retention?~~ **90 days**, freeing ~247 MB and taking
   the database from 90% of cap to ~41%. See W6 for precisely what is lost.
5. ~~Whether W2 ships ahead of this roadmap as a standalone row.~~ **Decided
   2026-09-01: no — W2 ships as part of the wave, in its roadmap position.**
6. ~~Storage headroom is ~4 weeks and W6 is the only package with an external
   clock.~~ **Decided 2026-09-01: ~4 weeks is ample runway and does not
   constrain batching.** W6 keeps its position on merit, not on a deadline;
   re-check the figure if it is still unbuilt in three weeks.

---

## How to execute

Per the batch workflow in `docs/agent-commands/`. Each W becomes one or more
ledger rows authored from this document, and **`/batch-start` re-verifies the row
against the code before any of it is built** — several findings here name
`file:line` references that will move as earlier packages land. W4 in particular
must complete before W5 is authored, and W1 before W7 is meaningful.

Assign `DECISIONS.md` numbers at `/batch-start`, never when authoring the rows.

**Suggested first three rows:** W0+W1 together (the alerting is inert without the
handler fix), then W2 (safety, small diff), then W3 (live regression). W4→W5 is
the first multi-row sequence and should be authored as a pair.
