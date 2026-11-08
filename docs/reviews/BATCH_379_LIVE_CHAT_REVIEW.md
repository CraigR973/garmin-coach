# Batch 379 — Live coach conversation: sanitised review record

**Status (8 Nov 2026):** the read-only review is complete and awaits Craig's
explicit acceptance. Batch 379 is **not** complete. Batch 345 stays in progress;
Batch 378 is untouched. This record holds no conversation wording, captures or
health values. Mark's verbatim questions and answers, and the source extracts,
are kept in git-ignored private evidence (`scratchpad/batch-379-live-chat/`,
owner-only files). Answers are numbered #1–#43 there and here.

## Method

- **Read-only.** SQL reads used one `READ ONLY` transaction, asserted in the
  extract scripts, plus Supabase reads, Railway deployment metadata, retained
  Railway runtime logs, health GETs and an import-only container check.
- **No writes or changes.** No model call, regeneration, live chat, test
  notification, production write, configuration change or deployment.
- **24 Sep case.** The historical 24 Sep evaluation case is preserved
  (timestamp-selected in `scripts/run_coach_voice_eval.py`) and was not replayed.
- **Deployed at review time.** Railway and the Vercel proxy both serve
  `df1203b`, a docs commit whose code is PR #440's `0bd06aa`. Readiness is
  `db: ok`. Chat runs `coach-chat-v31-2026-11-02`, `claude-sonnet-5`, high effort
  and 24,576 tokens, with 10 tools including `pass_to_craig`. Local `main` is that
  commit plus the two unpushed planning commits (`090d7c2`, `733bcd8`), with no
  code difference.

## Agreed scope (Decision #483)

- **Covered:** every real question and answer under the trial voice, from the
  v25 deploy (20 Oct, 20:49 UTC) to the last stored answer (7 Nov, 10:28 UTC).
  That is 43 pairs, none sampled.
- **Decides acceptance:** the 11 answers on v31 (2–7 Nov). The 32 earlier ones
  (v25–v30) show trends and whether faults recur.
- **Excluded:** three thread posts that answer no question (two weekly reviews,
  one experiment notice).
- **Added later:** answers Mark gives before acceptance. Rechecked at 11:14 GMT
  on 8 Nov: none since 7 Nov.
- **Gaps:** stay open pending natural conversations.

## Provenance limits

