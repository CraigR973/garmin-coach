# Batch 330 — Coaching-Integrity Refresh (5th)

**Date:** 9–10 Oct 2026 · **Lens:** cycling coach who trains masters athletes ·
**Reviewed SHA:** `42a6a98` (production) · **Grade entering:** B+ (Batch 239) ·
**Grade leaving: B+ (held: up on the call, down on the plan and the trainer)**

Part of audit wave #5 (Batches 327–333). Siblings cited, not restated:
`BATCH_327_CODE_REVIEW.md` (CR327), `BATCH_329_AI_ENGINEERING_REVIEW.md` (AI329),
`BATCH_332_HEALTH_SCIENCE_REVIEW.md` (HS332). Strength and mobility belong to R5 (FC331); the
UX of Mark's complaints to R7 (UX333). **This report names how inputs can be gamed and how the
plan can be stripped; it is internal and not for Mark.**

Method: the two prongs of `COACHING_INTEGRITY_AUDIT.md`. **Prong A** drove the real functions
in memory from scratch scripts in `scratchpad/wave5/r4/` (never re-implemented): `grade()` over
the 295 test grid, the verdict transforms on Plan No. 3's sessions, `plan_changes.apply_change`
on a copy of the draft, `ride_intervals._adherence`. **Prong B** read production read-only
(Supabase SQL, column-projected; one `railway run` replay, rolled back). Paid spend: **$0**.

---

## 1. Summary

**Verdict.** The morning call is now the best-built part of the app and needs nothing before
21 Oct: the replay reproduces production on **10 of 10** graded mornings, a worse input never
gave a less cautious colour across 798,336 grid comparisons, F2, F3 and F4 are closed. What a
coach would not stand behind is downstream of the call: on **Sat 10 Oct** the brief, Home and
the trainer prescribe **three different rides** (CR327-01, live), and Plan No. 3 — a real
improvement on Plan No. 2 — arrives with three gaps that all land in its first fortnight: its
editor can multiply a VO₂ session several times over, the app will keep grading against 280 W
after the ramp test sets a new FTP, and its protections can be removed one tap at a time with
no one told. **Grade B+ (held).**

| Question | In this lens |
|---|---|
| 1. Correct and safe? | The call: yes, invariants hold. The plan editor: no ceiling on VO₂ dose (CI330-01); a test on a tired morning is eased rather than moved (CI330-03). |
| 2. Honest with Mark? | The call: yes. The ride: no on 10 Oct (three versions, CR327-01); after 20 Oct every ERG-perfect interval can read "under" or "over" (CI330-02). |
| 3. Helping him get fitter? | Plan No. 3 progresses and recovers properly (2:1, a test, longer sweet spot); no key session has been ridden at full since 12 Sep; his own VO₂ progression was set aside unmentioned (CI330-05). |
| 4. Would failure be noticed? | The call: the replay and grid would catch it. The plan: a stripped or overloaded plan logs at info level only, and the app then judges against it (CI330-04). |
| 5. Cheap to run and change? | Yes for the call (one engine after 308). The plan editor is cheap to make safe: a per-session dose bound and a lock-time diff, about a day. |

---

## 2. What optimal looks like, and the smallest path

**Optimal, for this athlete** (57, well-trained, ERG on Zwift, two strength sessions, one
coach-in-a-box): one deterministic call per morning (done); **the session on the trainer is
always the session the call and Home describe** (not yet: CR327-01); a 13-week block that
progresses, deloads every third week and tests once (Plan No. 3 does this); **the test result
flows into every target and every grade** (not built: CI330-02); **a test is ridden fresh or
moved, never eased** (CI330-03); Mark can change anything, but **no change can make a session
unsafe** and **Craig sees what was removed** (CI330-01, CI330-04); a signal that tells him when
to progress (319, queued).

**Near-optimal already** (keep, do not touch): the graded verdict and its floors; the session
actions (move/hold/ease/recovery) as a coach would titrate; Red-never-VO₂ at every push rail;
the proposal-expiry job (no stale offers); Plan No. 3's shape (recovery every third week, a
week-1 ramp test after a taper, sweet spot from 2 × 25 to 2 × 40, long ride 120 → 135 min,
weekly cap 453 min respected, two loaded strength sessions); the post-ride reads grade what he
actually rode (7 and 8 Oct).

**Smallest set of changes, in order:**

