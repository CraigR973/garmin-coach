# Batch 356 — Code and architecture review (wave #6, pass R1)

**Pass R1** · reviewed SHA `083e012` (local `main` has no code drift past it on 1 Nov 01:35 GMT) · lens: senior software engineer · read-only · paid calls: **none ($0)**.
Run 1 Nov 2026, 01:21–01:40 GMT. Every probe ran on a throwaway Postgres 16 (`pgserver`) or in a throwaway clone under the session scratchpad; production was read with five projected SELECTs.

## 1. Summary

**Grade B+.** The code is in better shape than its size suggests: the full backend suite runs 3,222 passed / 0 skipped locally against a real Postgres, lint, format and strict mypy are clean, 15 of 18 surgical revert-the-fix probes fail the tests as they should, the four migrations are additive and round-trip cleanly, and the ladder's removal was a real deletion. What holds it below an A is one class, again: the rollback-then-read defect (CR236-01, CR327-02) is live a third time in the morning pipeline's per-step handler (proved), and three of the reloads Batch 341 added have no test that fails without them — the class is fixed per site, not as a class.

1. **Correct and safe?** Mostly. One proved defect: the 11:00 backstop's "isolated" steps are not isolated (CR356-01). No live harm observed.
2. **Honest with Mark?** In this lens, yes; the one risk is a backstop morning with a failed step losing its written brief (CR356-01).
3. **Doing its job?** The rule changes since wave #5 (311, 316, 336, 339, 318, 346, 335, 351) are each pinned by a test that fails when the rule is reverted (proved).
4. **Would a failure be noticed?** A step failure is logged, but the outcome counters misreport which step failed once CR356-01 fires; the job-level guard test (337.3) is still deferred.
5. **Cheap to run and change?** Getting harder: `morning_analysis.py` imports 45 other service modules; 507 lines of dead progression code and a 192-line regex reply that has never fired still ship (CR356-03…05).

## 2. Findings (at most ten, Highs first)

No High. One Med-High, three Medium, three Low.

### CR356-01 — Med-High — The backstop's per-step handler raises instead of isolating the step (CR236-01's class, a third time)
- **Evidence: proved.** `MorningBriefPipeline._isolated` (the per-step wrapper the 11:00 backstop uses, `BACKSTOP_POLICY` = `PER_STEP`) rolls back, then logs `profile_id=str(profile.id)`, and only then reloads the profile. The rollback has expired the profile, so the log line itself does IO and raises `MissingGreenlet` inside the handler. Probe (`probes/isolated_probe.py`, the real function on a real `AsyncSession`, scratch Postgres): a step that touched the database and then failed → **`sqlalchemy.exc.MissingGreenlet` escapes**; a step that failed before touching the database → returns 0 as designed. Every real step touches the database first (`_hold_scope` takes an advisory lock). With the id hoisted above the `try` (two lines), the same probe returns 0 and counts one failure (proved in the clone).
- **What it does when it fires (implemented):** the steps are amber regeneration (his eased ride to Zwift), the chronic deload proposal, the "brief is ready" push and the drivers precompute. A failure in either of the first two escapes to stage 2's handler, which records the morning as failed, sends "today's call is ready" and **returns before the deload step and before the written brief**. On a morning Mark has not checked in by 11:00, he gets the colour without a brief, and Craig's log says "follow-through failed" rather than which step broke. A failure in the push or drivers step is reported as a failed follow-through after the brief was written.
- **Has it fired? (observed):** not provably. `morning-sync` has 7 `degraded/step_failures` rows since 3 Sep (last 23 Oct); their counters fit input-sync failures, and the logs that would say more are R2's. Mark checked in on 25 of 25 days, so the backstop rarely has a brief left to lose. Not fast lane: no harm seen, and the fix is ordinary build work.
- **Fix and cost:** hoist `profile_id` before the `try` and log it (two lines), plus one real-`AsyncSession` test of `_isolated` that fails today (the probe is the test). Under an hour.
- **Where it goes:** a small new row, or the first item of 337 when it is undeferred; it is exactly the "guard test over every failure handler" 337.3 promised.

