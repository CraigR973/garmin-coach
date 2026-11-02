# Batch 356–363 — follow-through table (companion to the remediation roadmap)

Every finding of review wave #5 (Batches 327–333, 10 Oct, 60 findings) and every earlier row
still carried at wave #5 (38 rows), with its status on 1 Nov 2026 at `083e012`. Built read-only
by the pack step from the ledger, `DECISIONS.md`, `STATUS.md` and the code; then **re-verified in
each lens by the eight passes, whose corrections come first and win over the rows below**; then
checked in synthesis against production and the code. Roadmap:
[`BATCH_356-363_REMEDIATION_ROADMAP.md`](BATCH_356-363_REMEDIATION_ROADMAP.md).

**Statuses:** fixed (with its evidence label) · partly · shipped differently · open · deferred ·
accepted · superseded · closed. *Claimed* means only a ledger row or decision says so.

## Corrections made by the passes (they override the rows below)

| Row | Pack said | Now | By |
|---|---|---|---|
| CR327-02 | fixed (implemented) | **partly**: open in the backstop's per-step handler; 3 of 341's reloads untested (CR356-01/02) | R1 |
| CR327-05 | fixed (claimed) | fixed (**proved**: removing the lock fails 2 tests) | R1 |
| CR327-06 | fixed (claimed) | fixed for `brief_messages`; the class open on one `manual_entries` column (CR356-07) | R1 |
| DS328-02 | open; who runs the crons unknown | open, **premise changed**: the crons never run a job; the scheduler runs both (DS357-03) | R2 |
| DS328-11 / DS237-04 | open | open and wider: archives unencrypted on the breached platform (DS357-04) | R2 |
| DS237-06 | 42 unrevoked, expiry unchecked | **16 live** 365-day device tokens; 26 expired; still deferred | R2 |
| AI329-01 | open | open, confirmed: the chat sees fired rules only, and not why a morning has no call | R3 |
| AI329-05 | fixed (claimed) | fixed (**proved**: 15 crafted provider errors classify as intended) | R3 |
| AI329-07 | fixed (claimed) | **partly**: colour words blocked; health steering passes (AI358-04, HS361-04) | R3, R6 |
| AI238-05 | open (zero thinking) | **accepted** as a variable: every brief since v60 thought (AI358-06) | R3 |
| AI238-09 | partly | fixed for chat: 25 of 26 answers since 21 Oct carry usage and cost | R3 |
| CI330-01 / -03 | fixed | fixed (**proved**: dose bound on all three edit paths; a test is moved, never eased) | R4 |
| CI330-02 | fixed (claimed) | fixed (**observed**: rides graded at 267 W) | R4 |
| CI330-06 | shipped differently | **resolved by the athlete**: 5 of 5 key sessions in full since the test | R4 |
| DV-2 (319) | fixed (claimed) | **partly**: built, but empty under ERG (CI359-02, ST363-02) | R4, R8 |
| HS240-15 | not in 311 | open: the resting-HR rail has no judged-week or nights-away leave-out | R4 |
| FC331-01 | fixed (claimed) | **partly**: delivery to the watch built; matching and top weight never built; false completions 21 and 26 Oct (FC360-01) | R5 |
| FC331-02 | fixed (claimed) | fixed for Red and the chest follow-up; the bike-rest floor open (FC360-05) | R5 |
| FC331-03 | open (live plan) | open and **wider**: 11 of 11 remaining A sessions precede VO₂ | R5 |
| FC331-04 / -05 / -07 | fixed (claimed) | **next plan only** (live rows unchanged); -07 harmless | R5 |
| FC331-06 | fixed (claimed) | **partly**: v8 sees load; the rollup still counts circuits (FC360-04) | R5 |
| HS332-01 | fixed | **partly**: only when a morning is stored (HS361-02) | R6 |
| HS332-03 | fixed (claimed, 318) | **open in what Mark reads**: REM against the age band in 10 of 25 briefs, bands misquoted | R6 |
| HS332-04 | shipped differently | **open, never built**: Decision #454 left it, no row held it; "toward 17C" sent 8 times | R6 |
| HS332-06 / -07 / -08 | fixed (claimed) | fixed (implemented) | R6 |
| HS240-12 / 0928-MD-5 | open | fixed by 339.4 (implausibly high HRV = watch notice) | R6 |
| 1001-MD-5 | open | **accepted by design** (respiration speaks beside a heart reading only) | R6 |
| UX333-01 / -03 | fixed (implemented) | fixed (**proved** in the shipped bundle; 8 of 8 failures in words) | R7 |
| UX333-02 / -06 / -07 / -09 | fixed (claimed) | **partly**: two controls on a tired morning; "No plan loaded" shadowed; REM asked daily; one raw date left | R7 |
| HS332-02 | fixed (claimed) | fixed, re-run; daily re-looks remain an error source (ST363-04) | R8 |
| HS332-09 | fixed (claimed) | fixed; the stored audit line prints the raw sign (ST363-08a) | R8 |
| DV-5 | fixed (claimed) | fixed (observed: one usual HRV since 29 Oct) | R8 |
| DV-7 | shipped differently | open, small: the holiday nights lower his usual HRV by 0.7 ms until late Dec | R8 |
| 1001-AI-5 / 6 | open | **resolved** by the evaluator: inconclusive with an interval | R8 |