- **Prompt version per turn: inferred.** It comes from Railway deployment
  `createdAt`, because `BriefMessage` stores no prompt version. One answer (#33)
  falls 4 minutes after a docs-only deploy; both sides are v31.
- **Model and effort: stored.** They are in `generation_usage`, with token
  counts, estimated cost, model time and lookup count. Tool names are not
  stored.
- **Ask-time context and lookup results: not stored.** Claims were checked
  against records whose timestamps show they existed before the question
  (`daily_metrics` morning rows, morning and post-ride reads, versioned
  `planned_workouts`, activities, check-ins, recorded disruptions).
- **Values that changed later: unknown at ask time.** Some morning rows were
  updated after the question with no history kept, so their current values
  stand in for ask-time values.
- **Railway logs: about 7 days.** 2–7 Nov is verifiable. Failed or rejected
  attempts and alert events for 21 Oct–1 Nov are unknown.
- **No post-cleanup answers exist.** All 43 ran before the cut-path retirement
  (7 Nov, 15:37 GMT). Every one was an ordinary model answer: each has stored
  usage, and none came from a code-composed path.

## Results

| Prompt | Answers | OK / minor / material |
|---|---|---|
| v25 | 7 | 5 / 2 / 0 |
| v27 | 6 | 0 / 0 / 6 |
| v29 | 9 | 2 / 4 / 3 |
| v30 | 10 | 7 / 2 / 1 |
| **v31** | **11** | **5 / 2 / 4** |

**Held on v31.**

- **Answer first:** 10 of 11 lead with the answer; the 11th gives the key fact
  first.
- **Length:** 66–100 words.
- **Wording:** no banned or internal terms stored, no third-person references
  and no label-first openers.
- **Calls and floors:** no call or floor was argued down.
- **Plan changes:** no plan or interval change was offered. The one boundary
  statement is correct.
- **Pass-on:** no pass-on was claimed, and the retained logs show none raised.
- **Guard and failures:** 18 of 18 chat submissions on 2–7 Nov returned 200
  with a stored answer. The logs show no guard rejection or failure.

**Material on v31.**

- **#37 — a claim the records contradict.** It said two recovery measures had
  stayed within their usual ranges throughout the six-week window. The stored
  daily records show several mornings outside them. It made no lookup first.
- **#39 — two misdescriptions inside a correct answer.** It misdescribed the
  training phase of part of the period, and one session's type and recovery
  effect. The core figures matched.
- **#34 — an invented mechanism.** It explained a device score as depending on
  how the platform classifies the workout's name. The figures were correct.
- **#33 — a mislabelled record, repeated faithfully.** An operator plan move
  (Decision #462, run through `swap_day`) is stored as `today_card_swap`. The
  coach repeated that label, could not give the reason and did not pass on the
  reported schedule problem. Mark then moved the session back, which also hit
  the event bug that Batch 374 fixed.
- **Minor:** median figures called averages (#36, #38).

**Trend in earlier answers.**

- **24 Oct (v27), six answers.** The coach repeatedly denied that an earlier
  thread conversation existed, implied Mark was mistaken, used the third
  person, and made two pass-on claims nobody can now check. Cause: it then saw
  only the last 10 turns and no planned-session contents. Both were addressed
  on 25 Oct (Batches 349 and 350). No comparable question has come since, so
  the fix is unproven in live answers.
- **28–29 Oct (v29).** It attributed a six-week trend to a recorded disruption,
  which the records do not support, then reversed itself the next day without
  saying so. One answer chain was not answer-first and overstated how much a
  session type contributes to training load. A 12-week comparison mixed wake
  and end-of-day observations and so overstated the change. The v31 answers
  quote the app's own with/without-disruption figures correctly.
- **31 Oct (v30).** It contradicted itself on whether the planned ride stood
  until a pick was made. The tired-morning pick still exists, so this can
  recur.

**Cost and wait (recorded).**

- **All 43:** $3.96 estimated, $0.092 an answer. Model time median 17.6 s,
  90th percentile 48 s, max 125 s.
- **v31:** $1.25, $0.114 an answer. Model time median 23.7 s, max 59 s. Server
  time from request to answer (retained logs) median 36 s, max 66 s, with 7 of
  11 over 30 s.
- **Not measured:** phone and network time.

**Pass-on.** v31 made no claims. In three v31 exchanges Mark reported a problem
or challenged an app decision, and no pass-on was attempted. The tool's
description covers both cases. Delivery and receipt belong to Batch 378. No
replacement-route claim exists to check.

## Gaps (open)

1. No answers since the cut-path cleanup.
2. No cut or HRV-floor challenge since the cleanup. Two floor-adjacent ones
   came before it, on v30 and v31.
3. No symptom report.
4. No interval or plan-change offer, so propose/approve was not exercised live.
5. No question needing older-conversation recall since the 25 Oct fix.
6. Pass-on delivery is with Batch 378.

## Outside 379 (reported, not dispositioned here)

- **Internal wording:** a morning brief and a post-ride read used an internal
  word for their input in Mark-facing text.
- **Missing input:** that brief's input lacked the next day's planned session.
- **Field names:** an older post-ride read showed internal field names.
- **Statistics:** the experiment notice shows raw correlation statistics.

## Repair candidates (not authorised; scope with Craig first)

- **R1.** Verify a claim about a period with a lookup before stating it (v31
  #34, #37, #39). This is a prompt change: Craig's words sign-off, a version
  bump and the normal evaluation procedure.
- **R2.** Give operator and owner plan moves their own provenance and a reason
  the coach can quote (#33). This is a code change with full gates.
- **R3.** Keep internal words out of brief and post-ride text (a separate
  surface).
- **R4.** Revisit when pass-on is triggered, once Batch 378 picks a route.

## Ready vs unresolved

- **Ready for Craig's acceptance (v31):** voice, phone length, answer-first,
  safety floors, answer guard, propose/approve boundary, honest pass-on
  statements.
- **Unresolved:** dated-claim accuracy (#34, #37, #39), plan-move provenance
  (#33), the six gaps, and pass-on delivery (Batch 378).
- **Batch 379 closes only on Craig's explicit acceptance against this scope.**
  Missing evidence is never waived silently.

## Row facts re-verified at batch-start (8 Nov)

- **Still accurate:** `CoachChatToolbox.execute` calls `admin_alert` with
  `KIND_COACH_FEEDBACK` and marks the turn passed once the log call succeeds;
  `_pass_on_acknowledged_error` uses the same executor; `admin_alerts.py` is
  shared; `BriefChatService.thread` and `list_coach_messages` expose the
  history; chat is v31.
- **Added:**
  - `generation_usage` stores model, effort, counts, cost, model time and a
    lookup count, but no prompt version or tool names.
  - No post-cleanup answers exist yet.
  - `daily_metrics` keeps a wake row and a settled row per date; the coach's
    lookup falls back to settled rows, which are the only kind stored before
    21 Jun.