1. **CR327-01** (R1's fix): a swap or move carries the planned content, not an adjusted event;
   and a daily check that each pushed event's content matches its planned row plus the
   morning's action. *Before 21 Oct? R1's call, already raised with Craig.*
2. **CI330-01**: bound VO₂ work per session in `plan_changes` (and the interval editor), and
   say the total. Adds caution only. *Before 21 Oct? yes — the builder opens to Mark on 12 Oct.*
3. **CI330-02**: after the ramp test, one tap writes the new FTP into the profile (the app
   computes three-quarters of the best minute). Fold into **319** as its first item; needed
   before Thu 22 Oct's first graded sweet spot. Zero-code bridge: Craig sets the profile FTP by
   read-modify-write when Mark reports it (a production write — Craig's call).
4. **CI330-03**: a test session's only actions are "as planned" or "move it". Zero-code bridge
   before Tue 20 Oct: tell Mark not to ride an eased test.
5. **CI330-04**: at accept, a one-screen "as proposed → your plan" diff of the test, the VO₂
   count and the recovery weeks' load, shown to Mark and logged with the `admin_alert` tag.

---

## 3. Findings

Counts: **0 High** (the live High in this lens is R1's CR327-01, analysed in 3.0) ·
**3 Med-High** · **3 Medium** · **2 Low**.

### 3.0 The live case: what reached the trainer on 8 and 10 Oct (CR327-01, observed)

Not a new finding; R1 owns it. My lens's account, from `workout_delivery_proposals`,
`planned_workouts`, the 10 Oct morning and the code (`executable_coaching.swap_day`,
`regenerate_for_verdict`, `_deliberately_acted`):

| Time (UTC) | What happened | Evidence |
|---|---|---|
| 11 Jul | Plan No. 2's rides pre-pushed (Decision #99): Thu 8 Oct Sweet Spot 1 × 30 @ 89 % (event …345), Sat 10 Oct Easy Z2 45 min (event …349) | observed |
| 8 Oct 09:40 | Morning graded **Red**, "Recovery day"; a `red_substitution` proposed for the Sweet Spot | observed |
| 10:07:01 | Mark approves it: event …345 is **replaced** by a 29-min ride, every step ≤ 60 % FTP (half length, `durationScalePct` 50) | observed |
| 10:07:10 | Mark taps Swap (Thu ↔ Sat). `swap_day` **moves the live events** and re-points their proposal rows: the eased event …345 now sits on **Sat 10 Oct** under a new plan row reading the **full 58-min Sweet Spot**; the unadjusted Easy Z2 (…349) moves to Thu | observed + implemented |
| 8 Oct | He rides 45 min at 178 W (64 % FTP), the Easy Z2; the post-ride read grades it correctly, then tells him "the real target is arriving at Saturday's Sweet Spot" | observed |
| 8 Oct (chat) | Mark: the Sweet Spot "was already moved to (swapped with) Saturday … and is showing there" on the Week tab | observed |
| **10 Oct 07:49** | Morning graded **Amber**, "Take the edge off": Sweet Spot action `ease_hard` (89 % → 76 %, full 58 min). **No proposal is made**: the pushed red-substitution row counts as "deliberately acted on" | observed + implemented |

**What Mark has on Sat 10 Oct** (as of 08:05 UTC; he had not ridden):

| Surface | The ride |
|---|---|
| Home / Week | Sweet Spot (1 × 30 min @ 89 %), 58 min, delivered (R1: shown "in Zwift") |
| The brief | the Sweet Spot "at its full planned length (58 minutes)" with the hard efforts eased "from 100% to 87% of FTP" |
| What the engine means | the main set 89 % → **76 %**; the 100 % → 87 % is the two 30-s warm-up primers (proved: `scratchpad/wave5/r4/probe_oct10.out`) |
| Zwift | "Recovery substitution: Sweet Spot …", **29 min, nothing above 60 %** |

So the week's only quality session becomes a recovery spin unless he notices the Zwift name, and
the brief's one number describes the warm-up. The brief also offers the deterministic swap
(Sat Sweet Spot ↔ Sun Easy Z2): taken, it would carry the recovery event to Sunday under a
Sweet Spot row again (implemented, same `swap_day` path). The 6 Oct invariant "every surface
shows the same call" holds for the **call** (headline and reading agree everywhere); it does
not hold for the **ride**, which no invariant covers. The brief's misquoted number is DV-9's
class (queued in 318). *Checked again at the end of this pass (about 08:05 UTC): no ride yet; the orchestrator or the 21 Oct trial addendum should read what he rode and what the post-ride read graded it against.*

---

### CI330-01 — Med-High · The plan editor multiplies a VO₂ session by its set count, and nothing bounds the dose · **before 21 Oct?**

**Evidence: proved** (`scratchpad/wave5/r4/probe_mark_vo2.py`, real `plan_changes.apply_change`
on a copy of the draft) + **observed** (Mark's 28 Aug document).

The change list's interval edit takes the editor's five numbers and applies them to **each set**
of a multi-set session (Batch 263's semantics, right for "2 × 10 min of 35/25"). There is no
field for the number of sets and no ceiling on the result. Entering Mark's own documented
next-block progression (28 Aug, "for future reference") on Plan No. 3's Tuesdays, the natural
way, is **accepted every time**:

| Week | He enters | The draft becomes | Work ≥ 106 % FTP |
|---|---|---|---|
| 2 | 6 × 2 min @ 120 % | 2 blocks of 6 × 2 min, 91 min | 24 min |
| 5 | 5 × 2:30 @ 119 % | 3 blocks of 5 × 2:30, 118 min | 38 min |
| 8 | 5 × 3 min @ 119 % | 3 blocks of 5 × 3 min, 123 min | 45 min |
| 10, 11 | 6 × 3 min @ 119 % | **4 blocks of 6 × 3 min, 180 min** | **72 min** |

Plan No. 3's own peak is 20 min of VO₂ work; Plan No. 2's was 21. The only signal is the
"longer than your longest week" warning (weeks 2–11 all trip it), which never blocks (Decision
#389). The summary line does say "each of its 4 sets", so a careful reader can see it. Once he
accepts, lock pushes it to Zwift (Decision #99), the morning classes it as one hard session and
on a Green morning says "as planned"; Red-never-VO₂ is the only gate, and nothing between the
editor and the trainer looks at dose. The coach's offers use the same list and validator
(AI329-02: it checks shape only), so "make week 10 six threes" from the chat produces the same
session. Separately, he **cannot** express his own progression at all on a 4-set Tuesday: the
set count is not editable and "add" offers only Zone 2, easy, long or dumbbells.

**What Mark experiences.** A plan he edits in good faith from Mon 12 Oct can carry a session no
coach would write; he would most likely notice the 180 minutes, but nothing stops it.
**Fix.** In `plan_changes._change_intervals` (and the session interval editor): refuse a result
whose work above 106 % FTP exceeds a bound (for example 1.5 × the plan's own peak, or 30 min),
say the total in the summary ("24 × 3 min = 72 min at 119 %"), and either expose the set count
or treat the five numbers as the whole session when the shape changes from micro-intervals to
long ones. About half a day with tests. **Where:** before 21 Oct if Craig agrees (adds caution
only; Mark can edit from 12 Oct), else first in the G8 run.

### CI330-02 — Med-High · After the ramp test the app keeps grading him against 280 W

**Evidence: implemented + proved** (`probe_plan3_engine.out` §4).

Plan No. 3 tells him: "Your new FTP is three-quarters of the best minute you held: set it in
Zwift, and every session follows" (Decision #387: "His FTP stays 280 W in the plan … The test
sets the next FTP, which he sets in Zwift"). Zwift's targets are percentages of **Zwift's** FTP
(`_intervals_description` sends only %), so the trainer follows. **The app does not:** its FTP
is the profile row's `ftpWatts` (`WorkoutDeliveryService._ftp_watts`, `post_workout_analysis`),
which no screen or job changes. Every post-ride grade divides his watts by 280. Driving the real
`ride_intervals._adherence` with ERG-perfect execution at a new Zwift FTP:

| New FTP | Sweet spot 89 % | VO₂ 1 min 120 % | Zone 2 65 % |
|---|---|---|---|
| 260 W (−7 %) | **under** | **under** | on |
| 265 W (−5 %) | on | **under** | on |
| 270–290 W | on | on | on |
| 300 W (+7 %) | **over** | **over** | on |

A ramp test's 75 % factor is a population constant set by its developer, not independently
validated; protocols differ by tens of watts for an individual (Karsten 2021: critical power
against 20-min FTP, 95 % limits −19 to +33 W, "should not be used interchangeably"), and his
last test was a 20-min one on 27 Jan (289 W). A move of 5 % or more either way is plausible.

**What Mark experiences.** From Thu 22 Oct, post-ride reads tell him he rode under (or over)
target on sessions ERG held perfectly — the exact complaint he made on 8 Sep about VO₂ reads —
and the deviation verdict, the outcome proxies, `block_progression`'s hit rate and 319's
planned "ready to progress" note all read the wrong number. The post-ride reads also quote his
FTP as W/kg from 280 W (7 Oct: "FTP is 3.61 W/kg"). **Fix.** The test's own ride computes the result (best one-minute power × 0.75) and offers
one tap that writes it to the profile and tells him the same number for Zwift; the next plan
starts from it. About a day. **Where:** fold into **319** as its first item (319 decayed: see §5),
landed before the 22 Oct sweet spot; bridge: Craig updates the profile FTP by read-modify-write
when Mark reports his number (production write, Craig's call).

### CI330-04 — Med-High · Plan No. 3's test, VO₂ work and recovery weeks can be removed or loaded one tap at a time, and no one is told

**Evidence: proved** (`probe_plan3_engine.out` §1–3, `probe_plan_changes.out`) + R3's paid
probe (AI329-02) + **implemented**.

The lens's standing question, answered for Plan No. 3 (Decision #389: the ramp test "only moves
or goes"):

- **The ramp test and all 13 VO₂ sessions** can be removed, by Mark or by tapping 14 coach
  offers, each accepted with no warning. Minutes above 106 % FTP fall from 8–21 a week to 1.2
  (the Saturday sprints). The only warning in the list (week longer than 453 min) cannot fire on
  a removal. R3's probe has the coach offering to remove the test on the first ask.
- **The ramp test can move to Fri 15 Jan** (the taper week) or onto Friday's rest day: accepted.
- **A recovery week can be loaded past any build week** — week 3 at 470 min with 6 × 3 min
  VO₂ and 2 × 30 min sweet spot — and keeps its "recovery" label. Batch 265's periodisation audit
  compares labels (`plan_periodisation.audit_plan_periodisation`), and the morning reads his
  HRV against his recovery-week normal in that week (Batch 275), so both treat it as a recovery
  week. Turning only the three recovery weeks' sweet spot into 2 × 30 @ 90 % raises no warning.
- **A VO₂ session hollowed to 60 %** keeps "VO₂" in its title and still classes as a key session,
  so the weekly review's key-session count is unchanged.
- **A change of days rebuilds the plan and silently restores the test** while dropping every
  other single-session edit (stated to Mark; it is also the only way removed protections return).

Who would notice: Mark (it is his change); the coach (its compact view carries the last 20
changes); **not Craig** — `next_plan_changed` is an info log (Railway keeps about 7 days), the
draft's `changes` list sits in a knowledge-base row no screen of his reads, and after lock the
engine judges adherence against the edited plan, so a stripped plan reads as perfect adherence.
It is Mark's plan, and the flexibility is Craig's deliberate choice; the integrity gap is that
nothing records what the change cost. **Fix:** at accept, a one-screen "as proposed → your
plan" of the protected kinds (test kept/moved/removed, VO₂ sessions and minutes, each recovery
week's minutes above 88 %), shown to Mark before he confirms and logged with the `admin_alert`
tag; the periodisation check reads load, not labels. About a day. **Where:** after G8, or
zero-code before 19 Oct: Craig reads the draft's `changes` (one SQL read) the day Mark accepts.

### CI330-03 — Medium · A ramp test on a tired morning is eased or swapped for a pick, never moved

**Evidence: proved** (`probe_plan3_engine.out`, `probe_invariants.out`).

The test (`bike_threshold`, steps to 146 %) classes as hard VO₂. Over the 295 grid its actions
are as planned (Green), recovery (Red), off the bike (floors), `move_or_hold` or, in a light
week, `hold_targets` (one mild concern), `ease_hard` (Amber), `pick_zone2_or_tempo` (tired Amber). Through the real transforms:

| Morning | What Zwift would be offered |
|---|---|
| Amber (`ease_hard`) | "Hard work eased: FTP Ramp Test", 40 min: every step above 75 % drops 13 points, **capped at 94 %** (top step 94 % instead of 146 %) |
| Tired Amber (pick) | ramp capped at 75 % or 85 % |
| Red | 20-min recovery spin |

The eased versions are offered, not applied; but if he takes one and follows the plan's own
instruction ("ride it until you can't hold the step"), he holds every step and the formula gives
**197 W** (0.75 × 263). If he rides the full test on a fatigued morning instead, the result is
depressed and sets every target for 13 weeks. Neither the morning nor the post-ride read knows a
session is a test. Coaching practice is to test fresh or move the test; here only the one-mild-
concern case says "move". With his 7-day HRV still marked on 10 Oct (41 against 46), an Amber
20 Oct is plausible. **Fix:** a session of kind `test` takes only "as planned" or "move it
within the week" (and off the bike on a floor); the post-ride read reports the test's number and
refuses to compute one from an eased ride. Small. **Where:** 319 (with CI330-02). Bridge
before Tue 20 Oct (zero code): tell Mark that if Tuesday is not "Green light" or "As planned",
move the test with Swap rather than ride an eased one.

### CI330-05 — Medium · Plan No. 3 sets aside Mark's own documented VO₂ progression without saying so

**Evidence: observed** (`~/Downloads/Dad Fitness/Current 13 week 2121 Plan Vo2 Issues
28.08.26.docx`; the draft) + **computed** + the ledger.

His 28 Aug document records that the jumps in Plan No. 2's VO₂ work were "too sharp" (6 × 2 →
6 × 3 min; 30/30 → 40/20), and closes with a 13-week progression for the next block built from
sustained intervals (5 × 2 → 6 × 2 → 4–5 × 2:30 → 30/30 and 40/20 → 4, 5, 6 × 3 min). The ledger
recorded it on 16 Sep as a real question to raise with him on 18 Oct. Batch 323 used the
toolkit's protocols instead (30/30 at 130 % in weeks 2–5, Rønnestad 30/15 at 125–128 % in weeks
7–11) and the "why this plan" note does not mention his. The week 5 → 7 step is the kind he
called too sharp: 30/15 at 125 %/55 % has the same set-average power (102 % FTP) as the 40/20 he
struggled with, at a larger dose (2 × 12 min against 2 × 10). Sustained 2–3-min VO₂ efforts
appear only in recovery weeks. The evidence for 30/15 is real but thin for him: one 10-week trial
of 16 trained cyclists (Rønnestad 2015: VO₂max +8.7 % against +2.6 % for 4 × 5 min, P = 0.05;
participants about 33 years old per secondary summaries), and a 2020 follow-up in elite riders
where the advantage showed in power, not VO₂max. Nothing in it addresses a 57-year-old. Either
protocol is defensible; dropping his without a word is not. **What Mark experiences:** on 12 Oct
he meets a plan whose VO₂ is not the progression he wrote, and (CI330-01) he cannot enter his own
on the 30/15 weeks. **Fix:** zero code — Craig shows Mark his progression beside the draft;
with CI330-01's fix he can then choose. Optionally a second VO₂ track in `next_plan.WEEKS`.

### CI330-06 — Medium · No key session has been ridden at full since 12 Sep, and the plan resumes at build intensity on day 2

**Evidence: computed** (`scratchpad/wave5/r4/key_sessions.json`, heuristic matcher).

Key sessions (VO₂, threshold-type, long rides), planned against what reached the trainer and
what he rode:

| Month | Planned | As planned | Moved, ridden as planned | Eased | Self-edited | Replaced / lost | Holiday | Not ridden / future |
|---|---|---|---|---|---|---|---|---|
| Jun | 6 | 5 | 0 | 0 | 0 | 0 | 0 | 1 |
| Jul | 11 | 4 | 2 | 0 | 2 | 1 | 2 | 0 |
| Aug | 16 | 5 | 3 | 2 | 4 | 1 | 0 | 1 |
| Sep (to 29) | 15 | 5 | 2 | 2 | 1 | 4 | 1 | 0 |
| **Since 30 Sep** | **7** | **0** | 0 | 0 | 0 | 0 | 4 | 1 (+2 future) |

The last build-intensity sessions were his own edited VO₂ on 8 Sep (40/20 + 35/25), the 10 Sep
sweet spot (3 × 18) and the 12 Sep long ride (moved from the 13th); 15–17 Sep was a recovery week; 22 Sep's VO₂ was swapped, 24 Sep's sweet spot eased (he rode
his own 77-min ride), then the holiday. By the 20 Oct ramp test he will have had about five weeks
without a build session, and his taper (13–18 Oct) is the last two primers. Plan No. 3 then opens
with a maximal test on its day 2 and 30/30s at 130 % in week 2. A coach would re-enter with one
bridge week. The test straight after a taper is right for a fresh result; it will, correctly,
probably come in low, and that is the FTP the plan then builds on (CI330-02). **Fix:** none
needed in code; say it to Mark with the plan (the test number will reflect five light weeks, and
that is fine). A bridge week is optional (`start` can move the plan a week).

### CI330-07 — Low · The post-ride read explained away a signal that agreed with the morning

**Evidence: observed** (stored post-workout reads, 7 and 8 Oct; activities).

Both reads grade what he rode, correctly (7 Oct: 40 min at 66 % against 65 %, on target; 8 Oct:
35 min at 66 % against 62 %, on target). On 8 Oct, the morning was Red; his note said it felt "a
touch harder than last time"; heart-rate drift across the Zone 2 interval was **13.2 %**
against **3.4 %** the day before at the same power. The read called it "normal aerobic drift on
an easy ride rather than a durability red flag". His own long-ride drift has run 0.9–5.2 % (6 Oct
review, C.2). The read has no baseline for drift by session type, so it cannot see that a
quadrupling the day after a Red agrees with the call and with him. The same read promised
Saturday's sweet spot (3.0). **Fix:** carry his median drift for the session type into the
packet (cheap); a candidate line for 322.

### CI330-08 — Low · Honest silence still beats an honest "rough" (F5, widened)

**Evidence: proved** (`probe_f_series.out`). A clean morning with feel omitted is **Green**; the
same morning with an honest feel of 3 is **Red** (Batch 296: "Rough on its own makes the day
Red"; at Batch 239 it was Amber). A whole missing row is Amber (`INSUFFICIENT_DATA`). By design,
and Mark has never gamed it — he checks in every day and argues rather than omits — but the
incentive points the wrong way. **Fix:** none now; if a feel is missing on a hard-session morning,
Home asks before the call is final (321.2's territory). Recorded so the next refresh re-tests it.

---

## 4. Follow-through

Statuses: fixed (observed/proved/implemented) · open · shipped differently · superseded ·
queued. Every row re-verified on `42a6a98` or in production on 9–10 Oct.

### 4.1 The baseline findings F1–F8

| # | Finding | Status | Evidence |
|---|---|---|---|
| F1 | "Normal" self-recalibrates | **Partly closed; queued 311** | HRV now judged against his own 84-night normal (not Garmin's band), but that normal includes the week it judges and a holiday week lowers it for 12 weeks (DV-7); resting HR is still a moving median (HS240-15 carried in 311). implemented |
| F2 | Load cannot move the light | **Fixed** | Load ratio 1.6 alone → Amber; with 50 h recovery → Amber, hard session eased (proved). Replay: load marked on 9 mornings. Its 1.3 mild line is loosened by 316 (queued) |
| F3 | One-way sleep credit | **Fixed** | Age-credit guard decided 2 replayed mornings; a domain marked on Garmin's raw score counts (implemented, `verdict_grading` Batch 300) |
| F4 | No cumulative escalation | **Fixed** | Two marked domains → Red with readiness HIGH (proved); readiness confirms, never votes (DV-6 → 311). Four mild domains stay Amber, by design |
| F5 | Missing data cheaper than honesty | **Partly closed** | Whole missing row → Amber (proved); a missing HRV value or sleep score rates normal (DV-13 → 321.2); omitted feel → Green, honest 3 → Red (CI330-08) |
| F6 | Chronic overreaching advisory-only | **Unchanged (accepted)** | Still proposals; `verdictImpact` none. Not exercised since August |
| F7 | Corrections steer the narrative | **R3's area** | AI329-01: the coach concedes to Mark on rules it cannot see (8 Oct). Not re-tested here |
| F8 | Narrative does not soften the light | **Still resolved for the call; numbers slip** | 10 Oct brief opens "Take the edge off — Some fatigue" (observed); its one number misquotes the eased main set (3.0; DV-9 → 318); colour words still reach him (AI329-03) |

### 4.2 Batch 239 (CI239-01…12) and the carried CI211-01 / CI191-01

| ID | Status | Evidence |
|---|---|---|
| CI239-01 `expected_training_debt` uncapped | **Fixed (implemented)** | `chronic_patterns`: corroborating load ≥ 1.0, one exclusion, two-day expiry (`TRAINING_DEBT_EXCLUSION_*`). No live Red has been excused since (none qualified) |
| CI239-02 un-eased default; gate not at the rail | **Shipped differently; the class recurred (CR327-01)** | `blocks_red_vo2` on every push and replace rail (implemented). Since 1 Sep: 10 eased rows pushed (one of them the 10 Oct row the swap re-pointed), 3 expired (one on a holiday morning), against 239's 7 of 18 pushed (observed). A pre-pushed ride is still never retracted; the eased ride needs his tap. 239's "watch" item was seen once — 8 Oct, Red, the substitution reached the trainer by his tap within 27 minutes — and the swap then carried it to the wrong day |
| CI239-03 Red longer than Amber | **Fixed** | `RED_ENDURANCE_DURATION_SCALE` 0.70 < Amber 0.75 (implemented); graded Amber keeps Zone 2 full length, Red shortens it (proved) |
| CI239-04 transform shortens every interval | **Fixed for VO₂ / sweet spot; one shape left** | Graded Amber keeps durations and drops intensity (proved, 10 Oct: 30 min at 76 %). Red recovery on a one-rep session still scales the rep: 8 Oct's substitution was 13 min of warm-up, a 5.5-min "Sweet Spot" step at 60 % and 10 min cool-down (observed). Harmless (all ≤ 60 %), odd-looking |
| CI239-05 Amber text bike-only | **Fixed** | Non-ride sessions take "Not a ride; the verdict's ride changes do not apply" (implemented) |
| CI239-06 perfect execution never earns FTP | **Fixed in code, superseded in practice** | `block_progression` gates on hit and under rates (implemented); Plan No. 3 replaces it with a test, which raises CI330-02 |
| CI239-07 strength invisible to load | **Fixed** | Strength is `INTENSITY_MODERATE` in the restructurer (implemented); coaching it is R5's |
| CI239-08 no periodisation check on import | **Fixed for import; blind to edits** | 265's audit runs on import and Week-ahead; it compares labels, so a loaded recovery week passes (CI330-04). Plan No. 3 itself is 2:1 throughout (observed) |
| CI239-09 generator never used, no overload | **Fixed (observed)** | Plan No. 3 (`next_plan.py`) progresses every build week; not yet accepted |
| CI239-10 two Zone-2 anchors | **Fixed** | 75 % classifies, 67 % prescribes (implemented) |
| CI239-11 data blackout → Green | **Fixed (proved)** | Whole missing rows → Amber |
| CI239-12 / CI211-01 stale proposals | **Fixed (observed)** | 0 rows `proposed`; 22 `expired` (the `proposal-expiry` job) |
| CI191-01 the Red that does not count | **Fixed with 239-01** | As CI239-01 |

### 4.3 Later findings in this lens (reviews of 22 Sep – 6 Oct)

| ID | Status | Evidence |
|---|---|---|
| R0922-14 a pre-pushed VO₂ stays after a Red | **Open; mitigated** | Never retracted (implemented); Red-never-VO₂ blocks any new VO₂ push; the 8 Oct Red was a sweet spot. Craig's call still unrecorded |
| 0928-CO-1 mild concern on easy day changes nothing | **Fixed** | Amber keeps Zone 2 as planned (proved, grid) |
| 0928-CO-2 nothing measures under-training | **Fixed in the weekly packet; not acted on** | `keySessions` in the weekly review (implemented); of the 5 key sessions due since 30 Sep, none ridden (CI330-06); the last review ran 20 Sep, and 27 Sep and 4 Oct were skipped as holiday |
| 0928-CO-3 one poor night not Red alone | **Fixed (proved)** | Sleep 55 alone → Amber |
| 0928-CO-4 recovery weeks read separately | **Fixed** | Recovery-week HRV normal (implemented); see CI330-04 for loaded "recovery" weeks |
| 1001-CO-1 light week holds on a clearly-off morning | **Fixed (proved)** | Grid: light-week hold only without a marked domain |
| 1001-CO-2 persistent dip never escalates | **Fixed** | 304's 3-morning persistence (replay: autonomic marked 19) |
| 1001-CO-3 Amber never shortens a ride | **Fixed (implemented)** | 306 offers the shorter long ride |
| 1001-CO-4 Amber VO₂ → 94 % at full length | **Fixed** | Tired Amber offers the pick (proved) |
| 1001-CO-5 planned training called "a little off" | **Fixed** | Hard yesterday counts only before a hard session (grid) |
| 1001-CO-6 ACWR 1.3 flags "optimal" | **Queued 316** | Never fired since 7 Oct |
| DV-1 nothing planned after 18 Oct | **Fixed (observed)** | Plan No. 3 draft active, revision 0, status draft, start 19 Oct |
| DV-2 nothing prompts progress | **Queued 319; decayed** | See §5 |
| DV-10 strength never coached | **Fixed in the draft** | Two loaded sessions a week (R5 judges them) |
| DV-12 swap withheld on an off-the-bike day untested | **Queued 321.1** | Still untested |
| VR1004-5 / 0929-9 flagged hard sessions 58 % vs 72 % on target | **Superseded by 322** | No new hard session ridden since 24 Sep |

### 4.4 The 6 Oct review's invariants, on today's code

| Invariant | Result | Evidence |
|---|---|---|
| Replay reproduces production | **10 of 10** graded mornings (111 stored, 21 Jun–10 Oct); 3 of 3 for 7–9 Oct before 10 Oct existed | computed (`replay_all_oct10.md`) |
| A worse input never gives a less cautious colour | **0 violations** in 798,336 one-step comparisons (VO₂ + Z2, sweet spot + long ride, the ramp test; normal and light weeks) | proved (`probe_invariants.out`) |
| …nor a less cautious session action | **505 violations, all the one named exception**: in a light week a Zone 2 or long ride "hold the targets" becomes "as planned" when something is clearly off — the same ride (Decision #373). DV-7's baseline drift is not on the grid | proved |
| Floors always win | Repo tests pass: 404 passed, 28 skipped (Postgres) locally; CI green at `42a6a98` incl. DB tests | proved |
| The words never contradict the call | Headline and reading agree on every 7–10 Oct surface read; the 10 Oct brief misquotes the eased number (3.0) | observed |
| Every surface shows the same call | Holds for the call; **not for the ride** (3.0) | observed |

**Ladder-against-graded disagreements, 7–10 Oct, for the trial table** (not scored here):

| Date | Shown (graded) | Ladder | Graded domains |
|---|---|---|---|
| Wed 7 Oct | Amber, "As planned" | **Red** | autonomic marked, sleep mild |
| Thu 8 Oct | **Red**, "Recovery day" | Amber | autonomic marked, sleep marked (readiness confirmed) |
| Fri 9 Oct | Amber, rest day | Amber | autonomic marked |
| Sat 10 Oct | Amber, "Take the edge off" | Amber | autonomic marked (7-day 41 vs 46.1), resting HR mild |

Two disagreements in four mornings, one each way; 8 Oct is the readiness-confirmation case 311
is to decide (HS332 found the Red right by the HRV trials). Batch 310 changed 2 of 111 mornings
(21–22 Jul) and none since the return (`--compare-without hrv_holiday_catch_up`).

### 4.5 Mark's own words since 1 Sep that concern coaching

From his chat turns (`brief_messages`, 83 turns), `feedback` (23 rows, 6 with text), check-in
notes as quoted in the reads, and his documents. UX complaints are R7's; health wording R6's.

| Date | What he said (short) | Status | Evidence |
|---|---|---|---|
| 3 Sep | Performance-condition reading of a sweet spot wrong | **Not re-checked** (data accuracy; no batch names it) | feedback row |
| 8 Sep | VO₂ jumps "too sharp"; consolidate with 35/25 | **Fixed for that session** (262–264: he rode his edited session); **not for the next block** (CI330-05) | chat, his 28 Aug doc |
| 8 Sep | VO₂ blocks "clearly hit 350w after erg build up" yet graded under | **Fixed for ≤ 30 s reps** (peak-graded); a 40-s rep is still held-average graded; returns via CI330-02 from 22 Oct | `ride_intervals.PEAK_GRADED_MAX_DURATION_SEC` |
| 13 Sep | Is the reduced workout "actually going to be better for me"? | **Fixed by the graded engine** (fewer, smaller cuts) | replay |
| 15 Sep | Needs a recovery week every third week, not five builds | **Fixed in Plan No. 3** (2:1), if he accepts it | draft |
| 18–23 Sep | Red from Garmin's HRV floor moving; "do not pass go" on one marginal metric; asks for grading | **Fixed** (294–296): replayed, 18 Sep Red → Green, 19 Sep Red → Green (held), 21–26 Sep Red → Amber, 27 Sep stays Red | computed |
| 22 Sep | Post-ride graded his swapped Z2 + sprints against the VO₂ | **Fixed** (278: matched on what was ridden; 7 and 8 Oct observed correct) | observed |
| 24 Sep | Cuts all week (VO₂ → Z2, 75 → 52 min, 89 → 47 min); "over cautious … undertraining" | **Mostly fixed**: graded Amber keeps Zone 2 and full length, eases intensity; replayed, 23 Sep's Z2 is as planned | computed |
| 25 Sep, 5 Oct, 7 Oct | Factor the holiday into the return | **Partly fixed**: 310 is live but fired on no return morning (his nights not yet back); the coach cannot see it (AI329-01) | replay; chat |
| 8 Oct | Metrics suppressed by the holiday; the coach is "often overly negative" | **R3's** (AI329-01); the call itself was right (HS332) | chat |
| 8 Oct | Sweet spot "already moved to … Saturday … showing there" | **Not fixed** — CR327-01; on 10 Oct Zwift holds a recovery spin | 3.0 |
| 8 Oct | Garmin's LTHR fell 147 → 141; is this HR shift expected after the break? | **Answered in chat; not used** — nothing in the app reads LTHR; CI330-07's drift is the same signal | chat |

---

## 5. G8 and parked rows re-verified (this lens)

| Row | Verdict | Note |
|---|---|---|
| **319** Progress has a signal | **Decayed** | Its premise ("the block generator, the only FTP-raising path … would not change Zwift's FTP"; acceptance "no automatic change to FTP") predates Plan No. 3's week-1 ramp test. It now needs CI330-02 (the test's FTP into the profile, by his tap) and CI330-03 (a test is moved, not eased) first, and its "three hard sessions at ≥ 90 % on target" note is meaningless until the app and Zwift share an FTP. `insights.detect_ftp_drift` at `:334` is still accurate |
| **322** Record what he rode | **Accurate; extend** | Add the drift baseline (CI330-07) and grading against the version actually pushed (10 Oct would grade a recovery spin against a sweet spot) |
| **318** The brief is checked | **Accurate** | 10 Oct's misquoted eased number is its class (DV-9) |
| **316** Load line, recovery time | **Accurate; pointer drifted** | `_load` is at `verdict_grading.py:953`, not `:948`. Removes caution: after the trial, as planned |
| **311** HRV counted twice | **Accurate; pointer drifted** | `_domains` is at `:1070`, not `:978`. 8 Oct is a new readiness-confirmed Red to replay |
| **321** Three small fixes | **Accurate** | 321.1's rule sits at `morning_analysis.py` ~1290 (the `acute_swap` block); 321.2 also covers CI330-08's missing-feel case |
| **308** The ladder goes | **Accurate** | Grid and replay give it a clean base; the ladder disagreed on 7 and 8 Oct |
| **317, 320** | **Accurate** | Not exercised in this lens |
| **276** Dispute suppression | **Accurate; still not fired** | 0 disputes recorded |
| 208, 209, 210 | Not this lens | — |

---

## 6. For reconsideration

- **Decision #387 ("His FTP stays 280 W in the plan … which he sets in Zwift").** New
  evidence: the app grades every ride against its own FTP, not Zwift's (CI330-02). Keep 280 for
  the draft; change "he sets in Zwift" to "he sets in the app and Zwift".
- **Decision #389, "the ramp test only moves or goes".** Sound for edits. New evidence: the
  morning can still ease it (CI330-03), and removal raises no flag anywhere Craig looks
  (CI330-04). Add: "and the morning only moves it", and a lock-time diff.
- **Decision #389, "a week longer than his longest warns and never blocks".** Sound for minutes.
  New evidence: minutes are the wrong guard for VO₂ dose (CI330-01). Keep the warning; add a
  dose bound that does block.
- **Decision #99 (push-on-plan-set) with Batch 173.1's "deliberately acted" rule.** New
  evidence: an approval on one day now freezes a different day's ride after a swap (CR327-01,
  10 Oct). R1 proposes the fix; the decision itself can stand once the swap carries planned
  content.

## 7. Hypotheses (unverified)

- The 8 Oct 10:45 "Sweet Spot has quietly gone at risk" message (R3 calls it a false alarm)
  was computed from the 09:40 morning's mix (today's sweet spot eased, nothing left) before the
  swap; by accident it was right — no sweet spot will reach the trainer this week. Not traced.
- Mark will most likely see "Recovery substitution" in Zwift's workout name today and ride
  something else; whether the app then grades it against the sweet spot depends on 278's match.
- A ramp test straight after a taper and five light weeks will read low; the plan's sweet-spot
  peak (2 × 40 @ 92 %) is then set on a low FTP, which is the safe direction.

## 8. Limitations

- **What he rode on 10 Oct**: no activity by about 08:05 UTC, when this pass finished (see 3.0).
- **No paid calls.** The coach's steerability is R3's one-sample probe (AI329-02); I re-ran the
  validator, not the model.
- **The key-session table** uses a heuristic matcher (same title within ± 7 days); September
  may be off by one (the 6 Sep long ride matched a 30 Aug row).
- **Home's exact text** for 10 Oct was not rendered; R1 and R7 own it.
- **Physiology sources:** Rønnestad 2015 read through its abstract as quoted in search results
  (PubMed blocked the page); Karsten 2021 read in full on PMC. No independent validation of the
  ramp test's 75 % factor was found.
- **DB-backed tests** skip locally (28); CI ran them green at `42a6a98`.

## 9. Probe log

| # | What | Result size |
|---|---|---|
| 1 | `railway run` replay, all stored mornings, `--compare-without hrv_holiday_catch_up` (rolled back; `pg_stat_activity` clean after) | 111 mornings, report ~27 KB |
| 2 | Earlier replays (9 Oct, all and 7 Oct onward) reused | 110 / 3 mornings |
| 3 | Plan No. 3 dump (`dump_plan3.py`, 9 Oct, rolled back) reused | 1 row, 101 KB in scratch |
| 4 | Key sessions (`key_sessions.py`, 9 Oct, rolled back) reused | 55 sessions |
| 5 | SQL: morning and post-ride analyses 6–10 Oct (projected) | 8 rows |
| 6 | SQL: delivery proposals 6–19 Oct; planned rows 6–19 Oct | 11 + 14 rows |
| 7 | SQL: three proposals' IR heads and step summaries | 3 rows, ~4 KB |
| 8 | SQL: post-workout outputs 7–8 Oct | 2 rows, ~6 KB |
| 9 | SQL: feedback since 1 Sep; Mark's chat turns since 1 Sep; 8 Oct 09:30–11:30 thread | 23 + 83 + 15 rows, ~40 KB |
| 10 | SQL: proposals by origin/status since 1 Sep; all by status | 9 + 3 rows |
| 11 | SQL: 10 Oct morning (call, actions, domains, brief text); 10 Oct proposals; 10 Oct plan row | 1 + 1 + 1 rows, ~9 KB |
| 12 | SQL: activities since 9 Oct (twice) | 0 rows |
| 13 | Prong A in memory: `probe_plan3_engine.py`, `probe_mark_vo2.py`, `probe_plan_changes.py` (9 Oct, its classification columns superseded — the wrapper lacked `version`), `probe_oct10.py`, `probe_invariants.py` (798,336 comparisons), `probe_f_series.py` | scratch outputs |
| 14 | Local pytest, 14 verdict and plan test files | 404 passed, 28 skipped |
| 15 | `gh run list` main | CI green at `42a6a98` |

Total production reads for this pass: well under 1 MB.

**References.** Rønnestad BR et al. (2015) Short intervals induce superior training adaptations
compared with long intervals in cyclists — an effort-matched approach. *Scand J Med Sci Sports*
25:143–151. Karsten B et al. (2021) Relationship between the critical power test and a 20-min
functional threshold power test in cycling. *Front Physiol* 11:613151.