**Synthesis corrections to the passes** (they override the pass reports):

| Item | Pass said | Now | Evidence |
|---|---|---|---|
| R4 closing note | Mark "got his call before he rode" (1 Nov) | Wrong: ride 11:59:37 UTC, brief ready 12:05:39 | observed |
| R4 lead for R5/R2 | 31 Oct Dumbbells B "still planned" may be wrong | The review is right: 1 Nov 08:53 is his bodyweight circuit, rightly refused for B | observed |
| R7 UX362-02 | 161 pushes | 162 (18 evening nudges, not 17); each sent once | observed |
| R5 FC360-01 fix | "A is done if SQUAT, DEADLIFT or LUNGE appears" | All 7 circuits record SQUAT; match on hinge or lunge plus a loaded session | observed |
| R6 HS361-01 | ≥20 °C asleep on 1 of 12 critical nights | 1 of 13 (31 Oct's night now measured: mean 19.5 °C) | observed |
| Pack LIVE §5 | thermal `info` 9, evening nudge critical 7 | info 15, evening nudge critical 8 | observed |
| R2 DS357-02 | 10 of 66 error sites tagged | 10 of 66–70 (the count depends on the pattern) | implemented |

---

## Summary

### Wave #5's 60 findings, after the corrections

| Pass | n | fixed | partly | shipped diff. | open |
|---|---:|---:|---:|---:|---:|
| 327 code | 7 | 4 | 2 | 0 | 1 |
| 328 ops | 11 | 3 | 1 | 0 | 7 |
| 329 AI | 7 | 4 | 1 | 1 | 1 |
| 330 coaching | 8 | 8 | 0 | 0 | 0 |
| 331 strength | 7 | 2 | 4 | 0 | 1 |
| 332 health | 10 | 7 | 1 | 0 | 2 |
| 333 UX | 10 | 6 | 4 | 0 | 0 |
| **Total** | **60** | **34** | **13** | **1** | **12** |

The pack counted 47 fixed from the ledger; the passes found 13 of those only partly done. Of
the 34 fixed, 26 are seen in the code or production and 8 rest on a claim.

### The 38 carried rows, after the corrections

14 fixed · 2 partly · 4 shipped differently · 8 open · 4 deferred · 4 accepted · 1 superseded ·
1 closed (the pack had 12 fixed, 13 open).

### Every earlier High still open

1. **DS328-01 / DS237-01: a failure reaches Craig.** Open since 1 Sep. Live example 1 Nov (DS357-01, -02).
2. **DS328-11 / DS237-04: no backup ever restored.** Drill skipped 9 of 9.
3. **DS328-04: the public repo carries a household's identity and Mark's health data.** 338 decision-gated.
4. **HS240-08 → HS332-04 → HS361-01: the bedroom thresholds.** Open through three waves; now High.

UX333-01 and CR327-01 (wave #5's other Highs) are fixed and proved.

### Wave #5's coverage claim, checked

"Every one of the 60 has a home" was true on paper. In delivery: 8 sat in rows that never
shipped (337 deferred holds 7, 338 holds 1), and **three were lost inside folds into queued
rows**: AI329-01 (into 317, never built), HS332-04 (into 320, left by Decision #454 with no row),
and FC331-01's matching (moved to 322, never built). This roadmap folds only into 345, an
in-progress row whose close-out names them.

---

## 1. Wave #5's 60, row by row

Status now · evidence · where it goes (wave #6 row or finding).

### 327 — code
| ID | Sev | Now | Evidence · home |
|---|---|---|---|
| CR327-01 | High | fixed | implemented + observed (live-ride check found 0 to 1 Nov) |
| CR327-02 | Med-High | partly | proved · CR356-01/02 → 365 |
| CR327-03 | Medium | fixed | implemented (0 `VERDICT_ENGINE` in src); residue → 373 |
| CR327-04 | Medium | partly | computed · CR356-04 deferred |
| CR327-05 | Low | fixed | proved |
| CR327-06 | Low | fixed | implemented; class → 373 (CR356-07) |
| CR327-07 | Low | open | implemented · 337.6 |

### 328 — data, security, ops
| ID | Sev | Now | Evidence · home |
|---|---|---|---|
| DS328-01 | High | open | implemented · 365 (watchdog), 337.1 (Sentry) |
| DS328-04 | High | open | observed · 338 (decision 8) |
| DS328-02 | Med-High | open | computed · 371 (crons), 365 (watchdog) |
| DS328-03 | Medium | fixed | implemented (Batch 348) |
| DS328-05 | Medium | fixed | observed (split backup; first full archive 1 Nov 03:00) |
| DS328-06 | Medium | open | claimed · 337.6 |
| DS328-07 | Low | fixed | claimed |
| DS328-08 | Low | open | implemented · 365 (misfire grace), 337.7 |
| DS328-09 | Low | partly | claimed |
| DS328-10 | Medium | open | observed · decision 5 (GitHub guards), 337.5 |
| DS328-11 | Medium | open | observed · 371 |

### 329 — AI
| ID | Sev | Now | Evidence · home |
|---|---|---|---|
| AI329-01 | Med-High | open | implemented · not placed this wave: 364.3 gives the chat the morning state; the full `rulesInForce` trace stays open |
| AI329-02 | Medium | fixed | proved (steerability held 4 of 4) |
| AI329-03 | Medium | shipped differently | observed (3 of 3 v65 misses) · 369 |
| AI329-04 | Low | fixed | implemented |
| AI329-05 | Low | fixed | proved |
| AI329-06 | Low | fixed | claimed |
| AI329-07 | Low | partly | proved · 370 |

### 330 — coaching integrity
| ID | Sev | Now | Evidence |
|---|---|---|---|
| CI330-01 | Med-High | fixed | proved |
| CI330-02 | Med-High | fixed | observed |
| CI330-04 | Med-High | fixed | implemented (live edits unalerted: accepted as his autonomy) |
| CI330-03 | Medium | fixed | proved |
| CI330-05 | Medium | fixed | claimed |
| CI330-06 | Medium | fixed | observed (resolved by the athlete) |
| CI330-07 | Low | fixed | claimed |
| CI330-08 | Low | fixed | claimed |

### 331 — strength
| ID | Sev | Now | Evidence · home |
|---|---|---|---|
| FC331-01 | Med-High | partly | observed + proved · 368 |
| FC331-02 | Med-High | fixed | implemented; bike-rest floor → 368 |
| FC331-03 | Medium | open | observed · W0 (decision 2) |
| FC331-04 | Medium | partly | implemented (next plan only) |
| FC331-05 | Medium | partly | implemented (next plan only) · decision 2 |
| FC331-06 | Medium | partly | observed · 368 |
| FC331-07 | Low | fixed | implemented |

### 332 — health and sleep
| ID | Sev | Now | Evidence · home |
|---|---|---|---|
| HS332-01 | Med-High | partly | proved · 364 |
| HS332-05 | Medium | fixed | implemented + proved |
| HS332-02 | Medium | fixed | observed (re-run) |
| HS332-03 | Medium | open | observed · 369 |
| HS332-04 | Medium | open | observed · 366 |
| HS332-06 / -07 / -08 | Low | fixed | implemented |
| HS332-09 | Low | fixed | observed |
| HS332-10 | Low | fixed | claimed |

### 333 — UX
| ID | Sev | Now | Evidence · home |
|---|---|---|---|
| UX333-01 | High | fixed | proved |
| UX333-02 | Med-High | partly | proved · 372 |
| UX333-03 | Med-High | fixed | proved |
| UX333-04 | Medium | fixed | claimed |
| UX333-05 | Medium | fixed | implemented |
| UX333-06 | Medium | partly | proved · 372 |
| UX333-07 | Medium | partly | observed · 372 |
| UX333-08 | Low | fixed | observed (rendered) |
| UX333-09 | Low | partly | observed · 372 |
| UX333-10 | Low | fixed | claimed |

---

## 2. The 38 rows carried at wave #5

| ID | 9 Oct | Now | Evidence · home |
|---|---|---|---|
| DS237-01 | open | open | = DS328-01 |
| DS237-04 | open | open | = DS328-11 |
| UX241-03 | open | fixed | proved (= UX333-03) |
| AI238-02 | queued 318 | shipped differently | observed (check exists; 3 of 3 v65 misses) · 369 |
| DV-2 | queued 319 | partly | proved · 367 |
| CI239-02 | shipped differently | fixed | observed (live-ride check) |
| HS240-05 | shipped differently | shipped differently | observed (band claim still made) · 369 |
| R0922-4 | shipped differently | shipped differently (sound) | — |
| 0928-SE-3 | shipped differently | superseded | the ladder is gone (#449) |
| HS240-08 | open | open, now High | observed · 366 |
| R0922-14 | open | open | implemented (a pre-pushed hard ride stays until he approves); 364 covers the no-call case |
| REM250-O1 / O2 / O3 | open / open / deferred | open | observed · 369 (O1); O2 needs clinical copy |
| HS240-09 | open | open | the thermal window is a clock window · 366 |
| HS240-12 / 0928-MD-5 | open | fixed | implemented (339.4) |
| 0928-MD-6 | open | fixed | observed (the call leads) |
| 1001-MD-5 | open | accepted | implemented (by design) |
| AI238-05 | open | accepted | observed (a variable, AI358-06) |
| AI238-09 | partly | fixed | observed (chat usage stored) |
| DS237-05 | deferred | deferred | observed (32 tables, RLS on, 0 FORCE) · 209 |
| DS237-06 | deferred | deferred | observed (16 live tokens) |
| DS237-07 / 08 / 10 / 13 / 14 | accepted | accepted | — |
| DS237-11 / 12 | closed | closed | — |
| CR236-10 | deferred | deferred | computed (`scheduler.py` 2,676 lines) · CR356-04 |
| CR236-11 | deferred | deferred | computed (`DashboardPage.tsx` 2,382 lines) |
| 1001-SE-9 | open | open | CI Postgres 16, production 17.6 |
| 1001-SE-8 | open | open | not re-checked (cosmetic) |
| 1001-AI-5 / 6 | open | fixed | observed (evaluator inconclusive with an interval) |
| 1001-AI-7 | fixed | fixed | observed (memory read runs nightly) |
| 1001-AI-2 | queued 311 | accepted | Craig kept it (3 Oct) |
| DV-4 / 5 | queued | fixed | observed |
| DV-6 / 7 | queued 311 | partly | DV-6 shipped differently; DV-7 open, small (R8) |
| DV-8, CO-6, VR0929-5, VR1004-3 | queued 316 | fixed | computed (rule-effect replay) |
| DV-9 | queued 318 | shipped differently | = AI238-02 |
| DV-11 | queued 320 | fixed | observed (evidence lines plain and honest) |
| DV-12 / 13 / 14 | queued 321 | fixed | claimed |
| DV-15 | queued 308 | fixed | implemented (§4 describes one engine) |
| 0928-AI-5 | queued 322 | fixed | observed (call-vs-ride record working, 31 Oct) |
| 1001-SE-5 | queued 308 | fixed | the ladder is gone |

**Also open, from the Batch 345 release review:** the pass-to-Craig alert reaching Sentry
(needs Craig's rule; AI358-07) and Mark's first v29 answers read.

## 3. Lessons for the next review

- **Folds into queued rows lose findings** (three this wave). Fold only into a row in progress,
  and name the finding IDs in that row's acceptance.
- **The ledger's "fixed" overstated delivery by 13 of 47** for wave #5. The pack's
  claimed/implemented split caught it; keep it.
- **Passes stamped planned end times** three times; the orchestrator corrected them from the
  transcripts. Stamp from `date` at the moment of writing.
