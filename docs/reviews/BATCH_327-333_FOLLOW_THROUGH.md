# Batch 327–333 — follow-through table (companion to the remediation roadmap)

Every finding of audit wave #4 (Batches 236–241, 1 Sep) and of the reviews since (3 Sep –
6 Oct), with its disposition on 9 Oct 2026 at `42a6a98`. Built read-only by a helper from the
ledger, `DECISIONS.md`, `STATUS.md` and the code; then **re-verified in each lens by the seven
passes**, whose corrections are listed first and win over the rows below. Roadmap:
[`BATCH_327-333_REMEDIATION_ROADMAP.md`](BATCH_327-333_REMEDIATION_ROADMAP.md).

## Corrections made by the passes (they override the rows below)

| Row | Table says | Corrected to | By |
|---|---|---|---|
| CI239-07 | fixed | **partly fixed** — strength still never reaches a load rule (load ≤ 14 across 49 sessions) | R5 (FC331) |
| CI239-02 | shipped differently | **shipped differently, and a new path found:** a swap moves one morning's easing to another day (CR327-01) | R1 |
| CR236-01 | fixed | **fixed where found; the class returned twice** (CR327-02) | R1 |
| DS237-01 | open | **open, and wider:** only 7 alert kinds carry the tag; storage, egress, backup, drill, watchdog and job-crash alerts do not (DS328-01) | R2 |
| DS237-03 | fixed | **partly fixed** — the meter is labelled honestly but still cannot see the billed direction (DS328-05) | R2 |
| DS237-15 | "premise false when written" | **that note is itself wrong** — see DS328-06 | R2 |
| AI238-05 | thinking tokens "only logged" | **wrong** — stored paths keep them; 17 of 43 briefs had zero thinking | R3 |
| UX241-03 | open, never placed | **confirmed open** (see UX333) | R7 |
| Levers (HS240-06 / 249) | "no lever currently passes" | **out of date** — levers pass on the live path for every flag; the cached path drops them (HS332-09) | R6 |
| STATUS "303.5" | open | **closed** — a later re-save no longer clears a symptom found in his note (proved) | R6 |
| 319, 321.1, 308, 210 | accurate | **decayed** (see the roadmap's G8 table) | R1, R3, R4, R5, R6 |

---

## Summary

**212 findings across 16 sources.** 124 fixed (53 seen in the code, 71 claimed only), 25 queued,
17 open, 8 shipped differently, 5 superseded, 1 dropped, 4 deferred with a trigger, 28 accepted
and closed.

### Counts by status

| Source | n | fixed | queued | open | shipped diff. | superseded | dropped | deferred | accepted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Wave #4 · 236 code | 19 | 11 | 0 | 0 | 1 | 0 | 0 | 2 | 5 |
| Wave #4 · 237 data/security/ops | 17 | 5 | 3 | 2 | 0 | 0 | 0 | 1 | 6 |
| Wave #4 · 238 AI | 17 | 10 | 1 | 1 | 1 | 0 | 0 | 0 | 4 |
| Wave #4 · 239 coaching | 12 | 11 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| Wave #4 · 240 health science | 19 | 10 | 1 | 2 | 3 | 1 | 0 | 0 | 2 |
| Wave #4 · 241 UX | 15 | 13 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| **Wave #4 total** | **99** | **60** | **5** | **6** | **6** | **1** | **1** | **3** | **17** |
| REM premise (3 Sep) | 7 | 4 | 0 | 2 | 0 | 0 | 0 | 1 | 0 |
| 268–275 review (22 Sep) | 14 | 11 | 0 | 1 | 1 | 1 | 0 | 0 | 0 |
| Verdict-grading review (28 Sep) | 20 | 16 | 1 | 2 | 1 | 0 | 0 | 0 | 0 |
| Replay (29 Sep) | 10 | 5 | 2 | 0 | 0 | 2 | 0 | 0 | 1 |
| Notes-reader eval (30 Sep) | 4 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 268–297 review (1 Oct) | 31 | 20 | 3 | 6 | 0 | 0 | 0 | 0 | 2 |
| Notes-reader eval (2 Oct) | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| Replay (4 Oct) | 5 | 1 | 2 | 0 | 0 | 1 | 0 | 0 | 1 |
| Rest-day replay (5 Oct) | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| Daily-verdict review (6 Oct) | 16 | 3 | 12 | 0 | 0 | 0 | 0 | 0 | 1 |

### Every High still open, queued or shipped differently (9)

1. **DS237-01 — open.** Alerts reach Sentry (DSN set 12 Sep, `admin_alert` tag since 291), but the Sentry rule that emails Craig is still his console step.
2. **DS237-04 — open.** No backup ever restored: `backup-drill` skips because `BACKUP_RESTORE_DATABASE_URL` is unset (Neon DB still Craig's, G4).
3. **UX241-03 — open, never placed.** A schema mismatch still shows Mark raw `ZodError` JSON; pages render `query.error.message` and no helper exists.
4. **AI238-02 — queued (318).** Only 244's warning-only heading check inspects output; content post-check and brief eval are DV-9.
5. **DV-2 — queued (319).** Nothing signals progress; waits for Plan No. 3 to be loaded.
6. **CI239-02 — shipped differently.** `blocks_red_vo2` guards every push rail, but a session pushed before a Red is never retracted and the eased ride needs Mark's tap (also R0922-14, open, Craig's call never recorded).
7. **HS240-05 — shipped differently.** REM test found the pattern real and the size uncertain; caveat stated; telling Mark (REM250-O1) and the GP-mention copy (REM250-O2) still open.
8. **R0922-4 — shipped differently (blocking).** 275's comparator got per-metric threshold and direction; Welch interval already existed. Sound.
9. **0928-SE-3 — shipped differently.** No 14-morning shadow (Craig, 28 Sep); ladder runs beside graded 7–20 Oct with a one-setting rollback.

Med-High still open: **HS240-08** (thermal thresholds at his median, below the WHO indoor minimum; never placed).

### Could not place, and caveats

- **The wave #4 roadmap's "all 99 mapped" is false.** Eight findings appear in no package, defer or accept list: AI238-05, AI238-08, AI238-09, HS240-08, HS240-09, HS240-15, HS240-17, UX241-03. All are placed below (291, 258, 268, 311, the age-credit guard reached four; UX241-03, AI238-05, HS240-08 and most of HS240-09 remain open).
- **DS237-15 was false when written:** `deploy-freshness.yml` (both health SHAs) existed from 15 Aug.
- **HS240-12:** ledger says fixed (254, display bands); the 6 Oct review says open (verdict grading one-sided). Recorded as shipped differently.
- **CR236-10:** its defer trigger (after W10) fired 4 Sep and nothing was scheduled.
- **71 of 124 "fixed" are claims only** (ledger or review), mostly Medium/Low. Every High marked fixed was checked in the code except 0928-SE-4 (ten colour consumers; only `weekly_mix` checked).
- Later-review docs without IDs were numbered here (`REM250-`, `R0922-`, `VR0929-`, `NR0930-`, `NR1002-`, `VR1004-`, `VR1005-`); the 28 Sep and 1 Oct reviews reuse CO/MD/AI/SE, so they carry `0928-`/`1001-` prefixes.

---

## 1. Audit wave #4 (Batches 236–241, 1 Sep 2026) — 99 findings

Sources: the six pass reports in `docs/reviews/`, the roadmap
`BATCH_236-241_REMEDIATION_ROADMAP.md`, and ledger rows 242–254 (all struck Shipped).

**Roadmap gap found while building this table.** The roadmap's coverage table says "all 99
mapped", but **eight findings are named in no package, defer list or accept list**:
AI238-05, AI238-08, AI238-09, HS240-08, HS240-09, HS240-15, HS240-17 and **UX241-03 (High)**.
Their rows below record what happened to each anyway (some were reached later by batches that
did not cite them).

### 1a. Batch 236 — code (19)

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| CR236-01 | Rollback expires ORM objects, so scheduler error handlers raise inside themselves | High | 242 | fixed | implemented | `session_recovery.restore_after_rollback` called in `scheduler.py` and `morning_pipeline.py`; reload, not session-per-iteration |
| CR236-02 | Morning brief has three entry points, two transaction contracts, no owner | High | 251 | fixed | implemented | `MorningBriefPipeline` + `CommitPolicy`/`MorningBriefPolicy`; wake job, backstop, check-in and retry all construct it |
| CR236-03 | Pipeline failure isolation tested only against mock sessions and profiles | High | 242 | fixed | implemented | `test_session_recovery.py` drives a real `AsyncSession` on `db_conn` (runs in CI only) |
| CR236-04 | Four post-activity services are 68–78% identical | Medium | 253 | fixed | claimed | `PostActivityReadRunner`; similarity now 0.61–0.73 |
| CR236-05 | `workout_type` is free text with ten classifiers, two disagreeing | Medium | 253 | fixed | claimed | One shared vocabulary pinned to the TS table; CHECK constraint deliberately not taken |
| CR236-06 | Transport exception carries domain control flow across four layers | Medium | 251 | fixed | claimed | `GenerationRequestInProgress` no longer an `HTTPException`; one 409 handler |
| CR236-07 | Central verdict is a 261-line, complexity-32 function | Medium | 245 | fixed | claimed | Pure move to `services/morning_verdict.py`; 80 stored verdicts byte-identical |
| CR236-08 | Alembic offline path omits `version_table_schema` | Medium | 253 | fixed | claimed | Offline SQL now puts `alembic_version` in `coach` |
| CR236-09 | `routers/daily_loop.py` is a serialization layer wearing a router's name | Medium | 251 | fixed | claimed | Router 1,747 → 250 lines; serializers in `daily_loop_envelope` |
| CR236-10 | `scheduler.py` is an application inside a module | Medium | none (roadmap defer) | deferred-with-trigger | claimed | Trigger ("after W10") met 4 Sep by 251, never scheduled; file now 2,368 lines |
| CR236-11 | `DashboardPage.tsx` is 2,230 lines holding 34 components | Medium | none (roadmap defer) | deferred-with-trigger | claimed | Trigger: next big change to it; now 2,300 lines |
| CR236-12 | Batch 184's "shared" projection assembly is still a copy | Medium | 253 | fixed | claimed | Four day-context loaders made one leaf |
| CR236-13 | `select(Model)` is the default idiom and nothing lints it | Low | 253 | shipped differently | claimed | No lint: `bulk_history_reads` documented entry point plus a `batch-verify` question |
| CR236-14 | Five orphaned backfill scripts ship in the image; two misnamed | Low | none (accept) | accepted-and-closed | claimed | "Fold into W12 opportunistically"; not done |
| CR236-15 | Nothing checks zod schemas and FastAPI models still agree | Low | none (accept) | accepted-and-closed | claimed | Only `workout_type` vocabulary is cross-pinned (253) |
| CR236-16 | CI measures coverage and ignores it | Low | none (accept) | accepted-and-closed | claimed | |
| CR236-17 | `run_scheduled.py` docstring and `JOBS` map have drifted | Low | none (accept) | accepted-and-closed | claimed | |
| CR236-18 | Migration round trip is checked one way only | Low | none (accept) | accepted-and-closed | claimed | |
| CR236-19 | Duplicated `except` bodies and duck-typed reason in `claim_generation_request` | Low | 251 (row 253 named it) | fixed | claimed | Closed by 251's single recorder with `isinstance` test |

### 1b. Batch 237 — data, security, ops (17)

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| DS237-01 | No operator alert reaches anyone, on any path | High | 242, 291 | open | implemented | Code half done (`observability.init_sentry`, `admin_alerts` tag; DSN set 12 Sep); Sentry email rule still Craig's console step |
| DS237-02 | Database at ~90% of storage cap, unmonitored | High | 247, 325 | fixed | implemented | `pg_database_size` summed over `pg_database` in `egress-budget`; purge 24 Sep, VACUUM FULL 7 Oct → 171 MB |
| DS237-03 | Egress meter wrong in three directions | High | 247.4 | fixed | implemented | Relabelled `http_response_bytes` with `measures=`; monthly comparison; pooler direction still unseen by design |
| DS237-04 | No backup has ever been proved restorable | High | 247.3 (G4) | open | implemented | `backup-drill` registered but skips: `backup_restore_database_url` empty; Neon DB + env var still Craig's |
| DS237-05 | RLS does not constrain the application (0/29 FORCE) | Medium | 209 | queued | claimed | Parked; Craig deferred 25 Sep (one profile) |
| DS237-06 | Thirteen live 365-day device tokens, no way to see them | Medium | none (roadmap defer) | deferred-with-trigger | claimed | Trigger: token compromise or second user; not fired |
| DS237-07 | Unused RLS-bypassing key required at startup | Medium | none (accept) | accepted-and-closed | implemented | `config.supabase_service_key` still required by startup validation |
| DS237-08 | Audit log records one thing, and not a user action | Medium | none (accept) | accepted-and-closed | claimed | |
| DS237-09 | F4 PII unmoved and wider than described | Medium | 253 | fixed | claimed | Packet no longer sends coordinates or `userId` to Anthropic |
| DS237-10 | Activation rate limit is one global bucket | Low | none (accept) | accepted-and-closed | claimed | |
| DS237-11 | Co-resident app's event trigger runs inside every migration | Low | 208 | queued | claimed | Parked row |
| DS237-12 | `coach` and public app share one advisor queue | Low | 208 | queued | claimed | Parked row |
| DS237-13 | Only production profile is `admin` | Low | none (accept) | accepted-and-closed | claimed | |
| DS237-14 | Activation codes travel in a query string | Low | none (accept) | accepted-and-closed | claimed | |
| DS237-15 | Stale-deploy detection is still human-only | Low | none (accept) | accepted-and-closed | implemented | Premise was wrong: `deploy-freshness.yml` polls both health SHAs, added 15 Aug |
| DS237-16 | A 401 clears the token but not the persisted brief | Low | 253 | fixed | claimed | |
| DS237-17 | Three residual Batch 235-class full-row reads | Low | 253 | fixed | claimed | Time-series reads and chat ownership check projected |

### 1c. Batch 238 — AI engineering (17)

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| AI238-01 | Morning brief's output contract is a stale four-item list | High | 244 | fixed | implemented | `morning_output_contract.required_morning_output_sections` → `prompt.requiredOutputSections` |
| AI238-02 | Nothing inspects generated output | High | 244, then 318 | queued | implemented | 244's heading check is warning-only (`morning_analysis_missing_required_sections`); content post-check + eval queued as DV-9/318 |
| AI238-03 | Daily paths alert only on billing; spend-cap wording unclassified | High | 248, 291 | fixed | implemented | Spend-cap wording → `billing` in `anthropic_text`; alert arrival depends on DS237-01's Sentry rule |
| AI238-04 | Transport failures bypass classification; nothing retries | High | 248 | fixed | implemented | `timeout`/`transport` reasons in `anthropic_text`; bounded retry inside the lease budget |
| AI238-05 | Adaptive thinking is an unmonitored variable the budgets rest on | Medium | none (unplaced) | open | implemented | `thinking_tokens` only logged (`anthropic_text._log_usage`); not persisted, no zero-thinking warning |
| AI238-06 | One honesty rule, eight hand-written copies | Medium | 253 | fixed | claimed | One constant, verbatim in 9 prompts |
| AI238-07 | Ninth generation path escapes the audit claiming it cannot | Medium | 253 | fixed | claimed | `AnthropicMessageBatchClient` added to discovery |
| AI238-08 | Deepest AI path (longitudinal) has never run in production | Medium | 291 (not cited by ID) | fixed | claimed | Sentry accepted as alert route; STATUS: monthly analysis runs again |
| AI238-09 | Highest-volume paid path (chat) records no usage | Medium | 258 (not cited by ID) | shipped differently | implemented | Usage only in `anthropic_usage` log lines; 258 measured chat caching from logs; nothing persisted on `brief_messages` |
| AI238-10 | Two JSON-extraction strategies; the fragile one writes memory | Medium | 253 | fixed | claimed | `conversation_learning` on structured outputs |
| AI238-11 | `BriefChatError` uncaught; chat ceiling unmeasured | Medium | 248 | fixed | claimed | Caught in both routers; input measured 48,981 tokens; output ceiling unchanged (paid turn not spent) |
| AI238-12 | Two `basis` strings for one fact; model quoted the wrong one | Medium | 253 | fixed | claimed | One sleep-stage denominator sentence |
| AI238-13 | Prompt-version → regeneration is three contracts, not one | Medium | 253 | fixed | claimed | `prompt_artifacts.orphaned_artifacts()` |
| AI238-14 | Age bands composed by the model from five raw numbers | Low | none (accept) | accepted-and-closed | claimed | |
| AI238-15 | A second, unwired copy of a shipped rule | Low | none (accept) | accepted-and-closed | claimed | |
| AI238-16 | Over-broad classification rules; batch path hardcodes 400 | Low | none (accept) | accepted-and-closed | claimed | |
| AI238-17 | Effort decision rests on an unreproducible measurement | Low | none (accept) | accepted-and-closed | claimed | Matters only if effort is revisited |

### 1d. Batch 239 — coaching integrity (12)

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| CI239-01 | First live Red excused as `expected_training_debt` on uncapped load | High | 252 | fixed | implemented | `chronic_patterns`: corroborator, two-day expiry (`training_debt_exclusion_expired`), shared cap |
| CI239-02 | Un-eased session is the Zwift default; Red-never-VO₂ skips delivery path | High | 243 | shipped differently | implemented | `blocks_red_vo2` on every push/replace rail; but pushed sessions are never retracted and eased ride needs Mark's approval |
| CI239-03 | Red prescribes a longer ride than Amber | Med-High | 243 | fixed | implemented | `verdict_scaling.RED_ENDURANCE_DURATION_SCALE` 0.70; monotonicity test |
| CI239-04 | Easing shortens the intervals, destroying the protocol | Med-High | 243, later 306 | fixed | claimed | Whole reps removed; 306 swaps VO₂ for Z2/tempo on a tired Amber |
| CI239-05 | Amber instruction is bike-only, emitted on strength/mobility/walk days | Medium | 243 | fixed | claimed | |
| CI239-06 | Perfect ERG execution can never earn an FTP increase | Medium | 252 | fixed | implemented | `block_progression`: `hit_rate >= 0.75`; but no FTP-raising path has run — DV-2/319 |
| CI239-07 | Strength invisible to load rules but counted as recovery spacer | Medium | 243, 252 | fixed | claimed | Strength is moderate load in `weekly_restructure`; coaching it is DV-10 (323) |
| CI239-08 | Nothing validates an imported plan against periodisation principles | Medium | 265 (not cited by ID) | fixed | claimed | Defer trigger fired (Mark felt week 9); 265 compares week types to `BLOCK_SEQUENCE` |
| CI239-09 | 13-week generator never produced a live plan; no overload | Low-Med | 323 | fixed | claimed | Plan No. 3 drafted 7 Oct with progressions; Mark decides from 12 Oct |
| CI239-10 | Two Zone-2 anchors coexist; endurance ceiling binds | Low-Med | 252 | fixed | claimed | 75% classifies, 67% prescribes |
| CI239-11 | A total data blackout returns Green | Low | 246 | fixed | implemented | `INSUFFICIENT_DATA_MESSAGE` floor; missing single fields still rate normal (DV-13 → 321) |
| CI239-12 | CI211-01 unresolved and growing | Low | 249 | fixed | implemented | `proposal-expiry` job registered |

### 1e. Batch 240 — health science (19)

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| HS240-01 | RHR 40 bpm above his ceiling still produces Green | High | 246, 293 | fixed | implemented | `morning_verdict.RESTING_HR_ABSOLUTE_DELTA_BPM = 7.0`, independent of readiness |
| HS240-02 | Acute one-night HRV collapse invisible to the verdict | High | 246, 294 | fixed | implemented | `HRV_ILLNESS_DROP_STDDEVS 2.5` / `FRACTION 0.30` floor; 1.5 SD now graded, not a cap |
| HS240-03 | SpO₂ and respiration collected, baselined, never evaluated | High | 246 | fixed | implemented | `AVERAGE_SPO2_ALERT_THRESHOLD_PCT`, nadir and respiration rules; surveillance only, never fired; respiration never grades (1 Oct MD-5) |
| HS240-04 | No medical boundary anywhere Mark reads | Med-High | 246, 301, 303 | fixed | implemented | `MEDICAL_BOUNDARY_STANDING_LINE` rendered by `AcutePhysiologyNotice`; symptom notices carry GP/111/999 |
| HS240-05 | Chronic REM deficit more likely device artefact than physiology | High | 250 | shipped differently | claimed | Test found pattern real, magnitude uncertain; caveat stated; disclosure to Mark undecided (Craig) |
| HS240-06 | Lever gate not defensible; the one issued lever fails the confound | High | 249 | fixed | implemented | `driver_levers`: calendar-adjusted effect plus interval gate; no lever currently passes |
| HS240-07 | Experiment loop reaches conclusions from noise | High | 249 | fixed | implemented | `experiment_evaluation`: per-arm minimum 4 → 7 nights; all four experiments now inconclusive |
| HS240-08 | Thermal thresholds arbitrary, at his median, below WHO indoor minimum | Med-High | none (unplaced) | open | implemented | Thresholds unchanged; `rem_interventions` grade note cites HS240-08 as unresolved |
| HS240-09 | Thermal exposure window is a clock window, not the sleep window | Medium | 268 (partly; not cited) | open | implemented | 268 fixed review/trend peaks (`night_thermal`); lever inputs still use `night_for_local` 21:30–09:00 window |
| HS240-10 | REM lever library mixes A-grade physiology with folk mechanisms | Medium | 250 | fixed | claimed | Each lever graded A–D; six mechanism claims rewritten |
| HS240-11 | `sleep_projection` names an ungated "measured driver" | Medium | 249 | fixed | implemented | `sleep_projection_context` applies the `driver_levers` gate |
| HS240-12 | Band classification one-sided; no rebound signal possible | Medium | 254 | shipped differently | implemented | Display bands fixed (`age_norms` far-side "neutral, worth noticing"); 6 Oct review: verdict grading still one-sided |
| HS240-13 | Outcome descriptors false for lower-is-better metrics | Medium | 254 | fixed | claimed | Directional descriptors; RHR 110 "Well above average" |
| HS240-14 | Ohayon denominator gap stage-dependent and larger than recorded | Medium | 250 | shipped differently | claimed | Rescaling rejected as self-cancelling; mismatch stated in `SLEEP_BAND_BASIS_NOTE` |
| HS240-15 | RHR/HRV rails self-recalibrate; trend detector is a step detector | Medium | 311 (via DV-7) | queued | claimed | Unplaced at roadmap; HRV now own baseline (295); "normal includes the week judged" queued |
| HS240-16 | VO₂ interval target probably below VO₂max intensity | Low-Med | 252 | fixed | claimed | Generated short VO₂ at 120–130% FTP, ERG off |
| HS240-17 | Age credit is a flat +4 on 83% of nights | Low | 295/300 (not cited) | superseded | claimed | 6 Oct review: superseded by the graded verdict's age-credit guard |
| HS240-18 | `workload_budget.py` is not a physiological workload budget | Low | none (accept) | accepted-and-closed | claimed | Scope correction |
| HS240-19 | SpO₂ survived the model swap; respiration and experiments did not | Low | 244 (folded into W3) | accepted-and-closed | claimed | Correction to the pre-audit note |

### 1f. Batch 241 — UX and live app (15)

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| UX241-01 | Brief lost four sections on model swap, including what to do | High | 244 | fixed | implemented | Same mechanism as AI238-01 (`requiredOutputSections`); 09-01 replay returned six headings |
| UX241-02 | `/brief` cannot tell failed from not-started; no retry | High | 248 | fixed | implemented | `BriefPendingCta` shared by Home and `/brief`; 302 added a graded morning before the prose |
| UX241-03 | A response the app cannot parse shows Mark raw JSON | High | none (unplaced) | open | implemented | Pages still render `query.error.message` (Sleep, Brief, Trends, Experiments, Holiday, Handover); no `ZodError` helper anywhere |
| UX241-04 | On `/brief` the verdict sits 3,080 px down a 3,809 px page | High | 244 | fixed | implemented | `TodaysCallHero` heads `MorningBriefPage`; written call section still last (DV-4 → 318) |
| UX241-05 | Coach holds 268 messages, shows 60, rest unreachable | Medium | 254 | fixed | claimed | "Load earlier messages" cursor; 276 of 276 reachable |
| UX241-06 | Coach thread is the one fetch with no schema guard | Medium | 253 | fixed | implemented | `coachThreadSchema.parse` in `CoachLauncher` |
| UX241-07 | Notification enable can fail silently; denied permission is a dead button | Medium | 253 | fixed | claimed | |
| UX241-08 | Home's sleep line leaks Garmin's raw grade, truncates mid-number | Medium | 253 | fixed | claimed | |
| UX241-09 | His own check-in words hidden behind a collapsed accordion | Medium | 253 | fixed | claimed | |
| UX241-10 | Nothing Mark reads says what the app cannot see | Medium | 246 | fixed | implemented | Standing line S1 (see HS240-04) |
| UX241-11 | Stale-brief detection is Home-only | Medium | 248 | fixed | claimed | `useDailyLoopFreshness` |
| UX241-12 | 25 hard-coded sub-14 px type sizes | Low | 254 | fixed | claimed | 27 found and moved to rem scale |
| UX241-13 | One control under the app's 44 px floor | Low | 254 | fixed | claimed | Verdict hero "Change" link |
| UX241-14 | Raw timestamp "Generated 01/09/2026, 09:25:19" | Low | 254 | fixed | claimed | "Written at 09:25 this morning" |
| UX241-15 | Cold time-to-content 4.9–11.7 s | Low | 254 | dropped | claimed | Premise measured false: payload 33.8 KB in production, not 275 KB; time-to-content not re-measured |


---

## 2. REM premise audit (`BATCH_250_REM_PREMISE.md`, 3 Sep) — 7 findings

No IDs or severities in the doc; IDs are `REM250-<n>` (results) and `REM250-O<n>` (its
"Open, and deliberately not closed here" list). Severity "unrated".

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| REM250-1 | REM pattern is architecturally real; magnitude probably under-counted (first REM at 239 min) | unrated | 250 | fixed | claimed | Limitation now stated in the packet; only the band footnote is rendered on screen |
| REM250-2 | Truncation does not explain low REM; protect-last-cycle mechanism confirmed | unrated | 250 | fixed | implemented | `protect_last_cycle` graded A in `rem_interventions` |
| REM250-3 | Rescaling bands to the measured-sleep denominator is self-cancelling; state, don't rescale | unrated | 250 | fixed | claimed | `age_norms.SLEEP_BAND_BASIS_NOTE`; same as HS240-14 |
| REM250-4 | Six lever mechanism claims untrue; weak and strong levers rotated blind | unrated | 250 | fixed | implemented | `evidence_grade`/`grade_note` per lever; strong-first rotation |
| REM250-O1 | Whether to tell Mark explicitly that the REM figure is uncertain | unrated | none | open | claimed | Craig's decision; still listed as open in STATUS (Batch 250 log), never recorded as taken |
| REM250-O2 | Organic differential missing: no "mention low REM to a GP once" (OSA, meds, PLMS) | unrated | none | open | implemented | No such copy anywhere in `apps/api/src`; needs Craig-signed clinical copy |
| REM250-O3 | External EEG validation of the latency signature not taken | unrated | none | deferred-with-trigger | claimed | Trigger (tests disagree) not fired; available if Craig wants it |

---

## 3. Review of Batches 268–275 (`2026-09-22-batches-268-275-review.md`) — 14 findings

No IDs in the doc; `R0922-<n>`: 1–4 are its numbered blocking findings, 5–6 its clinical read,
7–12 its per-batch notes, 13 its deadlines, 14 its "happening today" item. Blocking = High.

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| R0922-1 | 269.1 gated Red on the acute rail; should be 271's recalibration signal | High (blocking) | 269, 271 | fixed | implemented | `morning_verdict` uses `hrv_recalibration.is_band_artifact` (ladder path); graded verdict (295/296) now decides |
| R0922-2 | 269 needs overnight reading primary and the recalibration gate, not one | High (blocking) | 269 | superseded | claimed | Both shipped, then superseded by 295/296's own-baseline HRV |
| R0922-3 | 268.3's "count goes to zero" premise false; needs a positive fixture | High (blocking) | 268 | fixed | implemented | `test_night_thermal.test_the_one_genuinely_warm_night_still_counts` (21 Sep at 20.25) |
| R0922-4 | 275.1 comparator invalid: fixed 3.0 threshold, no variance, no polarity | High (blocking) | 275 | shipped differently | implemented | Per-metric threshold and direction added; Welch interval already existed; `GROUP_THRESHOLD` 3.0 remains the sleep default |
| R0922-5 | Record the 10–22 Sep HRV decline per day rather than silently discount it | unrated | 270 | fixed | claimed | 270 keeps a per-day classification |
| R0922-6 | 269.3's copy should lead with his best night, not the moved floor | unrated | 269 | fixed | claimed | Prompt leads with his numbers |
| R0922-7 | 268: keep projection; add the new call site to the SQL-recording test | unrated | 268 | fixed | claimed | Row carries it |
| R0922-8 | 271 must pin its phase (morning vs settled) | unrated | 271 | fixed | claimed | |
| R0922-9 | 272: ship cross-surface agreement only, not "structural plausibility" | unrated | 272 | fixed | claimed | Shipped as asked |
| R0922-10 | 273: provenance contract test needs a registry or it is vacuous | unrated | 273 | fixed | implemented | `provenance.PROVENANCED_FIGURES` |
| R0922-11 | 274: split; hold contest suppression until 273 has been seen | unrated | 274, 276 | fixed | claimed | Dissent record shipped; suppression held as parked 276 |
| R0922-12 | 270 needs its own branch before the systemic fallthrough; 275 rejects unbound hypotheses | unrated | 270, 275 | fixed | claimed | |
| R0922-13 | Deadlines: 268 before 27 Sep, 270 before 26 Sep | unrated | 268, 270 | fixed | claimed | Both shipped 22 Sep |
| R0922-14 | A pre-pushed VO₂ stays on Zwift after a Red; Red-never-VO₂ is delivery-time only | unrated | none | open | implemented | `regenerate_for_verdict`: pushed sessions "are never retracted"; Craig's call never recorded (STATUS gotcha) |


---

## 4. Verdict-grading review (`verdict-grading-review-2026-09-28.md`) — 20 findings

The doc's own IDs (CO/MD/AI/SE), prefixed `0928-` here because the 1 Oct review reuses them.
Its six changes became Batches 294–297 (Decisions #365–#368).

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| 0928-CO-1 | A mild concern on an easy day should change nothing | High | 296, amended 300 | fixed | implemented | `verdict_grading.session_actions` (move/hold/ease by session); 300 limits light-week holds to mild |
| 0928-CO-2 | Nothing measures under-training | High | 296.6 | fixed | implemented | Weekly review packet carries `keySessions` and cautious days by cause (`reviews.py`) |
| 0928-CO-3 | One bad night's sleep shouldn't be Red on its own | Medium | 295 | fixed | implemented | `sleep_score_marked_below` alone gives Amber |
| 0928-CO-4 | Recovery weeks need their own reading | Medium | 295, 296, amended 300 | fixed | implemented | Recovery-week HRV normal (`hrv_recovery_min_nights`); hold now mild-only |
| 0928-MD-1 | Floors are for harm, not performance | High | 294, 295 | fixed | implemented | Floors: symptoms, HRV illness grade, +7 RHR; everything else graded |
| 0928-MD-2 | The off-the-bike HRV alarm fires on noise (1.5 SD) | High | 294 | fixed | implemented | `HRV_ILLNESS_DROP_STDDEVS 2.5` / `0.30`; 1.5 SD is now a graded concern |
| 0928-MD-3 | Two-mornings resting-HR rule fires on noise | Medium | 295, 305 | fixed | implemented | Mild in `THRESHOLDS`; 305 dropped it as bike-rest corroborator (4 bpm kept) |
| 0928-MD-4 | Symptoms are the biggest safety gap | High | 294 (+301, 303, 315) | fixed | implemented | `symptom_check.SYMPTOM_FLOORS`; clinician check of wording declined by Craig (28 Sep) |
| 0928-MD-5 | A sudden HRV rise isn't always good news | Low | none | open | claimed | 6 Oct review: bands still one-sided; 1 night in 104 was +2 SD |
| 0928-MD-6 | Sleep stages are the least reliable watch measure | Low | 295 (partly) | open | claimed | Caveat reaches the brief, which still opens with stage percentages; 318 may reorder |
| 0928-AI-1 | Count agreement across independent domains | High | 295 | fixed | implemented | `DOMAIN_AUTONOMIC/SLEEP/LOAD/...`; readiness residual double count → 311 |
| 0928-AI-2 | Judge HRV against his own baseline, not Garmin's band | High | 295 | fixed | implemented | `hrv_baseline_window_days` 84, `hrv_swc_sd` 0.5 in `THRESHOLDS` |
| 0928-AI-3 | Claude's reading of the notes must be one-way | High | 297 | fixed | implemented | `notes_reader` "can only add caution", enforced in code |
| 0928-AI-4 | Notes reader needs a design and an eval before it ships | High | 297, 307 | fixed | implemented | Strict schema (`extra="forbid", strict=True`); `scripts/run_notes_eval.py`, pinned by 307 |
| 0928-AI-5 | A replay shows what changes, not whether it's better | Medium | 296 (proxies), 322 | queued | claimed | Outcome proxies in the replay; real outcome recording queued in 322 |
| 0928-SE-1 | Verdict pure, table-driven and property-tested | High | 295 | fixed | implemented | `verdict_grading.THRESHOLDS`; invariant tests in `test_batch_295_verdict_grading.py` |
| 0928-SE-2 | The replay harness should be a kept tool | High | 295 | fixed | implemented | `scripts/replay_verdicts.py` |
| 0928-SE-3 | Shadow for 14 mornings first, then switch | High | 296 | shipped differently | claimed | No shadow (Craig, 28 Sep); ladder runs beside graded 7–20 Oct with one-setting rollback |
| 0928-SE-4 | The colour has many consumers; keep one meaning | High | 296, 298, 299 | fixed | claimed | Weekly mix and rail moved to session actions in 299 after 1 Oct SE-2 |
| 0928-SE-5 | Storing flags and symptom answers is a schema change | Medium | 294, 297 | fixed | implemented | Migrations `033_manual_entry_symptoms` and `034_check_in_readings` |

---

## 5. Graded-verdict replay (`verdict-replay-2026-09-29.md`, Batch 295) — 10 findings

`VR0929-1…8` are its "calls to review before 296"; 9–10 its outcome notes. Unrated.

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| VR0929-1 | One low HRV night is mild, not marked; illness grade stays a floor | unrated | 296 | fixed | claimed | Adopted (Decision #367) |
| VR0929-2 | 7-day HRV mild under 0.5 SD, marked under 1.0 SD | unrated | 296, 304, 310 | fixed | claimed | Adopted; 304 adds persistence, 310 holiday catch-up; the normal itself → 311 (DV-7) |
| VR0929-3 | RHR mild at two mornings or +4, marked +5, floor +7 | unrated | 296, 305 | fixed | claimed | Adopted |
| VR0929-4 | Total sleep mild under ~6.4 h, marked under ~5.6 h | unrated | 296 | fixed | claimed | Adopted |
| VR0929-5 | Load ratio mild from 1.3; recovery time mild over 24 h; hard yesterday mild | unrated | 305, 316 | queued | claimed | 305 narrowed hard-yesterday; 1.3 → 1.5 and recovery-time-before-hard-only queued in 316 |
| VR0929-6 | Feel mild at ≤5, marked at ≤4, Rough is Red | unrated | 296 | fixed | claimed | Adopted |
| VR0929-7 | Readiness confirms at most one mild domain, never votes alone | unrated | 296, 305, 311 | queued | claimed | Kept by Craig 3 Oct as deliberate extra weight; candidates to change it in 311 (DV-6) |
| VR0929-8 | Recovery-class weeks hold the session on any concern | unrated | 296 | superseded | claimed | Batch 300: only a mild concern holds |
| VR0929-9 | Flagged mornings' hard sessions hit 58% of intervals vs 72% | unrated | none | superseded | claimed | Reproduced and extended in 6 Oct review C.1 |
| VR0929-10 | No dissents recorded yet | unrated | none | accepted-and-closed | claimed | Still 0 at the 4 Oct replay |


---

## 6. Notes-reader eval, v1 (`notes-reader-eval-2026-09-30.md`, Batch 297) — 4 findings

No IDs; `NR0930-<n>`. Unrated.

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| NR0930-1 | First Sonnet 5 run missed H04 and H43 ("since yesterday" read as past) | unrated | 297 | fixed | claimed | Prompt fixed before the recorded run; 12 of 12 red flags on both passes |
| NR0930-2 | Haiku 4.5 set no chest floor for H07 (only asked) | unrated | 297 | fixed | claimed | Sonnet 5 chosen as the reader model |
| NR0930-3 | Real-note false alarms sit at the gate limit (R29, R35) | unrated | none | accepted-and-closed | claimed | STATUS: "still no margin" |
| NR0930-4 | No held-out set: the two missed cases shaped the fix | unrated | 307 | fixed | claimed | Ten held-out cases (X01–X10) added and scored on 2 Oct |

---

## 7. Review of Batches 268–297 (`2026-10-01-batches-268-297-review.md`) — 31 findings

The doc's own IDs, prefixed `1001-`; plus `1001-MF4` (its "Must fix" item 4) and `1001-N1`
(a "Happening now" item). Batches 298–309 (G7) took R1–R5.

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| 1001-SE-1 | Colour and floors exist only if the paid brief succeeds | High | 302 | fixed | implemented | `MorningAnalysisService.grade_and_store` before `write_brief`; `gradedMorning` field |
| 1001-SE-2 | Weekly mix decides "eased" from the colour, not session actions | High | 299 | fixed | implemented | `weekly_mix` takes `session_actions` |
| 1001-SE-3 | Delivery rail proposes rides on rest days and skipped sessions | Medium | 299 | fixed | claimed | |
| 1001-SE-4 | Re-saving the check-in clears a symptom his note named | Medium | 303 | fixed | claimed | Only his answer to Home's question counts |
| 1001-SE-5 | "Rollback restores the ladder exactly" is no longer exact | Low | 308 | queued | claimed | Ladder deletion after the 7–20 Oct comparison |
| 1001-SE-6 | Chat sees a held day as plain Green | Low | 298 | fixed | claimed | |
| 1001-SE-7 | Knowledge base still states the ladder's Amber | Low | 298, 313 | fixed | claimed | 6 Oct observed `training_plan` v4 |
| 1001-SE-8 | `updated_at` stamped microseconds before `created_at` | Low | none | open | claimed | Cosmetic; not re-checked since |
| 1001-SE-9 | CI runs PostgreSQL 16; production runs 17.6 | Low | none | open | implemented | `ci.yml` starts the runner image's PostgreSQL 16 |
| 1001-AI-1 | Ladder's words ("caps today at Amber") ship beside the graded colour | High | 298 | fixed | implemented | `morning_verdict.graded_acute_physiology` swaps in `GRADED_MILD_SIGNAL_CLOSING` |
| 1001-AI-2 | Readiness confirmation counts sleep and recovery twice | Medium | 305, 311 | queued | claimed | Labelled in 305; kept by Craig 3 Oct; DV-6 candidates in 311 |
| 1001-AI-3 | Notes-reader eval in CI cannot catch a prompt or model change | Medium | 307 | fixed | claimed | Recording pinned to prompt version and SHA-256 |
| 1001-AI-4 | A stored reading outlives a prompt change | Low | 307 | fixed | claimed | Re-read when the reader's prompt version moves |
| 1001-AI-5 | 275's "supported" rests on three recovery weeks | Low | none | open | claimed | Now four light weeks |
| 1001-AI-6 | "Reproduces production" cannot catch a live acute-rail fault | Low | none | open | claimed | Replay reuses the stored rail by design |
| 1001-AI-7 | Batch 284's chat extractor has never run in production | Info | none | open | claimed | STATUS: first paid run waits for Mark's own tap |
| 1001-CO-1 | Light weeks hold a session even on a clearly-off morning | High | 300 | fixed | implemented | `verdict_grading.session_actions(..., clearly_off=...)` |
| 1001-CO-2 | A persistent HRV dip never escalates | Medium | 304 | fixed | claimed | `hrv_persistence_mornings` 3; 7 stored mornings change |
| 1001-CO-3 | Amber never shortens a ride | Medium | 306 | fixed | claimed | Shortened long ride offered, not applied |
| 1001-CO-4 | Graded Amber turns VO₂ into 94% threshold work at full length | Medium | 306 | fixed | claimed | Mark picks easy Z2 or tempo; picking neither leaves the plan |
| 1001-CO-5 | Planned training is called "a little off" | Low | 305 | fixed | claimed | Hard yesterday counts only before a hard session |
| 1001-CO-6 | ACWR 1.3 flags what Garmin calls optimal | Low | 305 (deferred), 316 | queued | claimed | Line held until after 20 Oct |
| 1001-CO-7 | The return on 7 Oct | Info | none | accepted-and-closed | claimed | Informational |
| 1001-MD-1 | The 999/111/GP advice depends on the model | High | 301 | fixed | implemented | `SymptomNotice` on `CheckInPage` from `lib/symptoms.ts` |
| 1001-MD-2 | No graded return after a fever | High | 303 | fixed | implemented | `symptom_check.illness_return`: two easy mornings, shorter than IOC graded return |
| 1001-MD-3 | Breathlessness is missing | Medium | 303 | fixed | claimed | Chest answer and reader flag include it; v2 eval 22/22 |
| 1001-MD-4 | An unclear chest mention only asks | Medium | 303 | fixed | claimed | Eases a hard session until answered |
| 1001-MD-5 | Respiration rate never grades | Low | none | open | claimed | Surveillance only; 6 Oct: it restates HRV (r −0.61) |
| 1001-MD-6 | Noisy two-mornings RHR rule still corroborates bike rest | Low | 305 | fixed | claimed | Replaced by a 4 bpm corroboration (adds a day once in his history, 1 Aug) |
| 1001-MF4 | Don't send the 27 Sep reply: six claims no longer true | unrated | none | accepted-and-closed | claimed | Craig, 1 Oct: no message to Mark |
| 1001-N1 | Database at 453 MB of the 500 MB cap, alert firing for days | unrated | 325 | fixed | claimed | VACUUM FULL 7 Oct → 171 MB |


---

## 8. Notes-reader eval, v2 (`notes-reader-eval-2026-10-02.md`, Batch 303) — 4 findings

No IDs; `NR1002-<n>`. Unrated.

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| NR1002-1 | B03 ("woke gasping") set the chest floor on one pass, only asked on the other | unrated | 303 | accepted-and-closed | claimed | Since 303 the question also eases a hard session until answered |
| NR1002-2 | Held-out X07 (stitch on a walk) raised a chest question on one pass | unrated | none | accepted-and-closed | claimed | Prompt deliberately not fitted; one tap of None clears it |
| NR1002-3 | Real-note false alarms R29/R35 unchanged from v1; no margin | unrated | none | accepted-and-closed | claimed | Same as NR0930-3 |
| NR1002-4 | Haiku 4.5 not re-run under the v2 prompt | unrated | none | accepted-and-closed | claimed | Not the production model |

---

## 9. Graded-verdict replay (`verdict-replay-2026-10-04.md`, Batch 310) — 5 findings

A batch acceptance report; `VR1004-<n>`. Unrated.

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| VR1004-1 | 310's holiday catch-up changes exactly 21 and 22 Jul | unrated | 310 | fixed | claimed | Acceptance met; Red 8 → 7 |
| VR1004-2 | `hrv_week_marked_sd` first fired 4 Oct, on his holiday's low week | unrated | 310, 311 | queued | claimed | 310 shipped the catch-up; "normal includes the week it judges" is DV-7 → 311 |
| VR1004-3 | ACWR 1.3 mild line to move to 1.5 only after 20 Oct | unrated | 316 | queued | claimed | |
| VR1004-4 | Graded Red rate 7% (7 of 105); replay reproduces 4 of 4 | unrated | none | accepted-and-closed | claimed | Under the one-in-ten warning line |
| VR1004-5 | Flagged-morning hard sessions on target 58% vs 72% | unrated | none | superseded | claimed | Extended in 6 Oct review C.1; better recording in 322 |

---

## 10. Rest-day replay (`verdict-replay-2026-10-05-rest-days.md`, Batch 313) — 2 findings

`VR1005-<n>`. Unrated.

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| VR1005-1 | 16 planless plan-week mornings become rest days; no colour moves | unrated | 313 | fixed | claimed | Acceptance met (rest days 11 → 27; 0 colours changed) |
| VR1005-2 | Replay reproduces 5 of 5 graded mornings; Red 7% | unrated | none | accepted-and-closed | claimed | |

---

## 11. Daily-verdict review (`2026-10-06-daily-verdict-review.md`) — 16 findings

The doc's own IDs (DV-1…16). G8 took them as Batches 314–323 (mapping from the review's
section E and the ledger's G8 preamble).

| ID | One-line finding | Severity | Where it went | Status | Evidence | Note |
|---|---|---|---|---|---|---|
| DV-1 | Nothing planned after Sun 18 Oct, and nothing tells Mark | High | 323, 324 | fixed | implemented | `block_generator.next_plan_draft`; Home `NextPlanCard` from 12 Oct; empty from 19 Oct if he declines |
| DV-2 | Nothing measures or prompts progress; engine can only hold or reduce | High | 319 (+323's week-1 ramp test) | queued | claimed | 319 waits for Plan No. 3 to be loaded |
| DV-3 | Morning after a chest or heart report is ordinary, VO₂ included | High | 315 | fixed | implemented | `symptom_check.chest_follow_up`, `answer_chest_follow_up` route, migration 036 |
| DV-4 | Home says what but not why; the brief says why, last | Medium | 317, 318 | queued | claimed | |
| DV-5 | Two "usual" HRVs in one brief; a fair night called "clearly off" | Medium | 317 | queued | claimed | |
| DV-6 | Readiness confirmation decides 7 of 106 colours, 3 of 7 Reds | Medium | 311 | queued | claimed | |
| DV-7 | His normal includes the week it judges; a low holiday week lowers it 12 weeks | Medium | 311 | queued | claimed | Also carries HS240-15 |
| DV-8 | Load domain least informative; its 1.3 line flags Garmin's "optimal" | Medium | 316 | queued | claimed | |
| DV-9 | Nothing checks the brief against the call or packet; no brief eval | Medium | 318 | queued | claimed | Also carries AI238-02 |
| DV-10 | Strength is protected but never coached | Medium | 323 | fixed | claimed | Plan No. 3 draft: two loaded, progressing strength sessions a week; only if Mark accepts |
| DV-11 | Recovery advice is generic and its effect never measured | Medium | 320 | queued | claimed | |
| DV-12 | Withholding a swap on an off-the-bike day has no test | Low | 321.1 | queued | claimed | May land any time |
| DV-13 | A missing HRV reading or sleep score counts as normal | Low | 321.2 | queued | claimed | |
| DV-14 | Three call lines say more than the engine knows | Low | 321.3 | queued | claimed | Row names two lines (head cold, missing row) |
| DV-15 | ARCHITECTURE §4 no longer works as a model | Low | 308 | queued | claimed | 308.1 amended in place |
| DV-16 | Cost and size are fine | Low | none | accepted-and-closed | claimed | No action |