### CR356-02 — Medium — Three of Batch 341's reloads have no test that fails without them
- **Evidence: proved** (revert-the-fix in a throwaway clone, each mutation run against its batch's tests on a fresh Postgres). Removing each of these leaves every test green:
  - the reload between the month and season buckets in `run_trend_narratives` — **the very site of the 20 Sep outage CR327-02 named** (97 passed);
  - the reload after a failed push in the post-workout backstop (78 passed);
  - the reload after a failed reader in the same backstop (78 passed).
  By contrast the job loop's own reloads (3 failures), the router's CR236-01 reload (1 failure) and the draft lock (2 failures) are guarded.
- **Why it matters:** the class has now returned three times (CR236-01, CR327-02, CR356-01), each time at a site the previous fix did not cover, and each fix shipped with tests of the sites it touched only.
- **Fix and cost:** two parts, about half a day. (a) Real-session tests for the three sites above. (b) A class guard: a static check over every `except` block that does a `rollback()` and then reads an attribute of an ORM-shaped name before a reload. A rough version (`rbscan.py`, 25 lines of `ast`) run over all 2,724 functions found **exactly one true hit (CR356-01) and one false positive** — cheap enough to be a CI test.
- **Where it goes:** fold into 337.3 (the deferred guard test), and ask that 337.3 be split out of 337 so it does not wait on the Sentry decision.

### CR356-03 — Medium — The coach-voice trial shipped a reply keyed to one past question
- **Evidence: implemented + computed.** `source_backed_cut_reply.source_backed_floor_and_next_week_reply` (192 lines, **cyclomatic complexity 74, the highest in the codebase**) fires only when a chat question matches all six patterns at once: "HRV", "floor", "next week", "3/three recovery weeks", one of three phrases of concern, and a cut word. That is one historical question re-asked word for word. Production: **0 of 37 coach answers since 18 Oct** began with either source-checked opening (this one or the broader `source_backed_cut_opening`). Separately, `compose_source_backed_cut_answer` turns a model reply that calls the cut "minor/modest/small" into a 503 ("The coach couldn't answer just now") rather than a retry or a plain answer.
- **What Mark experiences:** nothing yet. The cost is to change: the module's narrowest path will never run, and its tests pin an evaluation case rather than a behaviour.
- **Fix and cost:** at 345's close-out, delete the floor-and-next-week path (keep the general cut opening if R3 judges it useful), and make the minimised-wording rejection retry once before failing. An hour or two.
- **Where it goes:** 345 (in progress). **Cross-lens → R3**, which owns whether the general opening earns its place.

### CR356-04 — Medium — Two modules carry the morning, and they keep growing
- **Evidence: computed** (AST counts at `083e012` against `42a6a98`). Functions 2,480 → 2,724; functions with complexity ≥ 30: 24 → 26; functions over 200 lines: 7 → 10. `morning_analysis.py` (3,616 lines) imports **45** other service modules, and `assemble_context_packet` is 561 lines at complexity 55; `daily_loop_envelope` imports 27 and **imports two routers** (`routers.daily_loop_schemas`, `routers.feedback`), the service→router coupling CR236-02/09 flagged. `scheduler.py` grew 2,368 → 2,676 even after nine job bodies moved onto the job loop. The ladder's removal was real: `morning_verdict.morning_verdict` (complexity 115, the old worst) is gone.
- **Why it matters:** the overnight run (Decision #451) put eight batches through these two files in one session; every rule change now edits the 561-line packet builder.
- **Fix and cost:** not a rewrite. When a batch next touches them: split `assemble_context_packet` by packet section (each section already has its own reader), and move each scheduler job body into its own module now that `job_loop` gives them one shape. Half a day each, done opportunistically.
- **Where it goes:** defer, trigger "next batch that edits either function"; keeps CR327-04 and CR236-10 open as "partly".

### CR356-05 — Low — Deletion residue: a dead progression engine, a field no screen reads, ladder-only branches
- **Evidence: implemented.**
  - `services/block_progression.py` (507 lines, "seed blocks from progression evidence", Batch 47) has been imported only by tests since Batch 323 replaced the generator's seed with `next_plan.py` (7 Oct). Batch 319 then built a second progression reader, `progress_signal.py`. Two engines for one idea, one of them dead.
  - `liveOrigin` (Batch 335) is computed, serialised and typed in the shared schema; no web screen or helper reads it.
  - `weekly_mix` keeps "under the ladder" branches (`actions is None`) that only a morning stored before 30 Sep can reach; the mix reads the current week, so in production they are unreachable. `stored_engine` reads any packet without an `engine` key as the ladder's, so a future writer that forgets the key would silently get ladder semantics.
  - `morning_analysis.py` still carries 9 comment lines saying "the ladder's v50 is unchanged" (19 ladder mentions in all) inside the prompt-version history.
- **Fix and cost:** delete `block_progression.py` and its tests; drop `liveOrigin` or use it; let `stored_engine` treat a missing key on a packet dated after 30 Sep as an error worth a log line; trim the comments. An hour; no behaviour change.
- **Where it goes:** any small cleanup row; R7 may want `liveOrigin` (the "what Zwift holds" line) rather than its deletion.

### CR356-06 — Low — A failed push throws away the paid post-ride reads it was announcing
- **Evidence: implemented.** In the 20:30 post-workout backstop each reader generates with `commit=False`, then `_push_new_analyses` pushes; if a push raises, it rolls the session back, which discards the reads just generated, and the loop moves to the next kind. The next run finds the session unread and pays for it again. The docstring says a push failure "never blocks"; it does not block, but it costs the read.
- **Fix and cost:** commit the reader's results before pushing (the push is already idempotent per activity). Minutes, plus a test.
- **Where it goes:** with CR356-02's backstop tests.

### CR356-07 — Low — One JSON column from the overnight run missed Batch 341's `none_as_null` fix
- **Evidence: implemented + observed.** Batch 341 (CR327-06) made three `brief_messages` columns store SQL NULL rather than JSON `null`. Migration 040's `manual_entries.tonight_advice_feedback_json` (Batch 320, built the night before) is a plain nullable `JSONB`, the same class. Production: 309 rows, all SQL NULL, 0 JSON nulls — no writer assigns `None` today, so it is latent.
- **Fix and cost:** `JSONB(none_as_null=True)`; one line, no migration. Better still, a test that every nullable JSONB column declares it (the class, not the site).
- **Where it goes:** the same cleanup row. **Cross-lens → R7/R8:** 0 of the 309 rows carry an answer to "did last night's advice help?" — two mornings since 320 went live; worth watching, not yet a finding.

### Where it is already near-optimal (no finding)
- **Tests:** 3,222 passed, 0 skipped, in 7 min 22 s on Postgres 16, identical to CI's 30 Oct count. `ruff check`, `ruff format --check` (416 files) and `mypy src` (209 files, strict) clean.
- **Revert-the-fix (proved):** each of these fails its tests when reverted — 335 swap carry (4), 336 test moved not eased (7), 339 chest follow-up on a no-hard-ride day (3) and its mobility swap (3), 311 catch-up on any dip (4), 316 load ratio from 1.5 (6) and recovery time on hard days (4), 318 call length (1), 346 long quote (4), 351 device key (2), 341 job loop (3), draft lock (2), transport retry (2), refusal (1), CR236-01's router reload (1).
- **Migrations 038–041:** four additive, nullable columns; `downgrade 037` then `upgrade head` round-trips cleanly (proved). 039's downgrade drops the memory read's cursor, so a rollback would make the next nightly read re-read all chat once (paid, small).
- **Web ↔ API contract:** only one enum was added to the shared schema since wave #5 (320's answer, optional), action words are open strings, the five fragile Home sections fall back one by one, and a test pins the knowledge-base section list to the API's. A stale cached PWA (update is by prompt, not automatic) is unlikely to break on a newer API.
- **Prompt versions after the overnight run:** 20 `PROMPT_VERSION` constants, no collision; the eight bumps of 29 Oct are each distinct.
- **The ladder's deletion (308):** a deletion, not a split. No `VERDICT_ENGINE` remains in `apps/api/src` (the pack's "one residual reference" is in a test asserting it is gone); the remaining "ladder" reads exist only to read mornings stored before 30 Sep (but see CR356-05).

## 3. Follow-through corrections (rows of the pack's table in this lens)

| Row | Pack says | Corrected to | Evidence |
|---|---|---|---|
| CR327-02 | fixed (implemented) | **partly fixed**: open in `MorningBriefPipeline._isolated`; 3 of 341's own sites untested | proved (CR356-01, -02) |
| CR327-03 | fixed; 1 residual `VERDICT_ENGINE` in src | fixed; 0 in src (the one hit is a test asserting deletion); some dead ladder-only branches | implemented |
| CR327-04 | fixed (partly), claimed | partly; numbers re-derived: 147 modules, `scheduler.py` 2,676, complexity ≥ 30: 26 functions | computed |
| CR327-05 | fixed, claimed | fixed, **proved** (removing the lock fails 2 tests) | proved |
| CR327-06 | fixed, claimed | fixed for `brief_messages`; the class is open on `manual_entries` (CR356-07) | implemented + observed |
| CR327-07 | open | open, accurate (337 deferred) | implemented |
| DV-15 | fixed (claimed) | fixed: `ARCHITECTURE.md` §4 describes one engine and the 30 Sep boundary | implemented |
| CR236-10 / -11 | deferred | deferred, accurate (`scheduler.py` 2,676; `DashboardPage.tsx` 2,382) | computed |
| 1001-SE-9 | open | open, accurate (local probes also ran on 16; production 17.6) | implemented |
| 1001-SE-8 | open | not re-checked (cosmetic) | — |

## 4. Queued and parked items in this lens, re-verified

| Item | Verdict |
|---|---|
| 337.3 (guard test over every failure handler) | Accurate, and now urgent: CR356-01 is the defect it would have caught. Recommend splitting it out of 337 so it does not wait on the Sentry decision. |
| 337.6 (deploy freshness by ancestry, CR327-07) | Accurate; `deploy-freshness.yml` still expects the exact head SHA of the CI run. |
| 345 (coach voice, in progress) | Carries CR356-03 at close-out. |
| 209, 338 | R2's; not re-verified here. |

## 5. For reconsideration · Hypotheses · Cross-lens leads · Limitations · Probe log

**For reconsideration.** None. No settled decision is contradicted by new evidence in this lens. Decision #460's description of the job loop (rules 1–5) is accurate for the nine jobs it covers; CR356-01 is outside its scope.

**Hypotheses (unverified).**
- H1: the FTP decision (336) is a read-modify-write of the whole profile section with no lock; two taps at once give the second a 500 on the unique `(user, section, version)` constraint rather than a clean 409. Harmless (the first write stands) but untested.
- H2: `release_connection` commits "with nothing pending" by convention only; a caller that reaches it with a pending write would commit it early. No such caller found; not probed.

**Cross-lens leads for the synthesis (not chased).**
- **R2 (P9):** `trend-narratives`' cron command runs the job only when London time reads exactly `12:30` (`HHMM = 1230`); a container that starts a minute late skips. The in-process scheduler also runs `trend_narratives`, so the in-process job is probably the real runner. `weekly-review` runs in both on purpose (Decision #266). Which runner wrote each `job_runs` row is R2's to read from Railway's history.
- **R3:** CR356-03's source-checked openings (0 uses in 37 answers); whether the general one earns its place.
- **R7/R8:** 0 answers to "did last night's advice help?" in two mornings since Batch 320 (CR356-07).
- **R2:** CR356-01 is visible only in logs; the `degraded` backstop rows of 14–23 Oct need their log lines to tell an input-sync failure from this one.

**Limitations.**
- Frontend: not run here (the worktree has no `node_modules`); CI's 643 web and 59 shared tests on `083e012` stand. Only the daily-loop parser and the schema enums were read.
- Production logs and Sentry not read (R2's lane), so CR356-01's "has it fired" rests on job counters only.
- The complexity numbers are an AST approximation of cyclomatic complexity (branches + boolean operands), the same script on both SHAs, so the trend is sound and the absolute values are approximate.
- Revert-the-fix used surgical mutations of each fix's core line(s), not whole-commit reverts (later commits touch the same files); a mutation that passes is a test gap for that line, not proof the batch is untested.
- Local Postgres is 16; production is 17.6 (1001-SE-9).

**Probe log** (all local unless marked PROD; nothing written anywhere but the session scratchpad).
| # | What | Result |
|---|---|---|
| 1 | Throwaway Postgres 16 (`pgserver`), `alembic upgrade head` | head `041` |
| 2 | `alembic downgrade 037` then `upgrade head` | clean both ways |
| 3 | Full backend suite on it | 3,222 passed, 0 skipped, 441 s |
| 4 | `ruff check`, `ruff format --check`, `mypy src` | clean / 416 formatted / 209 files no issues |
| 5 | AST complexity at `083e012` and `42a6a98` (`cc.py`) | §CR356-04 numbers |
| 6 | Service import graph (`imports.py`) and unimported-module scan | fan-out 45; 2 modules imported by no source (one is the test-only prompt registry) |
| 7 | Rollback-handler scan over all functions (`rbscan.py`) | 1 true hit, 1 false positive |
| 8 | `_isolated` probe, real `AsyncSession`, 2 variants | `MissingGreenlet` escapes after a DB touch; returns 0 with the id hoisted (in the clone) |
| 9 | 18 revert-the-fix mutations in a throwaway clone (`mutate.py`), baseline 430 passed first | 15 fail as they should, 3 pass (CR356-02); clone left clean |
| 10 | PROD `information_schema.columns` for `coach.job_runs` | 9 columns |
| 11 | PROD `job_runs` non-succeeded `morning-sync`, 60 days, 4 columns, LIMIT 12 | 7 rows, all `degraded/step_failures` |
| 12 | PROD `analyses` morning rows 22–24 Oct, 4 columns | 3 rows |
| 13 | PROD `manual_entries.tonight_advice_feedback_json` null/type counts | 309 rows, all SQL NULL |
| 14 | PROD `brief_messages` count of the two source-checked openings since 17 Oct | 0 and 0 of 37 answers |
| — | Paid calls | **none, $0** |

Production reads were single SELECTs through the Supabase MCP (autocommit, no transaction held open), columns projected, no JSON blob selected. Throwaway Postgres stopped at the end of the pass.
