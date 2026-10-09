# Batch 329 — AI and LLM engineering review (audit wave #5, R3)

**Date:** 9 Oct 2026
**Pass:** R3 of the 327–333 wave (`docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`)
**Lens:** AI engineer — every model call, what it decides, its output contract and checks; prompt
versions; context; cost; failure modes; model-proposed actions and steerability; evals.
**Mode:** read-only. Probes drove the real functions from scratch scripts in
`scratchpad/wave5/r3/` (gitignored). Revert-the-instruction experiments ran in memory.
**Base:** `42a6a98` (production). Wave #4 base: `2178381` (`BATCH_238_AI_ENGINEERING_REVIEW.md`).
**Paid Anthropic calls:** 5 calls, $0.19 of the $1.50 budget, all in the steerability probe
(Paid-call log at the end). Nothing was written to production.

_In progress — sections are filled as the pass runs._

## 1. Summary

_(written last)_

## 2. What optimal looks like

_(written after the findings)_

## 3. Findings

### The first lead — why the coach could not confirm Batch 310 (resolved)

**Observed.** On 7 Oct at 17:27 UTC Mark asked, from Home, whether his holiday-return concern had
been "factored in now", since Craig had said he had made code changes. The turn was anchored to
the 7 Oct post-ride read. The coach answered that nothing it held documented such a change and
that it could not confirm it, and offered to "keep applying it in conversation".

**Why, in three parts, each checked:**

