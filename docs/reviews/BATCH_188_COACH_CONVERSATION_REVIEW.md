# Batch 188 — Coach-conversation & prompt-policy integrity review

**Date:** 2026-08-05
**Branch:** `chore/batch-188-coach-conversation-review`
**Mode:** diagnose-only — this batch changes documentation, not product code, prompt
text, prompt versions, verdict logic or floors
**Scope:** full-app across the *prompt and coach-speech surface*: every
`PROMPT_VERSION` constant in `apps/api/src/services/`, `services/coach_policy.py`,
`services/brief_chat.py`, `services/chat_context.py`,
`services/state_change_coach.py`, `routers/coach_chat.py`, the eight deterministic
read prompts, and `tests/test_brief_chat_prompt_policy.py`.
**Base:** `main` @ `886bf56` (Batch 187 closed out)

---

## Executive summary

The **hard safety boundary holds.** Nothing in the spoken layer can move the
deterministic Green/Amber/Red ladder, apply a plan change, or bypass Decision
#29's propose→approve→push gate. The propose affordance is a server-side
deterministic decision over live plan rows; the model never triggers it. The
state-change coach writes only an `Analysis` audit row and a `BriefMessage` — it
has no code path to a verdict or a `PlannedWorkout`. Batch 181's observed-data
humility is correctly bounded in every prompt that states it ("This applies to
observed data only: never let a correction change a deterministic verdict, safety
floor, or propose/confirm decision"), and `ANTI_SYCOPHANCY_RULE` resolves the
collision the batch plan flagged as the sharpest candidate contradiction. That
specific contradiction is **not** present.

**The lead question is answered, and the answer inverts the hypothesis.**
`state_change_coach.py` is *not* the least-covered prompt surface, because it is
not a prompt surface at all: it makes no model call, has no system prompt, and
emits four hand-written message templates (`model_name=None`, `raw_response={}`).
Its `PROMPT_VERSION` names a template revision, not a prompt. It therefore cannot
hallucinate, and being outside `READ_PROMPT_FLOORS` is *correct* — but undocumented,
and its detection layer has no test coverage at all. The genuinely uncovered **LLM**
surface is `conversation_learning.py`: the only Anthropic-calling module with no
version constant, outside the floors audit, and the only one whose output enters
the coach's persistent memory and re-enters every user-facing prompt from there.

Where the discipline is thinner than the deterministic layer:

1. the **unprompted-speech budget is spent first-come, not best-first** — a
   low-value weekly-mix heads-up on Monday silences a chronic deload transition
   until the following Monday;
2. the state-change coach **recomputes** its "current" state with different inputs
   from the morning brief Mark actually read that day, and compares it against
   *yesterday's* stored packet, so "Something changed" can contradict this
   morning's read;
3. the floors audit matches **topic adjacency, not the rule** — an inverted
   "on a Red day VO2 is fine" passes `missing_floors` unchanged (verified by
   execution), and one registered floor (`local_clock_times`) is audited against
   zero prompts and matched by none of the eight;
4. the audit is **closed-world**: a newly added user-facing prompt is never forced
   into the registry, so the guard only catches removal, never omission;
5. every read packet embeds a **verbatim copy of its own system prompt**, which
   doubles the morning call's system text and is re-injected unbudgeted into every
   anchored chat turn as "Mark's information behind that read";
6. `sinceThisRead` reports **pre-read** workout closures as changes since the read.

Counts: **2 High, 8 Medium, 7 Low.** Identifiers are review-local placeholders,
not allocated ledger batch numbers.

---

## 188.1 — The prompt surface, mapped, with an in/out disposition

There are **17** version constants (16 named `PROMPT_VERSION`, plus
`wake_detection.WAKE_CHECK_PROMPT_VERSION`). Only **9** of them belong to an actual
model prompt. The distinction is the finding: *"prompt version" has been used as a
generic "regenerate when this changes" token*, which is why the surface looked
larger and less audited than it is.

Ten modules call Anthropic (`generate_anthropic_text` directly, or
`AnthropicReviewClient`): `morning_analysis`, `post_workout_analysis`,
`post_walk_analysis`, `post_strength_analysis`, `post_flexibility_analysis`,
`reviews`, `trends`, `handover`, `brief_chat`, `conversation_learning`. Every other
service listed below emits deterministic templates.

| # | Surface | Version constant | Model call? | Speaks to Mark? | Floors audit | Disposition |
|---|---|---|---|---|---|---|
| 1 | `morning_analysis` | `morning-analysis-v27-2026-08-04` | yes | yes | **in** (4 floors) | correct |
| 2 | `post_workout_analysis` | `post-workout-analysis-v15-2026-08-02` | yes | yes | **in** (2) | correct |
| 3 | `post_walk_analysis` | `post-walk-analysis-v5-2026-08-02` | yes | yes | **in** (1) | correct |
| 4 | `post_strength_analysis` | `post-strength-analysis-v5-2026-08-02` | yes | yes | **in** (1) | correct |
| 5 | `post_flexibility_analysis` | `post-flexibility-analysis-v5-2026-08-02` | yes | yes | **in** (1) | correct |
| 6 | `reviews` | `reviews-v7-2026-08-05` | yes | yes | **in** (1) | correct |
| 7 | `trends` | `PROMPT_VERSION_BY_BUCKET` | yes | yes | **in** (1) | correct |
| 8 | `handover` | `handover-v2-2026-08-02` | yes | yes | **in** (1) | correct |
| 9 | `brief_chat` | `coach-chat-v7-2026-08-02` | yes | yes | **composed** from `coach_policy` | correct |
| 10 | `conversation_learning` | **none** | yes | no (proposes memory) | **out** | **gap — CC188-14** |
| 11 | `state_change_coach` | `state-change-coach:v1-2026-08-05` | **no** | **yes, unprompted** | out | correct but undocumented — CC188-18 |
| 12 | `nudge_alerts` | `notification-rules:v3` | no | **yes** (push bodies, 20:00 nudge) | out | correct but undocumented — CC188-18 |
| 13 | `insights` | `insights:v2-2026-08-02` | no | via other packets | out | correct |
| 14 | `weekly_restructure` | `weekly-restructure:v1` | no | preview copy | out | correct |
| 15 | `executable_coaching` | `executable-coaching:v1` | no | delivery copy | out | correct |
| 16 | `experiment_tracker` | `experiment-tracker:v1` | no | experiment copy | out | correct |
| 17 | `experiment_evaluation` | `experiment-eval:v1` | no | via state-change turns | out | correct |
| 18 | `wake_detection` | `wake-check-v1-2026-06-24` | no | no | out | correct |

**Verified clean:** a scan of every string literal in the eight deterministic
modules for `coach_policy.INTERNAL_VOCABULARY` returns no hit in
`state_change_coach` (2,090 literal chars) or `nudge_alerts` (10,212) — the two
that put deterministic text directly in front of Mark. Hits in `insights`,
`weekly_restructure`, `executable_coaching`, `experiment_evaluation` and
`wake_detection` are confined to docstrings and comments, not user-facing copy.
No automated guard enforces this; it is true today by care, not by test.

**Second, undeclared floor registry.** `morning_analysis.py:596-632` stores a
`prompt.outputRules` list of rule keys inside the packet —
`never_recommend_vo2_on_red`, `never_reference_left_right_power_balance`,
`state_local_clock_times_never_utc`, `never_treat_skipped_workout_as_live_training`
and 17 more. It overlaps `coach_policy.FLOORS` but is neither derived from it nor
cross-checked against it, and it is the *only* place `state_local_clock_times_never_utc`
is named as a rule (see CC188-07).

---

## 188.2 — Coherence across the accumulated floors

### What holds

**The flagged contradiction is not real.** Batch 181's "his own-device reading wins
on observed data" is bounded in the floor itself
(`coach_policy.py:102-114`: "…while keeping every deterministic verdict, safety
floor, and propose/confirm decision intact"), restated identically in all eight read
prompts ("This applies to observed data only…" —
`morning_analysis.py:155-160`, `post_workout_analysis.py:110-115`,
`post_walk_analysis.py:75-80`, `post_strength_analysis.py:93-98`,
`post_flexibility_analysis.py:73-78`, `trends.py:98-102`, `handover.py:103-108`),
and explicitly disambiguated for the conversation by
`ANTI_SYCOPHANCY_RULE` (`coach_policy.py:197-202`): *"Deferring to what his own
device displayed is observed-data honesty, not licence to defer to him on coaching
judgement."* When both rules bite at once the resolving code path is the read
prompt's "observed data only" clause plus the fact that the verdict is computed
before the model is called and passed in as `verdict.status` — the model has no
channel through which to change it.

`GROUNDING_RULE` and `GENERAL_SCIENCE_RULE` are scoped disjointly (about Mark vs
general physiology, the latter mandatorily labelled `General principle:`) and do
not collide. Batch 165's capability wording, Batch 173.3's "quote the app's own
adjustment figures", and Batch 178's not-known sentence all survive intact in
`coach-chat-v7` and are covered by the policy test.

### What does not hold

1. **The chat is told two different things about its own epistemic status.**
   `chat_context._state_meaning` (`chat_context.py:648-658`) writes *"where the two
   differ, this block is the current truth"*, and `_trends`
   (`chat_context.py:371-375`) writes *"a direction stated here is evidence, not a
   guess."* Both are in the same prompt as the Batch 181 floor asserting that every
   app figure is "what the app recorded, not… independently verified truth about
   Mark", and as `brief_chat.SYSTEM_PROMPT:130-132`, which is careful to say
   *"Neither record proves what Mark's body or own device actually showed."*
   → **CC188-06**.
2. **The floor patterns detect topic, not rule** → **CC188-04**.
3. **`local_clock_times` is a floor no read prompt is audited for, and none matches**
   → **CC188-07**.
4. **The audit is closed-world** → **CC188-05**.
5. **`PROPOSE_CONFIRM_RULE` and `_capability_instruction(None)` give opposite
   instructions on a rest/holiday/closed-out day** — one says keep an adjustment
   request "in the existing propose/confirm path", the other says "Do not say the
   app can propose, confirm, upload, or change a workout from this conversation"
   (`coach_policy.py:190-195` vs `brief_chat.py:280-284`). Both are always present.
   The resolution is left to the model. → **CC188-12**.

---

## 188.3 — Ask-time context assembly (`services/chat_context.py`, 769 lines)

### Verified as claimed

- **The `_DROP_ORDER` trim genuinely names its whole-section drops.**
  `_apply_char_budget` (`chat_context.py:620-645`) appends each dropped section to
  `omittedForLength` and attaches `omittedForLengthMeaning` ("Trimmed to fit the
  prompt, not absent from the app"), matched by the prompt's own instruction
  (`coach_policy.py:172-173`: "If something says it was trimmed for length, that
  means you cannot see it right now, not that the app does not hold it"). A
  genuinely-empty section is skipped (`if not state.get(section): continue`) rather
  than mislabelled as trimmed. `weekAhead`, `today` and `sinceThisRead` are never
  dropped; the trend series is trimmed oldest-first, never below one window, and
  the trim is named. Covered by three pure tests
  (`test_chat_context.py:79-134`).
- **`_packet_check_in_versions` matches the real packet shapes.** The morning packet
  writes `manualEntries` (`morning_analysis.py:566`) and the four post-session
  packets write `postRideCheckIn` / `activityCheckIn`
  (`post_workout_analysis.py:493`, `post_strength_analysis.py:304`,
  `post_walk_analysis.py:315`, `post_flexibility_analysis.py:403`), all at packet top
  level, so the one-level scan is sufficient today, and
  `analysis_currentness.manual_entry_input_version` produces exactly the
  `entryAtUtc` string format compared against.
- **`adjustable_workout_id` gates the affordance correctly.**
  `_adjustable_workout_id` (`chat_context.py:265-298`) requires an active plan row
  dated today, status not in `{completed, skipped}`, a `structured_workout`, a bike
  `workout_type`, and no covering holiday window — the holiday check queried from
  `HolidayPauseService` rather than inferred from statuses, which is right because
  `holiday_pause` writes `status="skipped"` but a stale un-re-versioned row would not
  carry it. Four DB tests cover the live/closed/holiday/rest cases
  (`test_chat_context.py:433-564`).
- **The origin vocabulary is closed and non-interpolating.** `normalize_origin_kind`
  (`chat_context.py:139-143`) degrades any unknown value to `general`, and only
  `ORIGIN_KINDS[...]` prose ever reaches the prompt — client text never does
  (`routers/coach_chat.py:64-66`, tested at
  `test_brief_chat_prompt_policy.py:244-250`).

### Defects

- `subjectDateWorkoutsClosedSinceRead` is computed from **current status only**, with
  no comparison to the read's own generation time → **CC188-03**.
- The activities delta is anchored on `Activity.start_utc`, not on when the app
  learned of the activity → **CC188-13**.
- Field-level truncations (`REVIEW_CONCLUSION_MAX_CHARS = 900`, the 200-char plan-change
  summary) are silent — they add an ellipsis but never appear in `omittedForLength`
  → **CC188-15**.
- `APP_STATE_CHAR_BUDGET` is a soft cap; the trim can terminate over budget →
  **CC188-16**.
- The budget governs only `appState`. The stored packet, which is the larger input
  and contains a verbatim copy of the read's system prompt, is serialized whole and
  unbudgeted (`brief_chat.py:493-496`, `501-502`) → **CC188-09**.

---

## 188.4 — Unprompted speech (`services/state_change_coach.py`, 513 lines)

### Verified as claimed

- **Batch 182's qualification and plan-suppression are inherited in code.**
  `_chronic_snapshot` (`state_change_coach.py:115-117`) returns `None` when
  `triggered is not True` **or** `suppressedByPlan is True`, so a Red cluster that
  Batch 182 declined to qualify, and a signal covered by a scheduled
  recovery/taper/consolidation block, produce no message. Unit-tested
  (`test_state_change_coach.py:65-76`).
- **Ranking is chronic > experiment > mix, deterministically.** `_RANK`
  (`:33-37`) plus a stable `state_key` tiebreak in `choose_ranked_candidate`
  (`:76-84`). Unit-tested (`test_state_change_coach.py:55-63`).
- **A standing state is not a transition.** `transition_candidate` (`:65-73`)
  returns `None` on an unchanged `state_value`. Unit-tested (`:44-52`).
- **Experiments never auto-conclude**: the template says so explicitly (`:198-202`)
  and the service writes no `Experiment` row.
- **No structural path to a verdict or a plan mutation.** The service's only writes
  are one `Analysis` and one `BriefMessage` (`:278-303`). `ANALYSIS_TYPE_STATE_CHANGE`
  is not in `training_week.ACTION_AUDIT_TYPES` and not in `chat_context._READ_TYPES`,
  so the audit row cannot masquerade as a plan change or supersede a read.
- **The messages are clean of internal vocabulary** (scanned; no hits).

### Defects

- The 7-day budget is checked **before** candidates are computed, so it is spent
  first-come rather than best-first → **CC188-01**.
- "Current" state is a fresh recomputation with **different parameters** from the
  morning packet, compared against **yesterday's** packet → **CC188-02**.
- An absent previous morning read turns a standing state into "Something changed"
  → **CC188-08**.
- No holiday guard, unlike the weekly-review job → **CC188-10**.
- `verdictImpact` / `planMutation` are packet string literals, asserted by test as
  literals, with no enforcement → **CC188-11**.
- `_existing_analysis` / `_message_for_analysis` (`:466-513`) are unreachable →
  **CC188-17**.
- A suppressed lower-ranked transition is lost permanently, not deferred →
  **CC188-19**.
- The real detection layer has **no test coverage**: the one DB test subclasses the
  service and replaces `_candidates` wholesale (`test_state_change_coach.py:79-91`),
  so `_current_chronic`, `_current_weekly_mix`, `_experiment_candidates`,
  `_previous_morning` and the packet parsers are never executed under test →
  **CC188-20**.

---

## Ranked findings

### CC188-01 — High — the unprompted-speech budget is spent first-come, so a trivial message silences a deload transition for up to six days

**Evidence**

- `StateChangeCoachService.run` checks the budget *before* computing candidates and
  returns immediately (`apps/api/src/services/state_change_coach.py:228-234`).
- `_budget_spent` returns true if **any** `state_change_coach` analysis row exists
  with `subject_date` in `[as_of - 6, as_of]`, regardless of its kind
  (`:452-464`).
- `_RANK` and `choose_ranked_candidate` (`:33-37`, `:76-84`) order candidates only
  *within a single run*; there is no comparison against what was already spent.
- The job fires daily at 11:45 (`scheduler.py:1464-1473`).

**Failure scenario**

Monday: the endurance bucket goes at risk; no other transition. The coach spends
the week's single turn on *"Endurance has gone at risk this week (2 still due, 1
still scheduled)"*. Tuesday: sustained recovery-marker misses cross Batch 182's
threshold and `chronicAction.triggered` flips to true — the highest-ranked
transition the system knows how to notice. `run` returns `budget_spent` before
`_candidates` is ever called. Wednesday through Sunday the same. By the following
Monday, `_previous_morning` is Sunday's packet, which already records the triggered
chronic action, so `transition_candidate` sees no change and the deload transition
is **never** announced.

**Remediation stub** — evaluate candidates first, then apply the budget as a
*ranked* spend: allow a strictly higher-ranked transition to pre-empt a
lower-ranked one already sent inside the window (at most one pre-emption per
window), or scope the budget per `TransitionKind` with a tighter global ceiling.
Requires the budget query to read the stored `transitionKind` from the packet.

---

### CC188-02 — High — the coach announces a state it recomputes with different inputs from the brief Mark read that morning

**Evidence**

- Morning packet: chronic action is computed **with** the day's not-yet-persisted
  verdict and the sleep protocol —
  `ChronicPatternSuggestionService.suggestions(..., sleep_protocol=knowledge_base["sleep_protocol"], current_verdict=verdict["status"])`
  (`morning_analysis.py:449-456`).
- State-change coach: the same service is called **without** either, and with a
  different `sleep_drivers` argument
  (`state_change_coach.py:346-353`). `current_verdict=None` means
  `recent_verdicts` falls back entirely to stored rows
  (`chronic_patterns.py:545-548`).
- Morning packet: weekly mix is computed with the **real** verdict status and the
  rest-day guard (`morning_analysis.py:506-513`).
- State-change coach: weekly mix is computed with a hardcoded
  `verdict_status="Green"` and no rest-day guard
  (`state_change_coach.py:355-364`). `verdict_status` is the only channel by which
  today's easing enters the accounting (`weekly_mix.py:369-390`,
  `:196-231`), so the two computations can disagree by construction.
- The comparison baseline is **yesterday's** morning packet, never today's
  (`state_change_coach.py:408-421`), even though the job runs at 11:45 and the
  morning backstop guarantees today's read by 11:00 (`scheduler.py:1403-1418`).

**Failure scenario**

An Amber morning eases today's threshold session. The morning brief Mark reads at
07:00 carries `weeklyMix` computed with `verdict_status="Amber"`, so the threshold
bucket is `atRisk: true` and the brief says so with its shortfall/re-patch wording.
At 11:45 the state-change coach recomputes the same week with
`verdict_status="Green"`: the eased session is *not* removed from
`remaining_planned`, the bucket is not at risk, and no message is produced —
harmless. Reverse the days and it is not: yesterday was Green (bucket not at risk
in the stored packet), today the deterministic Amber morning has already told Mark
the bucket is at risk *and offered the swap*, while the coach's Green-forced
recomputation independently decides the bucket "has quietly gone at risk" and posts
*"I have not moved anything; this is a heads-up while there is still time to choose
a fix"* — contradicting the brief that already moved it. The chronic lane has the
same shape: today's brief can say nothing about a deload while the coach's
differently-parameterised recomputation announces one.

**Remediation stub** — read *today's* stored morning packet as the "current"
snapshot rather than recomputing, exactly as the "previous" side already does. That
makes the announced state identical to the one Mark was given, deletes both
parameter asymmetries, and removes three service calls per profile per day. Fall
back to recomputation only when today's morning read does not exist, and mark such
a message as provisional.

---

### CC188-03 — Medium — `sinceThisRead` reports workouts closed *before* the read as changes since it

**Evidence**

`_since_read` builds `subjectDateWorkoutsClosedSinceRead` by filtering the subject
date's planned workouts on **current status alone**, with no timestamp comparison
against `read_generated_at` (`chat_context.py:328-337`). That list also feeds
`anythingChangedSinceRead` (`:338-345`).

**Failure scenario**

Mark rides at 07:00; the ride is marked completed; the post-workout read is
generated at 12:00; he opens the chat on that read at 12:05. The block reports
`anythingChangedSinceRead: true` and lists the very ride the read is about under
`subjectDateWorkoutsClosedSinceRead`. The prompt tells the model this block is "the
current truth" against the read's "earlier record", so the coach can open with
*"since I wrote that, you've completed your session"* — describing the session the
read analysed. The same happens on any morning read regenerated after the ride
(check-in-first regeneration is a routine path).

**Remediation stub** — either compare a closure timestamp against
`read_generated_at`, or rename the field to what it actually is
(`subjectDateWorkoutsClosed`) and drop it from the `anythingChangedSinceRead`
disjunction. `PlannedWorkout` has no status-change timestamp today, so the rename is
the honest minimum; adding one is a migration.

---

### CC188-04 — Medium — the floor audit matches topic adjacency, not the rule, so an inverted rule passes

**Evidence** (verified by execution against the live registry)

- `never_vo2_on_red` matches `r"vo2[^.]{0,60}red|red[^.]{0,60}vo2"`
  (`coach_policy.py:82-85`). `missing_floors("On a Red day, VO2 intervals are
  absolutely fine.", ("never_vo2_on_red",))` returns `()` — the audit passes an
  exactly inverted rule.
- `no_skipped_as_live` matches the bare token `r"skipped"` (`:96-100`).
  `missing_floors("Do not say skipped.", ("no_skipped_as_live",))` returns `()`.
- Only `recorded_data_honesty` uses a multi-clause ordered pattern (`:110-113`) that
  actually constrains meaning.

**Failure scenario**

A future prompt edit reverses or weakens the Red/VO2 prohibition while leaving the
two words in the same sentence — say, "VO2 work is only off the table on a Red day
when HRV is also suppressed". `test_every_user_facing_read_prompt_states_the_floors_it_owns`
(`tests/test_brief_chat_prompt_policy.py:169-190`) stays green, and the change
reaches Mark. This is the single most safety-critical floor in the system.

**Remediation stub** — strengthen the two weak patterns to require the prohibition
(`never|do not|don't|no ` within the same clause as the subject), and add a negative
control per floor to the policy test: an inverted sentence must be reported as
missing. `missing_floors` already proves it "is capable of failing" for an empty
string (`:190`) — extend that to the inverted case.

---

### CC188-05 — Medium — the floors audit is closed-world: a new user-facing prompt is never forced into it

**Evidence**

`test_every_user_facing_read_prompt_states_the_floors_it_owns` asserts
`prompts.keys() == READ_PROMPT_FLOORS.keys()` over a **hand-written literal dict**
(`tests/test_brief_chat_prompt_policy.py:176-186`). `READ_PROMPT_FLOORS`
(`coach_policy.py:120-134`) is likewise hand-maintained. Nothing enumerates the
modules that call Anthropic, so a new one is simply absent from both sides and the
equality still holds.

**Failure scenario**

A future batch adds a user-facing read (the pattern has repeated five times: walk,
strength, flexibility, reviews, trends). Its author does not add it to
`READ_PROMPT_FLOORS`. The whole suite stays green, and a CheckMark surface ships
with no floor coverage at all. `conversation_learning` (CC188-14) is the existing
instance of exactly this.

**Remediation stub** — discover the surfaces instead of listing them: enumerate
`src.services.*` modules that reference `generate_anthropic_text` or
`AnthropicReviewClient`, and fail if any module exposing a user-facing `SYSTEM_PROMPT`
is absent from `READ_PROMPT_FLOORS` (with an explicit, commented opt-out list for
`conversation_learning` and any other non-user-facing prompt).

---

### CC188-06 — Medium — the app-state block asserts "current truth" and "evidence", contradicting the Batch 181 floor in the same prompt

**Evidence**

- `_state_meaning`: *"where the two differ, this block is the current truth"*
  (`chat_context.py:648-654`).
- `_trends`: *"Real measured series — a direction stated here is evidence, not a
  guess."* (`chat_context.py:371-375`).
- The floor in the same prompt: *"treat every app figure as what the app recorded,
  not as independently verified truth about Mark"* (`coach_policy.py:102-114`).
- `brief_chat.SYSTEM_PROMPT` gets this right and is careful about it:
  *"the current state is the app's latest record and the read is the app's earlier
  record… Neither record proves what Mark's body or own device actually showed"*
  (`brief_chat.py:129-132`) — which is precisely the sentence the two `chat_context`
  strings undercut.

**Failure scenario**

Mark says his watch showed HRV 46 last night; the app recorded 38. Batch 181's whole
point is that the coach acknowledges the discrepancy and treats it as a data-quality
problem. The app-state block simultaneously tells the model its own figure is "the
current truth", giving the model a licence — inside the same prompt — to defend the
recorded number as truth rather than as a record. Which instruction wins is
undetermined and untested.

**Remediation stub** — restate both strings in the record vocabulary the chat prompt
already uses ("the app's latest record", "measured and stored by the app"), and add a
policy test asserting that no string `chat_context` puts in the prompt claims
independent truth. Prompt-version bump required; this is a remediation batch, not a
review edit.

---

### CC188-07 — Medium — `local_clock_times` is a registered floor audited against zero prompts, and matched by none of the eight

**Evidence** (verified by execution)

- `local_clock_times` appears in `FLOORS` (`coach_policy.py:91-95`) and therefore in
  `floors_sentence()`, which the conversation states to the model verbatim.
- It appears in **no** entry of `READ_PROMPT_FLOORS` (`:120-134`) — the only floor with
  zero coverage.
- Running `missing_floors(prompt, all_floor_keys)` over all eight read prompts:
  `local_clock_times` is reported missing from **all eight**.
- The morning read *does* enforce local times — via wording the pattern cannot see:
  *"sleep.sleepStartLocal, sleep.sleepEndLocal, which are already the user's local
  clock time"* (`morning_analysis.py:145-148`); the pattern requires `local time`,
  `local timezone` or `never utc` (`coach_policy.py:94`) and "local clock time" matches
  none of them. The rule is separately named in the packet's parallel registry as
  `state_local_clock_times_never_utc` (`morning_analysis.py:614`).

**Failure scenario**

Two failure modes, both live. (a) The chat promises Mark a floor — "state any clock
times in Mark's local timezone (never UTC)" — that no read is audited for, so it can
silently regress in the morning brief, which is exactly where Mark reported it
(2026-07-12, Batch 91). (b) Anyone adding `local_clock_times` to `READ_PROMPT_FLOORS`
to close (a) will see all eight surfaces fail despite correct behaviour, and is
likely to conclude the floor is wrong rather than the pattern.

**Remediation stub** — widen the pattern to `local (clock )?time|local timezone|never utc`,
then add `local_clock_times` to the morning, post-workout and post-session entries and
confirm green. Derive `prompt.outputRules` from `coach_policy` keys, or drop it, so the
two registries cannot diverge again.

---

### CC188-08 — Medium — an absent previous morning read turns a standing state into "Something changed"

**Evidence**

`_candidates` falls back to `previous_packet = {}` when there is no prior morning
`Analysis` or its packet is not a dict (`state_change_coach.py:316-322`). Every
`previous_value` is then `None`, and `transition_candidate` treats
`None != current.state_value` as a transition (`:65-73`). `_previous_morning` accepts
*any* morning read with `subject_date < as_of` (`:408-421`), so this bites whenever
the most recent one is missing entirely rather than merely old.

**Failure scenario**

Mark returns from a holiday during which no morning reads were generated. On the
first day back, `previous_packet` is `{}`; a chronic action that has been standing
unchanged for a fortnight is announced as *"**Something changed:** the longer-term
recovery markers now meet the threshold for a deload proposal"*. Nothing changed —
the app simply lost its comparison point. The same occurs after any morning-generation
failure that leaves a date without a read, and on the first run in a fresh
environment.

**Remediation stub** — treat "no previous packet" as *unknown*, not as "different":
skip candidate generation for a kind when no comparison baseline exists, and record
the skip reason in the result. If a first-observation message is wanted, give it its
own wording ("Where things stand:") rather than "Something changed".

---

### CC188-09 — Medium — each read packet embeds a verbatim copy of its own system prompt, doubling it per generation and re-injecting it unbudgeted into every anchored chat turn

**Evidence**

- All eight read packets store `prompt.system` = the module's `SYSTEM_PROMPT`
  verbatim (`morning_analysis.py:596-598`, `post_workout_analysis.py:499`,
  `post_walk_analysis.py:323`, `post_strength_analysis.py:312`,
  `post_flexibility_analysis.py:411`, `reviews.py:1141`, `handover.py:266`,
  `trends.py:894`).
- The generation call passes `system_prompt=SYSTEM_PROMPT` **and** a user prompt that
  JSON-dumps the whole packet (`morning_analysis.py:333-340`, `:689`, `:976-981`;
  `post_workout_analysis.py:633`, `:911-914`).
- `brief_chat._build_system_prompt` appends `_packet_json(analysis.context_packet)`
  with no size limit (`brief_chat.py:493-496`, `:501-502`); `APP_STATE_CHAR_BUDGET`
  governs only the `appState` block (`chat_context.py:88-94`).
- Measured: `morning_analysis.SYSTEM_PROMPT` is **11,254 characters** (~2.8k tokens);
  `post_workout_analysis.SYSTEM_PROMPT` is 6,755.

**Failure scenario**

Two consequences. (a) Every morning generation pays for ~2.8k tokens of duplicated
system text; the same for each of the other seven surfaces. (b) Worse for integrity:
an anchored chat turn receives the morning read's *entire instruction set* —
"Return concise markdown…", output-section rules, the `outputRules` key list — inside
a block labelled "Mark's information behind that read, as it stood when you wrote it".
The chat prompt never says those are a record rather than instructions to follow, and
an 11k-character instruction block sitting in user-prompt position beside a
3.5k-character system prompt is a live prompt-hygiene risk: the read's formatting and
scope rules can bleed into a conversational answer that Batch 178 deliberately made
short and conversational.

**Remediation stub** — stop storing `prompt.system` in the packet; keep
`prompt.version` (which is what regeneration and currentness actually key on) and, if
the exact text is wanted for forensics, store a hash. If the verbatim text must be
retained, strip the `prompt` node in `_packet_json` before it reaches the chat, and
bring the packet under a character budget of its own with the same
`omittedForLength`-style naming.

---

### CC188-10 — Medium — unprompted coach speech has no holiday guard

**Evidence**

- `run_state_change_coach` (`scheduler.py:302-340`) iterates active profiles with no
  holiday check — contrast `run_weekly_review_delivery`, which counts a
  `skipped_holiday` outcome per Decision #265.
- The weekly-mix lane has no suppression of any kind
  (`state_change_coach.py:355-364`); only the chronic lane inherits Batch 182's
  plan-based suppression.
- `holiday_pause` marks a paused session `status="skipped"`
  (`holiday_pause.py:309`), and `summarize_weekly_mix` counts a *future* skipped
  session as `remaining_planned` while excluding a *past* one, with
  `at_risk = due > remaining` (`weekly_mix.py:206-231`). So a bucket mechanically
  flips to at-risk as a holiday week progresses.

**Failure scenario**

Mark is away Monday to Friday; the holiday pause skipped the week's two threshold
sessions. On Wednesday the Monday session is past-and-uncompleted (excluded from
`remaining`) while Friday's is still future (counted), so `due=2 > remaining=1` and the
bucket flips to at-risk for the first time. The coach posts, mid-holiday,
*"Threshold has gone at risk this week (2 still due, 1 still scheduled). I have not
moved anything; this is a heads-up while there is still time to choose a fix."* The
whole point of the holiday pause is that there is nothing to fix.

**Remediation stub** — apply the same holiday check the weekly-review job uses before
any candidate generation, and separately give the weekly-mix lane a suppression rule
mirroring the chronic lane's (`suppressedByPlan`): no at-risk heads-up when a
recovery/taper/holiday window covers the remainder of the week.

---

### CC188-11 — Medium — `verdictImpact` / `planMutation` are declarations, not enforcement

**Evidence**

The packet writes the literals `"verdictImpact": "none"` and `"planMutation": "none"`
(`state_change_coach.py:275-276`), and the only test asserts those same literals are
present (`tests/test_state_change_coach.py:143-144`). Nothing asserts the service
performed no verdict or plan write. The same pattern appears in
`ChronicActionSignal.to_packet` (`chronic_patterns.py:276`) and
`week_ahead` (`classificationImpact`).

The claim is **true today** by construction — the service's only writes are one
`Analysis` and one `BriefMessage`, and `ANALYSIS_TYPE_STATE_CHANGE` is absent from
`training_week.ACTION_AUDIT_TYPES` and `chat_context._READ_TYPES`. But nothing
prevents a future edit from adding a plan write beside a packet that still declares
`planMutation: "none"`.

**Failure scenario**

A future batch extends the state-change coach to auto-apply a same-week rearrangement
("it already knows the swap"). The declaration string is copy-pasted unchanged, the
existing test still passes, and the audit trail asserts a boundary the code no longer
honours — while `verdictImpact: "none"` is exactly what a reviewer would grep for to
confirm the boundary.

**Remediation stub** — make the claim testable: assert after a `run` that no
`PlannedWorkout`, `Analysis` of an action-audit type, or verdict-bearing row was
created or modified for the profile, rather than asserting the string. One shared
helper can cover every surface that declares `verdictImpact`/`planMutation`/
`classificationImpact`.

---

### CC188-12 — Medium — the propose affordance and the coach's words are decided by two independent mechanisms

**Evidence**

- The button is attached whenever Mark's *question* contains one of ten keywords
  and a live adjustable workout exists — the model's answer is not consulted
  (`brief_chat.py:207-220`, `:425`).
- The keyword list includes `"harder"` (`:219`).
- The frontend renders a "Propose this adjustment" button from
  `proposedPlannedWorkoutId` alone (`CoachConversation.tsx:186-199`), which POSTs to
  `/api/v1/workout-delivery/planned-workouts/{id}/proposals` with no body
  (`:120-134`).
- `PROPOSE_CONFIRM_RULE` is always in the prompt (`coach_policy.py:190-195`), while
  `_capability_instruction(None)` simultaneously forbids mentioning proposals when
  nothing is adjustable (`brief_chat.py:280-284`).

**Failure scenario**

Mark asks, from the Week page on a training day, *"Am I strong enough to go harder in
the next block?"* The keyword `harder` matches, a live ride exists, and a button
labelled **"Propose this adjustment"** is attached to an answer about next month.
Tapping it proposes an adjustment to *today's* ride that the coach never suggested.
Decision #29 still holds — it lands as a proposal requiring approval on Delivery, and
the toast says so — but the affordance and the words disagree. The inverse also
occurs: *"can we knock twenty minutes off tonight?"* matches no keyword, so a genuine
adjustment request the coach agrees to gets no button.

**Remediation stub** — either narrow the trigger to phrases that unambiguously request
a change to *today's* session, or (better) require both the keyword and a structured
marker the model emits for "I am offering an adjustment", so the button only appears
under an answer that actually offered one. Also decide, and state in the prompt, which
of the two capability instructions wins when nothing is adjustable.

---

### CC188-13 — Low — the "since this read" activity delta is anchored on activity start time although an ingest timestamp is available

**Evidence**

`_activities_since` filters `Activity.start_utc >= since_utc` where `since_utc` is
`analysis.generated_at_utc` (`chat_context.py:476-492`, `:314`) — i.e. when the ride
*happened*, not when the app learned of it. An ingest anchor already exists and is
unused: `Activity` carries `created_at`/`updated_at` via `UpdatedAtMixin`
(`models/coaching.py:100`, `models/base.py:19-30`).

**Failure scenario**

Mark rides 06:15–07:15. The morning brief regenerates at 07:30 after his check-in,
before the hourly Garmin poll imports the ride at 08:10. He asks about the ride at
08:30: `activitiesCompletedSinceRead` is empty and `anythingChangedSinceRead` can be
false, even though the app learned of the ride after the read was written. Mitigated
in practice — `recentActivities` (21-day window) still carries the ride, so the coach
can see and discuss it; only the delta's framing is wrong.

**Remediation stub** — anchor the delta on `Activity.created_at` (or on
`created_at OR start_utc`, whichever is later, so a backfilled historical import does
not read as "new since the read"). No migration needed. Note the same question for
`_check_ins_since`, which uses `entry_at_utc` — correct there, since a check-in is
authored live.

---

### CC188-14 — Low — the only unversioned, unaudited LLM prompt is the one that writes into persistent coach memory

**Evidence**

`conversation_learning.py` calls `generate_anthropic_text` (`:160`) with a
`SYSTEM_PROMPT` (`:59-86`) and has **no** `PROMPT_VERSION` constant — the only
Anthropic-calling module without one. It is absent from `READ_PROMPT_FLOORS`.
Accepted proposals write the versioned `learned_context` KB section, which
`morning_analysis` then injects into the packet (`morning_analysis.py:562`).

The safety design here is genuinely strong and this is **not** a floors gap: the
prompt is not user-facing, the extraction is bounded by strict Pydantic schemas
(`:115-134`), a deterministic filter rejects transient/coercive/verdict content, and
nothing reaches memory without Mark's explicit accept. The gap is versioning: a
stored proposal cannot be attributed to the prompt that produced it, and a prompt
change cannot invalidate proposals generated under the old one — the invalidation
mechanism every other surface has.

**Remediation stub** — add a `PROMPT_VERSION` and stamp it on
`ConversationLearningProposal`; record the disposition ("LLM, not user-facing,
deliberately outside `READ_PROMPT_FLOORS`") in `coach_policy.py`'s docstring so the
omission is a documented decision rather than an oversight.

---

### CC188-15 — Low — field-level truncations are silent and never named in `omittedForLength`

**Evidence**

`_latest_reviews` truncates each review's conclusions to
`REVIEW_CONCLUSION_MAX_CHARS = 900` (`chat_context.py:400`, `:102`) and
`_plan_changes_since` truncates each summary to 200 (`:564`). `_truncate` appends
`"..."` (`:735-740`) but neither appears in `omittedForLength`, whose meaning string is
the only thing telling the model that a shortfall is a trim rather than an absence
(`:639-645`). `recentWindows` is likewise pre-sliced to the last six windows
(`:376`) — mitigated by `windowsAvailable` stating the true count (`:377`).

**Failure scenario**

The weekly review's conclusions run past 900 characters, which is routine for a
`Bottom line` + Trends + Wins + Concerns + Recommendations review. Mark asks what the
review recommended; the coach sees the recommendations cut off mid-sentence with a
bare ellipsis and no instruction covering that case, and can report the review as not
covering something it covered.

**Remediation stub** — record field truncations in `omittedForLength` in the same
`section.field` form already used for `trends.recentWindows(oldest)`, or replace the
bare ellipsis with an explicit inline marker the prompt's "trimmed for length" rule
recognises.

---

### CC188-16 — Low — `APP_STATE_CHAR_BUDGET` is a soft cap the trim can exit above

**Evidence**

`_apply_char_budget` drops the three `_DROP_ORDER` sections, then trims trend windows
while `len(trend_windows) > 1` (`chat_context.py:627-638`). If the block is still over
budget it simply returns: `weekAhead`, `today` and `sinceThisRead` are never dropped by
design (`:158-163`). The module docstring says the block "is capped at
`APP_STATE_CHAR_BUDGET`" (`:35-39`), which overstates it.

**Failure scenario**

Benign today — a full block measures ~22k against a 30k budget, and the load-bearing
sections are small. It matters only alongside CC188-09: the *total* prompt has no
ceiling at all, because the larger input (the packet) is unbudgeted.

**Remediation stub** — document the cap as best-effort in the docstring, and log when
the trim terminates over budget so the assumption is monitored rather than assumed.

---

### CC188-17 — Low — the state-change coach's idempotency path is unreachable

**Evidence**

`_existing_analysis` (`state_change_coach.py:466-497`) and `_message_for_analysis`
(`:499-513`) implement an "already delivered → return the existing message" path
(`:249-263`). It cannot run: `_budget_spent` returns true for *any*
`state_change_coach` row with `subject_date` in `[as_of - 6, as_of]` (`:452-464`), which
necessarily includes a row at `subject_date == as_of`, so `run` returns
`reason="budget_spent"` first. The project's own test confirms it — a same-day re-run
asserts `second.reason == "budget_spent"`, never `"already_delivered"`
(`tests/test_state_change_coach.py:146`).

**Failure scenario**

No live defect; 48 lines of dead code plus a `StateChangeResult.reason` value that can
never be emitted, which will mislead the next reader into believing there is a
same-day idempotency rail independent of the budget.

**Remediation stub** — delete both methods and the `already_delivered` branch, or move
the `_existing_analysis` check ahead of `_budget_spent` if a same-key re-delivery guard
is genuinely wanted independent of the budget.

---

### CC188-18 — Low — the deterministic coach-speech surfaces are outside the floors audit by correct judgement, but nothing records that judgement

**Evidence**

`coach_policy.py`'s docstring explains why the *read* prompts are audited rather than
rewritten (`:8-25`) but says nothing about the surfaces that speak without a model.
`state_change_coach.py` and `nudge_alerts.py` both put text directly in front of Mark
— an assistant turn in the coach thread and push bodies / the 20:00 sleep nudge — with
no reference to the floors and no note that they are deliberately out of scope.
`state_change_coach.PROMPT_VERSION` (`:27`) names a template revision, and the module
sets `model_name=None`, `raw_response={}` (`:285`, `:289`) — there is no prompt.

**Failure scenario**

A reviewer greps `PROMPT_VERSION`, finds 16, finds 8 audited, and reaches the wrong
conclusion in either direction: either that eight prompts are unaudited (they are not
prompts), or that a deterministic template is covered by the floors (it is not). The
Batch 188 plan itself made the first inference.

**Remediation stub** — record the disposition table from §188.1 in `coach_policy.py`'s
docstring, and rename the deterministic constants to `TEMPLATE_VERSION` (or
`RULES_VERSION`) so the distinction is visible at the grep, not only in the review.

---

### CC188-19 — Low — a suppressed lower-ranked transition is lost permanently, not deferred

**Evidence**

`choose_ranked_candidate` returns exactly one candidate and the rest are discarded
(`state_change_coach.py:76-84`, `:237`) — Decision #268's deliberate drop-don't-queue
rule. The unstated consequence is that they are unrecoverable: the comparison baseline
is the previous morning packet (`:408-421`), which is written by `morning_analysis`
regardless of whether the coach spoke, so by the next run `previous_value` already
equals the current value and `transition_candidate` returns `None` (`:65-73`).

**Failure scenario**

Both a chronic action and a weekly-mix bucket transition on the same morning. Chronic
wins. The weekly-mix transition is never mentioned — not "later", not "when the budget
frees up", but never. This is within Decision #268's letter ("discarded rather than
queued") but the decision's stated reason is staleness, which implies deferral was the
alternative; permanence is a stronger property than the decision records.

**Remediation stub** — documentation, not code: state in `DECISIONS.md` (or the module
docstring) that a dropped transition is permanently dropped because the baseline moves
independently of delivery. Revisit only if CC188-01's ranked budget is implemented,
which changes the trade-off.

---

### CC188-20 — Low — the unprompted-speech detection layer has no test coverage

**Evidence**

`tests/test_state_change_coach.py` has four tests. Three are pure unit tests over
`transition_candidate`, `choose_ranked_candidate` and `_chronic_snapshot` (`:44-76`).
The one DB test subclasses the service and overrides `_candidates` to return a
hand-built list (`:79-91`), so `_candidates`, `_current_chronic`,
`_current_weekly_mix`, `_experiment_candidates`, `_previous_morning`,
`_previous_experiment_evaluation`, `_chronic_snapshot_from_packet` and
`_weekly_mix_snapshots_from_packet` are **never executed under test**.

**Failure scenario**

Every finding in this review that lives in the detection layer — CC188-02's parameter
asymmetry, CC188-08's absent-baseline transition, CC188-10's holiday gap — would have
been caught by a single end-to-end test that seeds a previous morning packet and lets
the real `_candidates` run. None exists, so the whole detection half of the newest
proactive surface reaches production on hand-verification only.

**Remediation stub** — add DB tests that seed a previous morning `Analysis` with a real
`verdict.chronicAction` / `verdict.weeklyMix` packet and exercise `_candidates`
unstubbed: standing state → no message; genuine flip → message; missing previous read →
(currently) message, which is the CC188-08 regression to pin once fixed. Note that
`_experiment_candidates` runs a full `ExperimentEvaluationService.run(commit=False)` per
active experiment on every daily pass — deterministic and unpaid, but its rows are
persisted by the `no_transition` branch's commit (`:239-247`), which is worth asserting
deliberately either way.

---

## Findings summary

| ID | Sev | Title | Primary file |
|---|---|---|---|
| CC188-01 | High | Unprompted-speech budget spent first-come, not best-first | `services/state_change_coach.py` |
| CC188-02 | High | Announced state recomputed with different inputs from the read Mark was given | `services/state_change_coach.py` |
| CC188-03 | Med | Pre-read workout closures reported as changes since the read | `services/chat_context.py` |
| CC188-04 | Med | Floor audit matches topic adjacency; an inverted rule passes | `services/coach_policy.py` |
| CC188-05 | Med | Floors audit is closed-world; a new prompt surface is never forced in | `tests/test_brief_chat_prompt_policy.py` |
| CC188-06 | Med | App-state block claims "current truth"/"evidence" against the Batch 181 floor | `services/chat_context.py` |
| CC188-07 | Med | `local_clock_times` audited nowhere and matched by no prompt | `services/coach_policy.py` |
| CC188-08 | Med | Absent previous morning read fabricates a transition | `services/state_change_coach.py` |
| CC188-09 | Med | Packet embeds its own system prompt; doubled per call, unbudgeted in chat | eight read services + `services/brief_chat.py` |
| CC188-10 | Med | No holiday guard on unprompted speech | `src/scheduler.py`, `services/state_change_coach.py` |
| CC188-11 | Med | `verdictImpact`/`planMutation` declared, not enforced | `services/state_change_coach.py` |
| CC188-12 | Med | Propose affordance and the coach's words decided independently | `services/brief_chat.py` |
| CC188-13 | Low | Activity delta anchored on start time when an ingest timestamp exists | `services/chat_context.py` |
| CC188-14 | Low | `conversation_learning` prompt is unversioned | `services/conversation_learning.py` |
| CC188-15 | Low | Field-level truncations not named in `omittedForLength` | `services/chat_context.py` |
| CC188-16 | Low | `APP_STATE_CHAR_BUDGET` is a soft cap | `services/chat_context.py` |
| CC188-17 | Low | Unreachable idempotency path | `services/state_change_coach.py` |
| CC188-18 | Low | Deterministic speech surfaces' out-of-audit status undocumented | `services/coach_policy.py` |
| CC188-19 | Low | Dropped transitions are permanent, not deferred | `services/state_change_coach.py` |
| CC188-20 | Low | Detection layer has no test coverage | `tests/test_state_change_coach.py` |

## What was checked and holds

- No spoken surface can change the deterministic Green/Amber/Red ladder, a safety
  floor, or plan state. The verdict is computed before any model call and passed in as
  data; the state-change coach writes only an audit row and a message.
- Batch 181's observed-data humility vs deterministic ownership — the flagged
  contradiction — is explicitly resolved in both the floor sentence and
  `ANTI_SYCOPHANCY_RULE`, and consistently bounded in all eight read prompts.
- Red-never-VO2, the power-balance floor and the skipped-workout floor are present in
  every prompt that owns them (subject to CC188-04's pattern weakness).
- Every entry point into the conversation composes the identical floors text; the
  policy test proves it for anchored-morning, anchored-retrospective and cold-open
  assemblies.
- `omittedForLength` names every whole-section drop, distinguishes a trim from a
  genuine absence, and never drops `weekAhead`/`today`/`sinceThisRead`.
- `adjustable_workout_id` resolves from live plan rows with an authoritative holiday
  check, from any entry point.
- The origin vocabulary is closed; unknown client values degrade to `general` and raw
  client text never reaches the prompt.
- Batch 182's Red qualification and recovery-block plan-suppression are inherited by
  the chronic lane in code, not merely asserted in copy.
- Experiment outcomes never auto-conclude an experiment.
- `state_change_coach` and `nudge_alerts` copy contains no banned internal vocabulary.

## Boundaries respected by this review

Diagnose-only. No product code, prompt text, prompt version, floor, verdict logic,
threshold, config or data was changed. The only executable work performed was
read-only introspection of `coach_policy` patterns against the in-repo prompt strings
(reported inline above); no production data was accessed — that belongs to Batches 190
and 191.