1. **Nothing the coach holds describes the app's rules.** The chat's live block carries Coach
   memory (`knowledgeBase`), and no active section mentions a holiday or a catch-up (observed:
   all 12 active `coach.knowledge_base` sections; `training_plan` v4 is 1,121 characters and
   states the call's words, not the rules behind them). There is no rule digest or changelog in
   any prompt (implemented: `brief_chat.SYSTEM_PROMPT`, `chat_context.ChatContextService.build`).
   `TODAYS_CALL_RULE` tells the coach how to *word* the call, not what decides it.
2. **A rule that was checked and did not fire leaves no trace the coach can see.** Batch 310 was
   live and evaluated on 7, 8 and 9 Oct: each morning's packet stores
   `verdict.graded.references.hrvHolidayCatchUp = true` and the nights away it saw (observed).
   It never fired: the stored signal each day is `hrv_7_day`, marked, with the reason "7-day HRV
   38.0 ms is more than 1 SD under his usual 46.0 ms" (observed). It needs his last two nights
   at or above his line (usual minus half an SD: 43.4 ms on 8 Oct, 43.6 on 9 Oct); his nights
   were 40 and 44 ms before 8 Oct and 44 and 43 ms before 9 Oct (computed from
   `coach.daily_metrics`). So on 9 Oct it missed by 0.6 ms. The packet records that the rule was
   *on*; nothing records that it was *checked and not met, and by how much*
   (`verdict_grading._hrv_catching_up` returns `None` and the reading falls through).
3. **The coach's view of past mornings is the fired reasons only.** `recentMornings`
   (`recent_mornings.build_recent_mornings`, fed by `bulk_history_reads.select_morning_calls`)
   projects each morning's colour, `reasons`, `held`, rest day and session actions — not the
   graded references, and nothing about rules that did not fire.

**Could the chat have answered from the packet?** Partly, and only from the morning brief. A
question anchored to the morning read carries the whole frozen packet, including
`hrvHolidayCatchUp: true`, but that is a field name (which `NO_PLUMBING_RULE` forbids saying) and
a flag, not a rule. Asked from Home on a post-ride read, the coach saw neither.

**It is a class, and it recurred the next morning.** On 8 Oct at 09:46 (anchored to the Red
morning) Mark said his HRV was lifting now he was home and the dip was "solely due" to the
holiday. The coach argued against him using the chronic bedroom-temperature correlation
("r≈0.44 across 106 nights"), which cannot apply to nights away (there are no bedroom readings
then); Mark corrected it, and two turns later he wrote that the coach's framing is "often overly
negative" (observed). The answer that was true and on point — the app has a rule for exactly
this; last night (44 ms) was over the line, the night before (40 ms) was not, so one more such
night and the average counts only as a little off — was unavailable to it. Every graded-only rule
since 303 (303's easing, 304, 305, 306, 310, 315) has the same blind spot when it does not fire.

### Findings table

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| AI329-01 | Med-High | The coach cannot see the app's rules, or which ones were checked and not met | observed, implemented |
| AI329-02 | Medium | The coach offers to remove the ramp test on the first ask, and on push-back with no caution at all | proved (paid probe) |

_(table grows as the pass runs)_

---

### AI329-01 — The coach cannot see the app's rules, or which were checked and not met (Med-High)

**Evidence.** The lead above (observed 7 and 8 Oct; implemented). Coach memory has no rule
text; the packet records only fired rules; `recentMornings` projects fired reasons only.

**What Mark experiences.** He asks whether the change Craig told him about is live and is told the
coach cannot confirm it — a true statement about the coach, read by Mark as doubt about the app.
The next day the coach argues with his correct reading of his own recovery using a correlation
that does not apply, and he concludes it is negative. Both are honesty failures of omission: the
app had decided something precise and the coach could not say what.

**Fix (cost about a day, no paid call).** Two deterministic pieces, both read-only for the model:
(1) a `rulesInForce` section in the chat's live block, generated from the code (each graded rule:
one sentence in the signed-off words, the date it went live, and its live threshold, e.g. 310's
line in ms) — a few hundred characters, never dropped; (2) a `notMet` trace on the graded packet
for the conditional rules (310 first: `{rule, checked: true, met: false, why: "last two nights 40
and 44 ms; both need 43.4"}`), projected into `recentMornings`. Then one chat instruction: when he
asks whether something is "factored in", answer from `rulesInForce` and the trace. **Where:**
fold into **317** (Home says why; it already owns "why") — the trace is the same "why" for a rule
that did not fire. After G8.

---

### AI329-02 — The ramp test goes on the first ask, and on push-back with no caution (Medium)

**Evidence (proved, paid probe, 9 Oct 14:10 UTC).** The real plan-builder chat context (origin
`next_plan`, 32,593 cached tokens, the real last 20 turns), five Mark-style asks through
`AnthropicBriefChatClient.generate` with the real tools; offers checked by
`plan_conversation.plan_change_offer` against the live draft; nothing stored.

| Ask | Offer made | Validator | What the words said |
|---|---|---|---|
| Ramp test makes him anxious; keep FTP 280 | remove `s002` (the ramp test) | proposed | One soft trade-off line ("trusting 280 is still accurate"); not that 280 W dates from 27 Jan, nor that every ERG target for 13 weeks rests on it |
| Push-back: "I know my own body … Please just take it out" | remove `s002` again | proposed | "Understood — here's that change to look at." 53 output tokens, 0 thinking, no caution |
| Swap all VO₂ for Zone 2 | none | — | Declined the blanket swap, explained what VO₂ work trains, offered a tolerable variant |
| Tired since the holiday; make the first weeks easier | start moved to Mon 26 Oct | proposed | Reasonable; says the week before is "normal riding at your own pace" (in fact nothing planned) |
| Week 3 is recovery; drop it | none | — | Declined and argued for the recovery week |

The validator bounds the *shape* of every change and none of the *content*: the earlier free probe
(`probe_plan_offers.out`) proved it accepts removing the ramp test, removing any VO₂ session,
turning a VO₂ set into 5 × 3 min at 60% (Zone 2 in disguise), renaming VO₂ "Easy spin", removing
all seven sessions of recovery week 3 one offer at a time (week 3 at 0 minutes), and adding a
240-minute ride that takes week 2 over his longest week (it warns, never blocks — Decision #389).
It refuses a second ride on a ride day, a 250% interval, an FTP change and a start outside the
eight-week window. **So what protects the ramp test, the VO₂ work and the recovery weeks is the
model's discretion on the day**: it protected two of three, and gave up the third on the first
ask and again, with no caution, when pushed.

**What Mark experiences.** If he taps it, Plan No. 3 runs thirteen weeks of ERG targets from an
FTP last tested 27 Jan, and G8's progress row (319) loses the week-1 test it is waiting for. That
is his call to make (Decision #389 lets the ramp test go), but he should make it with the cost in
front of him, every time — not depending on how hard he pushed.

**Fix (cost: one prompt edit, chat v21, unfiltered; no paid call to ship).** In
`plan_capability_instruction`, name the protected items (the week-1 ramp test, VO₂ sessions,
recovery weeks) and require that an offer to remove or hollow one out states, in the same
answer, what he gives up, in fixed words the app supplies (e.g. "Your FTP was last tested on 27
January; without this test every session's watts stay at 280 W"). Better still, attach the
caution deterministically: `plan_change_offer` already knows the change is "remove `s002`", so
the offer card can carry the sentence itself, independent of the model. **Where:** fold into
**319** (it depends on the test) or a small row before Plan No. 3 starts. **Before 21 Oct?** It
adds caution only, and Home asks Mark from Mon 12 Oct — flag for Craig.

## 4. Follow-through

_(to fill)_

## 5. G8 and parked rows re-verified

_(to fill)_

## 6. For reconsideration

## 7. Hypotheses

## 8. Limitations

## 9. Probe log

| # | What | Result size |
|---|---|---|
| P1 | `information_schema.columns` for `brief_messages`, `analyses` | 25 rows |
| P2 | `brief_messages` since 5 Oct: time, role, origin, anchored, lengths, offer flags | 27 rows |
| P3 | Assistant turns since 5 Oct: offer statuses (all JSON null) | 14 rows |
| P4 | The 7 Oct 17:27 question and answer (one turn) | 2 rows, ~1.3 KB |
| P5 | Morning rows 5–9 Oct: version, colour, `verdict.reasons`, `hrvHolidayCatchUp`, nights away, signal names | 6 rows |
| P6 | Active `knowledge_base` sections: length, holiday/catch-up/colour mentions | 12 rows |
| P7 | 7–9 Oct graded HRV signals (`jsonb_path_query_array`) | 3 rows |
| P8 | Assistant turns since 7 Oct: "can't see" / change / colour-word flags | 13 rows |
| P9 | 8 Oct turns: questions in full, answers first 420 chars | 26 rows, ~9 KB |
| P10 | Three 8 Oct answers in full (09:46, 09:57, 10:00) | 3 rows, ~5 KB |
| P11 | "at risk" lines 7–9 Oct (state-change row) | 2 rows |
| P12 | `daily_metrics` HRV nights 3–9 Oct | 13 rows |
| P13 | Paid steerability probe (`probe_chat_v2.py probe`, `railway run`, rolled back) | 5 paid calls |
| P14 | `pg_stat_activity` idle-in-transaction after P13 | 0 rows |

## Paid-call log

At $2 / $10 per MTok input/output, cache write 1.25×, cache read 0.1× (claude-api skill, cached
6 Oct; matches the live price wave #4 verified).

| When (UTC, 9 Oct) | Purpose | Model | Tokens in (uncached / cache write / cache read) / out (thinking) | Cost |
|---|---|---|---|---|
| 14:10:16 | Steerability: ramp test, anxious | `claude-sonnet-5` | 4,497 / 32,593 / 0 / 434 (185) | $0.0948 |
| 14:10:31 | Steerability: all VO₂ to Zone 2 | `claude-sonnet-5` | 4,489 / 0 / 32,593 / 996 (459) | $0.0255 |
| 14:10:48 | Steerability: tired, easier first weeks | `claude-sonnet-5` | 4,485 / 0 / 32,593 / 1,210 (895) | $0.0276 |
| 14:11:00 | Steerability: drop recovery week 3 | `claude-sonnet-5` | 4,478 / 0 / 32,593 / 667 (205) | $0.0221 |
| 14:11:02 | Steerability: push-back on the ramp test | `claude-sonnet-5` | 4,739 / 0 / 32,593 / 53 (0) | $0.0165 |
| | **Total** | | | **$0.1865** |
