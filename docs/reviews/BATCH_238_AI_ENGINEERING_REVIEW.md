# Batch 238 — AI / LLM engineering review

> Read-only pass, 2026-09-01, against `2178381` — the SHA Railway direct
> (`/api/v1/health`) was serving throughout. **No code, prompt, config, schema or
> analysis row was changed.** Third of six passes in the Batch 236–241 wave; scope
> and guardrails in `BATCH_236-241_AUDIT_SCOPE.md`.
>
> The first review of this app's AI layer as a whole. `docs/claude-api-review.md`
> (2026-08-29) covered the transport boundary only and is re-verified in §6.
>
> **Anthropic spend: $0.12** — itemised in §8. Everything else came from stored
> `coach.analyses` rows, `coach.job_runs`, the deployed environment, and the code.

---

## Summary

The AI layer is better engineered than most. One boundary, nine generation
paths, a deterministic verdict the model narrates but cannot set, a shared
policy registry with an AST-discovered drift test, and a Batch API path that
pre-counts tokens before it spends. Those are real assets and §7 says which
ones to protect.

The weaknesses are all one shape: **the app can prove what it *asked* the model
for, and can prove nothing about what it *got*.** Every prompt test asserts an
instruction is present in `SYSTEM_PROMPT`. Nothing asserts the instruction was
obeyed. On 2026-09-01 a model swap silently deleted two shipped batches' worth
of user-visible sections from Mark's brief, every test stayed green, the push
fired, and the only reason anyone noticed is that a human read it.

The lead the wave handed this pass resolves cleanly, and not the way it was
framed. The wiring is right; the prompt is wrong; and nothing could have told
the difference.

---

## Lead #1 — resolved

### (a) Why `thinking_tokens: 0`? Adaptive genuinely declined. The wiring is correct.

**Proved, twice, and it cost $0.12.**

The pre-audit correctly refused to guess. The answer is that the payload *does*
carry `thinking` and `output_config`, and the zero is the model's own decision.

Chain of evidence:

1. **The code path is intact.** `configured_thinking()` / `configured_effort()`
   (`anthropic_text.py:48-60`) resolve from settings; all eight
   `generate_anthropic_text` callers pass both, and `longitudinal_analysis.py:478,484`
   merges `effort` beside its `json_schema`. The payload builder adds `thinking`
   at `anthropic_text.py:289-290` and `output_config` at `:291-292`.
2. **No environment override exists.** `railway variables --service api` lists
   exactly one Anthropic variable, `ANTHROPIC_API_KEY`. No `ANTHROPIC_MODEL`,
   `ANTHROPIC_EFFORT` or `ANTHROPIC_THINKING_MODE`. Production therefore runs
   `config.py`'s defaults: `claude-sonnet-5` / `adaptive` / `medium` / `24576`.
3. **`effort` demonstrably reaches the API and steers thinking.** A synthetic
   ~166-token prompt through the real boundary, at the real production settings:

   | effort | input | output | `thinking_tokens` | latency |
   |---|---:|---:|---:|---:|
   | `medium` | 166 | 446 | **85** | 6.1s |
   | `high` | 166 | 489 | **178** | 7.4s |

   Thinking doubles with effort. The parameter is live.
4. **The decisive one — a real packet reproduces Batch 233's `medium`
   measurement almost exactly.** Replaying Mark's stored 2026-08-31 morning
   packet through `AnthropicMorningAnalysisClient()` at the shipped settings:
   `input_tokens=26474, output_tokens=5490, thinking_tokens=3801,
   stop_reason=end_turn`, 61.7s. Batch 233's sweep recorded 5,280 / 61.1s on the
   same packet. **Adaptive at `medium` does think on this app's morning prompt.**

So `thinking_tokens: 0` on 2026-09-01 is legitimate adaptive behaviour on that
particular packet — not a defect in the wiring, and not the `low` profile
leaking in. `output_tokens: 1360` on 3,646 chars of prose is ~2.68 chars/token,
consistent with the measured Sonnet 5 tokenizer inflation, so all 1,360 tokens
were prose and none were thinking.

**What is a defect is that nobody can see this happening.** Production has now
run three Sonnet 5 calls and all three returned `thinking_tokens: 0` (morning
29,118→1,360; post-strength 4,100→465; post-workout 34,041→1,878), while a
controlled replay of a real morning packet returned 3,801. That is a
**0–3,801-token, ~4× cost swing on one path with no monitor**, and Decision
#312's whole cost/timeout model — `~$0.11/run`, `24576` ceiling, `550s` read
budget, `670s` lease — is sized for the thinking case that production has not
yet produced. See **AI238-05**.

### (b) Model or prompt? Prompt — and the proof is a one-variable replay.

**Proved.** The replay in (4) above is the exact experiment Batch 233.8 was
blocked from running: same stored packet, same prompt version, only the model
and generation settings move.

Result — Sonnet 5 at `medium` **with 3,801 thinking tokens**:

| | 4.6 stored (08-31) | 5 replay (08-31, same packet) | 5 production (09-01) |
|---|---:|---:|---:|
| chars | 8,482 | **4,421** | 3,646 |
| thinking tokens | *(field absent)* | **3,801** | **0** |
| sections | 8 | **4** | **4** |

The fresh brief thought hard and still dropped `🔬 Experiment Updates` and
`🔁 Chronic REM Pattern`. **Thinking has nothing to do with the loss.**

The sections that survive, in both Sonnet 5 runs, are exactly and only the four
named in `morning_analysis.py:229`:

> "Return concise markdown with **a sleep summary line**, **a metrics-vs-baselines
> read**, **a thermal/environment review**, and **a Green/Amber/Red workout
> verdict** for today."

09-01 headings: `Sleep summary:` · `## Metrics vs. Baselines` ·
`## Thermal / Environment Review` · `## Today's Verdict`. Four for four, in
order. Sonnet 5 read a closed list and returned a closed list.

The cross-path contrast rules out "Sonnet 5 is just terser":

| path | 4.6 mean (range) | 5 | change |
|---|---|---:|---:|
| morning | 8,470 (6,966–11,475) | 3,646 | **−57%** |
| post-workout | 5,756 (4,695–6,372) | 4,719 | −18% (inside range) |
| post-strength | 1,453 (1,235–1,741) | 1,271 | −12% (inside range) |

Only the morning brief collapses, and it is the only prompt whose enumerated
output contract is far narrower than the content it is asked to carry. See
**AI238-01**. The fix is to re-baseline the contract sentence, not to revert the
model, raise effort, or add tokens.

Two refinements to the pre-audit's loss list, from reading the artifacts:

- The **corrections acknowledgement did survive** on 09-01 ("Note on your
  check-in: you flagged that small window gaps created drafts…"), though the
  packet carried `recentCorrections` with **5** entries and one was addressed.
- **Sleep-stage detail is nondeterministic, not deleted.** Absent on 09-01;
  present and correct in the 08-31 replay, including Batch 230's basis sentence
  in full ("all percentages are share of measured sleep — deep + light + REM +
  awake"). The two sections that are gone in *both* Sonnet 5 runs are Experiment
  Updates and Chronic REM Pattern.
- The packet was not the problem. The 09-01 `context_packet` carried
  `experimentLoop.experiments` (4), `chronicSuggestions.items` (1),
  `recentCorrections` (5), and `metricsVsBaselines` entries for
  `average_respiration` and `average_spo2_pct`. All were sent and none reached
  Mark.

### (c) Can the system detect this? No — and the absence is structural.

**Proved.** There is no assertion anywhere in `apps/api` about the *content* of
a generated artifact. `grep` across `src/` for any length or completeness check
on `output_markdown` returns three hits, all of which consume it
(`tts_pregenerate.py:36`, `handover.py:806`, `weekly_review_delivery.py:123`).
The only guards at the boundary are "the text is not empty"
(`anthropic_text.py:327`) and "`stop_reason` is not `max_tokens`" (`:310`).

The prompt test suite is genuinely thorough and points the wrong way. The
clearest example is one line:

```python
# tests/test_morning_analysis.py:1598
assert "experimentLoop.experiments" in SYSTEM_PROMPT
```

That test passed on 2026-09-01, on the morning the app told Mark nothing about
any of his four running experiments. The same is true of the Floor registry:
`test_brief_chat_prompt_policy.py:268-270` proves each surface *states* its
floors; nothing proves any output *honours* one. See **AI238-02**.

---

## Findings

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| AI238-01 | **High** | The morning output contract names four sections; ~a dozen batches added content outside it | proved |
| AI238-02 | **High** | No test or runtime check ever inspects generated output | proved |
| AI238-03 | **High** | The daily paths alert the operator on `billing` only — and the alert has no recipient in prod | proved |
| AI238-04 | **High** | Transport failures still bypass the taxonomy; still no retries anywhere | implemented |
| AI238-05 | Medium | Adaptive thinking is an unmonitored 0–3,801 token variable the budgets are sized against | proved |
| AI238-06 | Medium | `recorded_data_honesty` is hand-copied into eight prompts; the audit is a regex a paraphrase satisfies | implemented |
| AI238-07 | Medium | The ninth generation path escapes the prompt-floor discovery test that claims it cannot | proved |
| AI238-08 | Medium | `longitudinal_analysis` has never run in production and skips silently every day | proved |
| AI238-09 | Medium | The highest-volume paid path discards its usage — the only cached path is the only unmeasurable one | proved |
| AI238-10 | Medium | Two JSON-extraction strategies; the fragile one writes Mark's persistent memory | implemented |
| AI238-11 | Medium | `BriefChatError` is uncaught in both chat routers; the chat ceiling now shares its budget with thinking | implemented |
| AI238-12 | Medium | One packet carries two `basis` strings for one fact — a sentence and a field-name fragment | observed |
| AI238-13 | Medium | Prompt-version → regeneration is three different contracts across 19 constants | implemented |
| AI238-14 | Low | Age bands are composed by the model from five raw numbers; a replay narrowed one | observed |
| AI238-15 | Low | `NO_INVENTED_DERIVATION_RULE` is a second, unwired copy of a shipped rule | proved |
| AI238-16 | Low | Two over-broad substring rules in classification; the batch path hardcodes status 400 | implemented |
| AI238-17 | Low | Effort was decided on a percentage; the absolute difference is ~$37/yr, and the sweep is unreproducible | proved |

---

### AI238-01 — The morning brief's output contract is a stale four-item list (High)

**What is wrong.** `morning_analysis.py:229` is the only sentence in an
18,044-character system prompt that says what the output should *contain*. It
names four sections. Everything Batches 210–231 added — the experiment loop,
the chronic REM pattern and its carried actions, the stage table,
respiration/SpO₂/VO₂max/Body Battery, the corrections acknowledgement — arrived
as *conditional content rules* ("when X is present, describe Y") scattered
through the other 17,000 characters, and none of them was ever added to the
contract. Sonnet 4.6's verbosity hid the mismatch for a year. Sonnet 5 reads the
contract as a contract.

**Where.** `apps/api/src/services/morning_analysis.py:229`. The same pattern,
with a currently-matching list, at `post_workout_analysis.py` ("a workout rating,
performance read, specific timed recovery protocol, and tomorrow impact"),
`post_walk_analysis.py`, `post_strength_analysis.py`,
`post_flexibility_analysis.py`. `reviews.py` and `trends.py` are the safe
pattern: they name their sections *as headings* the model must emit
(`**Trends**`, `**Wins**`, `**Concerns**`, `**Recommendations**` /
`**Year-on-year**`, `**Seasonal patterns**`, `**What to watch**`).

**Failure scenario.** Batch 231 shipped a corrected chronic-driver framing after
a false claim appeared on four consecutive mornings. On 2026-09-01 the framing
was correct and never printed as its own section: the chronic REM pattern
survives as half a bullet and both carried actions (protect the final 90-minute
cycle; hold the room cool into the back half of the night) are gone. Mark is not
being told the wrong thing; he is not being told the thing. Batch 221 made
*displaying* a REM action the act of issuing it, so a brief that never displays
one quietly changes the experiment's meaning.

**Fix shape.** Replace the four-item sentence with an explicit section contract
in the `reviews.py` style — required sections always, conditional sections named
with their trigger — and pin it with a test that maps each shipped section to
the packet key that triggers it. This is one prompt edit plus a `PROMPT_VERSION`
bump (which self-heals on Mark's next open). Do **not** raise effort or revert
the model; the replay proves neither is the cause.

---

### AI238-02 — Nothing in the system inspects generated output (High)

**What is wrong.** The test suite is a prompt-integrity suite, not an output
suite. It proves rules are stated (`test_brief_chat_prompt_policy.py:268-270`,
`test_fact_basis.py`, `test_batch230_reconcilable_figures.py`) and packets are
assembled correctly (`test_morning_analysis.py:390-398`). No test, and no
runtime check, ever looks at what came back.

**Where.** `tests/test_morning_analysis.py:1598` is the single clearest
instance. At runtime: `anthropic_text.py:326-328` (empty-string check) and
`:309-311` (`max_tokens` check) are the entire output contract.

**Failure scenario.** It already happened, on 2026-09-01, and it is the reason
this pass exists. A 57% length collapse and the deletion of two sections
produced: 1,094 green backend tests, a `brief_ready_push` at 08:25:21, a stored
`analyses` row with `stop_reason: end_turn`, and no signal of any kind. The same
blindness covers a refusal-shaped answer, a truncated section, and a brief that
silently stops mentioning a Red.

**Fix shape.** Two cheap layers, neither of which needs an LLM judge.
(1) A deterministic post-generation assertion on the morning path: for each
packet key that has a required section, assert a matching heading or marker is
present in `output_markdown`; record a `brief_completeness` counter and log at
`warning` when it drops. (2) A stored-artifact regression check in closeout —
compare the new brief's section set and char count against the trailing median
and flag a >40% deviation. Both are pure functions over data already persisted.

---

### AI238-03 — The two daily paths alert only on `billing`, and the alert is dormant (High)

**What is wrong.** There are two different alerting policies for the same class
of failure, and the narrow one governs the paths Mark uses every day.

- **Broad (correct):** `scheduler.py:236-243` (longitudinal) and
  `scheduler.py:603-621` (weekly review) call
  `notify_admin_generation_failure(reason=…)` for **any** `AnthropicApiError`.
- **Narrow:** `routers/daily_loop.py:261-265` (morning brief),
  `daily_loop.py:1688-1691` (post-workout), `routers/brief_chat.py:144` and
  `routers/coach_chat.py:102` all gate on `if reason == "billing"`.

Consequences, given `classify_anthropic_error` (`anthropic_text.py:109-141`):
a spend-cap rejection (HTTP 400 `invalid_request_error`, "You have reached your
specified API usage limits" → `invalid_request`), a read timeout (`other`, and
see AI238-04), a 429, a 529 and an auth failure **all** produce a failure card
for Mark and silence for the operator.

**And the billing case is dormant anyway.** `notify_admin_generation_failure`
(`nudge_alerts.py:703-713`) always emits `log.error("brief_generation_admin_alert")`
and then returns `False` unless `settings.admin_alert_user_id` is set.
`ADMIN_ALERT_USER_ID` is **not** in the Railway `api` service's variable list.
So in production the entire Batch 141 alert reduces to one structured log line
with nothing wired to it.

**Failure scenario.** This is the 2026-07-21 credit freeze and the 2026-08-30
timeout outage, both of which are still reachable exactly as they occurred. On
2026-08-31 the spend cap was tripped *during verification* and produced no
alert — recorded in STATUS as a gotcha, deliberately not fixed.

**Fix shape.** Three independent changes, all small. (1) Alert on every
`AnthropicApiError` reason on the daily paths, matching the scheduler. (2) Add
the spend-cap wording to the `billing` branch of `classify_anthropic_error`
(match `"usage limit"` alongside `"credit balance"`, keeping the `etype`
check first). (3) Set `ADMIN_ALERT_USER_ID` in Railway, or accept the log-only
posture explicitly and wire a Railway log alert to
`brief_generation_admin_alert` — but decide, rather than leaving both halves
half-built.

---

### AI238-04 — Transport failures bypass classification; nothing retries (High)

**Still open, unchanged, and now the oldest AI-layer defect in the repo.**
`docs/claude-api-review.md` F1/F2, carried forward as ledger item 234.7 and
named again in Batch 232's "Next" block.

**Where.** `anthropic_text.py:298-303` — a single `client.post` inside `async
with httpx.AsyncClient(...)`, with `except httpx.HTTPStatusError` only.
`grep -rn "TimeoutException\|ReadTimeout\|ConnectError\|RequestError" src/ tests/`
returns no handler and no test; the only hits are comments and the unrelated
`TerminalBatchRequestError`. `main.py:115` registers exactly one exception
handler (`RateLimitExceeded`), so nothing catches the escape app-wide.

**Failure scenario.** Precisely 2026-08-30: seven `httpx.ReadTimeout`s between
08:59 and 09:23, every one classified `other`, every one a retryable failure
card that failed again on retry, and no alert. Batch 234 raised the read budget
so the immediate cause is gone; the illegibility is not. On the chat path the
same exception escapes to a bare `500` with a plain-text body the web client
cannot parse — the regression Batch 143 was written to close.

Separately: still no retry anywhere. `_RETRYABLE_ANTHROPIC_REASONS`
(`anthropic_text.py:148`) only chooses which sentence Mark sees. A single 529 at
06:40 costs the whole morning until the 11:00 backstop.

**Fix shape.** As `claude-api-review.md` §7 already specifies: catch
`httpx.TimeoutException` and `httpx.RequestError` at `anthropic_text.py:298` and
raise `AnthropicApiError(reason="timeout")`; add three attempts with exponential
backoff for `rate_limit` / `overloaded` / `server_error` / `timeout` only; add a
test that raises a real `ReadTimeout` from a stubbed transport. One change to
one function closes it in all nine callers.

---

### AI238-05 — Adaptive thinking is an unmonitored variable the budgets rest on (Medium)

**What is wrong.** Decision #312 sized three coupled numbers —
`anthropic_max_tokens = 24576`, `anthropic_read_timeout_seconds = 550`, and the
derived `670s` lease — from a thinking profile measured once. Production has
now produced the *other* profile three times out of three. Both are legitimate
adaptive outcomes; the app has no idea which one it is getting on any given day
and no alert if the answer changes.

**Where.** `config.py:129` / `:164-165` / `:193`; `anthropic_text.py:178-207`
logs `thinking_tokens` and nothing consumes the log.

**Measured range on real morning packets at the shipped `adaptive`/`medium`:**
3,801 thinking tokens (08-31 packet, replay) and 0 (09-01 packet, production).
Output tokens 5,490 vs 1,360 — a ~4× swing in the dominant cost line, and a
61.7s vs ~15s swing in wall-clock, both invisible.

**Failure scenario.** Two directions. Cost: a run of thinking-heavy packets
quadruples the paid-generation line with no signal. Correctness: the reverse —
if adaptive settles into declining to think on the morning prompt (as three
consecutive production calls suggest), the app is paying `medium`, receiving
`low`, and Decision #312's stated benefit ("`medium` buys adaptive thinking for
roughly what the app already pays") is not being delivered. Nobody would know.

**Fix shape.** Persist `thinking_tokens` as a first-class column or a stable
`raw_response` field the closeout already reads, and add it to the daily-loop
smoke output. Then a two-line check: log at `warning` when a morning generation
returns `thinking_tokens == 0`, because on this prompt that means the app is
running at `low` under a `medium` label.

**A second, cheaper reading of the same evidence.** The 18,044-character morning
prompt is almost entirely a rendering specification — "when X, say Y, in these
words, never softening Z". A model reasonably reads that as template-filling
rather than reasoning, which is a plausible mechanism for adaptive declining.
If AI238-01's fix shortens and structures the prompt, re-measure thinking
afterwards; the two are coupled.

---

### AI238-06 — One honesty rule, eight hand-written copies (Medium)

**What is wrong.** Batch 230 named the defect class precisely — "two prompts
each paraphrased one rule" — and closed one instance with a shared
`REM_FRAMING_RULE` constant embedded verbatim in both, pinned by a test against
the string. The sweep this pass ran found the class alive at eight-way scale on
the rule most central to the app's honesty posture.

**Where.** The `recorded_data_honesty` paragraph ("Treat every figure in the
supplied context as what the app recorded, not as independently verified
truth…") is a separate hand-written literal in **eight** modules:
`morning_analysis.py:221`, `post_workout_analysis.py:118`,
`post_walk_analysis.py:83`, `post_strength_analysis.py:101`,
`post_flexibility_analysis.py:81`, `reviews.py:106`, `trends.py:118`,
`handover.py:104`. A ninth, shorter paraphrase is the `Floor.sentence` at
`coach_policy.py:~200` that `brief_chat` composes via `floors_sentence()`.

All eight are byte-identical **today** (verified by hashing the normalised
paragraph out of each rendered prompt). Nothing keeps them that way. The audit
that exists — `missing_floors()` at `coach_policy.py:317-325` — matches a
*regex*, so a divergent paraphrase that still contains the pattern passes.

The class has already realised once more since Batch 230, in the fix Batch 230
itself shipped: "Packet field names are instructions to you, never words for
Mark" exists as two near-copies (`morning_analysis.py:~296` and
`trends.py:~130`) that differ in punctuation and in the trends copy naming two
field paths as examples — inside a rule forbidding field names. Neither is the
`NO_PLUMBING_RULE` constant (`coach_policy.py:331`), which states the same idea
in entirely different words for chat. **Three wordings, one rule.**

Also unaudited: "Never mention left/right power balance" appears in four prompts
(morning, post_workout, reviews, trends) but `READ_PROMPT_FLOORS` lists
`no_power_balance` for only the first two, so dropping it from reviews or trends
would be silent.

**Failure scenario.** Batch 230's own: two surfaces, same day, same data,
contradicting each other because one paraphrase drifted. The regex audit would
not have caught it then and would not catch it now.

**Fix shape.** Promote `recorded_data_honesty` and the field-name rule to shared
constants in `coach_policy.py`, interpolate them, and add the Batch 230 test
shape — `assert CONSTANT in prompt` for every surface that owns the floor,
alongside the existing regex check rather than instead of it. Add
`no_power_balance` to the `reviews` and `trends` floor lists.

---

### AI238-07 — The ninth generation path escapes the audit that claims it cannot (Medium)

**What is wrong.** `PROMPT_FLOOR_AUDIT_EXEMPTIONS`'s docstring says "the
discovery test requires every other caller to appear in `READ_PROMPT_FLOORS`, so
adding a caller cannot silently skip the audit"
(`coach_policy.py:359-362`). The discovery is an AST walk over
`src/services/*.py` looking for calls named `generate_anthropic_text` or
`AnthropicReviewClient` (`tests/test_brief_chat_prompt_policy.py:65`).
`longitudinal_analysis.py` calls neither — it goes through
`AnthropicMessageBatchClient` — so it is invisible to the discovery, absent from
both `READ_PROMPT_FLOORS` and the exemptions, and its `SYSTEM_PROMPT` is audited
for nothing.

**Where.** `tests/test_brief_chat_prompt_policy.py:65`;
`services/longitudinal_analysis.py:960` (`provider.submit`).

**Failure scenario.** The longitudinal prompt's output routes into experiments
and the knowledge base — coaching state, not prose — so a drifted rule there
propagates into surfaces that *are* audited, laundered through data. The claim
in the docstring is the risk: a future session reads it and trusts a guarantee
that has a hole in it.

**Fix shape.** Add `AnthropicMessageBatchClient` (and `.submit`) to
`model_boundaries`, then list `longitudinal_analysis` in `READ_PROMPT_FLOORS`
with the floors it owns, or in the exemptions with a reason. One line plus a
decision.

---

### AI238-08 — The deepest AI path has never run in production (Medium)

**Proved.** `coach.job_runs` for `longitudinal-analysis`: **0 succeeded, 7
skipped, 1 failed**, every skip with `reason: "admin_billing_alert_not_ready"`
and `counters: {alert_gated: 1, submitted: 0, findings_routed: 0}`. Most recent
2026-09-01 11:15. `coach.analyses` holds no row of that type. Batch 220's
monthly whole-history analysis has produced nothing, ever.

**Where.** `longitudinal_analysis.py:917-919` — `submit_monthly` raises
`BillingAlertNotReady` unless `billing_alert_readiness()` passes, which requires
`settings.admin_alert_user_id` to be set and that profile to hold an active push
subscription (`longitudinal_analysis.py:680-686`). `ADMIN_ALERT_USER_ID` is
unset in Railway (see AI238-03), so the gate can never open.

**Failure scenario.** The gate is defensible — do not spend on a batch you
cannot be alerted about — but it degrades to permanent silence. `scheduler.py:228-235`
logs a `warning` and the job reports `skipped`, which reads as normal in any
dashboard. A feature that shipped, was verified, and has never executed looks
identical to one that runs cleanly.

**Fix shape.** Either set `ADMIN_ALERT_USER_ID` (which also fixes half of
AI238-03) or make the gate loud: after N consecutive `alert_gated` skips, report
`degraded` rather than `skipped`, so an ops view distinguishes "nothing to do"
from "structurally blocked".

---

### AI238-09 — The highest-volume paid path records nothing (Medium)

**What is wrong.** `AnthropicBriefChatClient.generate` returns
`result.output_markdown` and drops `result.raw_response`
(`brief_chat.py:208-219`), so no chat turn's usage is ever stored.

**Why it matters more than F6 said.** Over the 30 days to 2026-09-01, stored
`analyses` account for **87 paid generations, 1,107,246 input and 133,101 output
tokens** (≈$5.32/month at Sonnet 4.6 rates). Over the same window
`coach.brief_messages` holds **104 assistant turns** — *more calls than every
recorded path combined* — each carrying a cached prefix containing the whole
morning brief and its packet (~25–30k tokens). If the cache is working that is
~$0.6/month; if it is not, ~$6/month, which would roughly double the bill. **The
data to tell the two apart is generated on every call and thrown away.**

This also makes §4 of `claude-api-review.md` unfalsifiable in production: the
one call site that applies `cache_control` (`brief_chat.py:558`, correctly
placed — stable prefix before the breakpoint, volatile `app_state` after) is the
one call site whose `cache_read_input_tokens` nobody can read. Across all 87
stored generations, `cache_read` and `cache_creation` are **0**, which is
expected and correct for once-daily calls and says nothing about chat.

**Fix shape.** Return the `AnthropicTextResult` from `generate` and persist
`usage` on the assistant `brief_messages` row (or a small `chat_usage` table).
Then read `cache_read_input_tokens` once and settle the caching question with a
measurement instead of an argument.

---

### AI238-10 — Two JSON-extraction strategies; the fragile one writes memory (Medium)

**What is wrong.** `longitudinal_analysis.build_message_params`
(`longitudinal_analysis.py:475-485`) uses the API's own structured-output
contract — `output_config.format` with a `json_schema` — and merges `effort`
beside it correctly. `conversation_learning` asks for "Return strict JSON only"
in prose (`conversation_learning.py:70`) and then hand-rolls markdown-fence
stripping plus `json.loads` (`:352-366`), raising
`ConversationLearningError("…returned invalid JSON")` on any deviation.

**Failure scenario.** `conversation_learning` is the path that proposes durable
additions to Mark's `learned_context` — the app's persistent memory. A model
that opens with one sentence of preamble before the JSON (more likely, not less,
with thinking on and a prompt that does not use the schema mechanism) fails the
whole extraction. It fails safe (nothing is written) but silently, and the
proposal queue simply stays empty.

**Fix shape.** Move `conversation_learning` onto `output_config.format` with the
same `anthropic_output_schema()` treatment `longitudinal_analysis` already
proves works, and keep the fence-stripping as a fallback rather than the
mechanism.

---

### AI238-11 — `BriefChatError` is uncaught, and the chat ceiling is unmeasured (Medium)

**What is wrong.** `anthropic_text.py:310-311` raises the caller's `error_cls`
on `stop_reason == "max_tokens"`; for chat that is `BriefChatError`, a bare
`Exception` subclass. Neither `routers/brief_chat.py:135-150` nor
`routers/coach_chat.py:92-109` catches it — both catch only `AnthropicApiError`
— and `main.py` has no app-wide handler. So a too-long answer is billed in full,
discarded, and surfaces as the same unparseable bare 500 as AI238-04.

The exposure grew in Batch 233. `anthropic_chat_max_tokens = 4096`
(`config.py:142`) is now shared between adaptive thinking and the reply, and
`config.py:135-141` says plainly that it "was never measured on a real chat
turn" — comfortable at `medium`, plausibly truncating at `high`. Raising
`anthropic_effort` is documented as a free dial everywhere except here.

**Fix shape.** Catch `BriefChatError` in both routers and map it through
`anthropic_http_status`/`anthropic_user_message` like the classified errors;
measure one real chat turn's `output_tokens_details.thinking_tokens` before any
effort change (AI238-05's persistence makes this free).

---

### AI238-12 — Two `basis` strings for one fact, and the model quoted the wrong one (Medium)

**What is wrong.** The 2026-09-01 packet describes the sleep-stage denominator
twice, with different registers:

- `ageComparison.sleepStagePctBasis` — a sentence, exactly what Batch 217's
  "a basis is a sentence or it is nothing" convention asks for:
  *"Stage percentages are shares of measured sleep — deep + light + REM + awake
  — so they include time awake in bed. Garmin's displayed Duration excludes it,
  so its minutes and these percentages do not divide into each other."*
- `metricsVsBaselines[metricKey=rem_sleep_pct].basis` — a fragment:
  *"% of measured sleep — deep + light + REM + awake"*.

The 09-01 brief rendered the fragment: *"REM: 34 minutes, 7.0% of measured sleep
(deep+light+REM+awake)"*, and only on the REM bullet — the Deep bullet gives a
percentage with no basis at all. Batch 230 shipped the explicit denominator
sentence to close a factual error; on Sonnet 5 it degrades to a parenthetical
that reads like field names, on the surface the "never print a field, key or
path" rule governs (AI238-06).

**Where.** `services/age_norms.py` (`SLEEP_STAGE_PCT_BASIS` /
`SLEEP_STAGE_PCT_BASIS_NOTE` / `REM_PCT_BASIS`), reaching the packet at
`morning_analysis._age_comparison` and `_metrics_vs_baselines`.

**Fix shape.** Make the two `basis` strings one string — the sentence — so the
model cannot pick the terser one, and pin it with the Batch 230 test shape.
Then re-state in the prompt that the basis is required on *every* stage
percentage, not once per read.

---

### AI238-13 — Prompt-version → regeneration is three contracts, not one (Medium)

**What is wrong.** Nineteen `PROMPT_VERSION` constants across `src/services`
share a name and behave three different ways on a bump:

| behaviour | paths | consequence of a bump |
|---|---|---|
| **self-heal** — regenerate on mismatch | `morning_analysis`, `post_workout`, `post_walk`, `post_strength`, `post_flexibility` (`post_workout_analysis.py:598-605`), `insights` | correct |
| **blank** — lookup filters on version | `trends` (`trends.py:735`) | the Trends page renders `null` until someone manually regenerates |
| **stale** — lookup does not filter | `reviews` (`reviews.py:779-786`) | an old-prompt narrative is served as current |

Seven of the nineteen are on **deterministic, non-model paths**
(`nudge_alerts`, `experiment_tracker`, `experiment_loop`,
`experiment_evaluation`, `executable_coaching`, `state_change_coach`,
`weekly_restructure`, `wake_detection`) where the name implies an LLM prompt
that does not exist.

**Failure scenario.** Observed already: Batch 230's closeout found both trend
buckets rendering blank after a bump and had to regenerate them twice. The
guard is a manual checklist item (`closeout.md` step 10), not code. The stale
case is live now — the only `monthly_review` in the database was generated
2026-07-05 on `reviews-v3-2026-07-05` while the code is on
`reviews-v7-2026-08-05`, and nothing scheduled ever generates a monthly review
(`POST /api/v1/reviews/monthly/run` is the only trigger).

**Fix shape.** Write down the contract — a table in `ARCHITECTURE.md` naming
each artifact's regeneration behaviour — and add a test that every
`PROMPT_VERSION` on a model-calling module resolves to exactly one of the three,
declared. Then decide `trends` deliberately: either self-heal it like the
morning path, or keep the version filter and add a closeout-executable orphan
check rather than a checklist line.

---

### AI238-14 — Age bands are composed by the model from five raw numbers (Low)

`ageComparison.sleepRows[]` carries `bandLow: 12`, `bandHigh: 20`,
`ageAverage: 16`, `garminTargetLow: 16`, `garminTargetHigh: 33` for Deep — five
numbers, two of which are `16`. In the 08-31 replay the model wrote *"below the
healthy 50–59 band (16–20%)"*, narrowing a 12–20% healthy range by picking the
wrong pair. The stored 4.6 brief for the same packet got it right ("12–20%, age
average 16%").

`observed` — one generation in a read-only replay, not a production brief, so
this is a data point rather than a pattern. But it is the same shape as Batch
230's original defect (the 08-27 brief misattributing a band), on the same
content, one prompt version later.

**Fix shape.** Render the band as a string in the packet
(`"healthyBandLabel": "12–20%"`) the way `descriptor` already is, so composing
it is not a modelling task. Cheap, and it removes a whole class.

---

### AI238-15 — A second, unwired copy of a shipped rule (Low)

`NO_INVENTED_DERIVATION_RULE` (`coach_policy.py:574`) is referenced by nothing
except `tests/test_fact_basis.py`. A full-repo grep returns six hits: the
definition, a docstring cross-reference, and four test lines. The rule's content
does ship — via `Floor(key="no_invented_derivation")` and `floors_sentence()`
for chat, and via a hand-written paraphrase in the morning prompt — so nothing
is missing from any surface. But the constant reads like the live wording and is
not, which is the same trap as AI238-06 in miniature: a future session editing
it would change nothing and believe otherwise.

**Fix shape.** Delete it, or make the Floor's `sentence` reference it so there
is one string.

---

### AI238-16 — Over-broad classification rules; the batch path hardcodes 400 (Low)

`classify_anthropic_error` (`anthropic_text.py:122-127`) matches `"billing" in
message` against the whole message, so any error mentioning billing raises the
credit alert; `"max_tokens" in message` (`:135`) conflates an over-long input
with an invalid argument. Both carried over from F8 unchanged.

New this pass: `longitudinal_analysis.py:641-644` calls
`classify_anthropic_error(400, …)` with a **hardcoded** status for every errored
batch result, so a rate-limit or overload inside a batch can only classify
correctly if `error.type` happens to carry it — and never reaches
`status_code == 429` / `>= 500`.

---

### AI238-17 — The effort decision was a percentage, and the measurement is unreproducible (Low)

**Two things worth restating with the current numbers.**

*Pricing, re-verified live on 2026-09-01* (the day it mattered): Sonnet 5 is
**$2 / $10 per MTok as the standard price**; the platform pricing page states
that the increase to $3/$15 scheduled for 2026-09-01 "will not occur". Sonnet
4.6 is $3/$15. `DECISIONS.md` #308 and Batch 233 were right; the struck
paragraph in `docs/claude-api-review.md` remains correctly struck. No action.

*Absolute cost.* Thirty days of stored generations is **$5.32/month** at 4.6
rates and will be lower on Sonnet 5 (33% cheaper per token, shorter output,
against a ~1.3× tokenizer) — call it ~$4. Batch 233 declined `high` effort on
"+126% versus +11%". In absolute terms the morning path is **~$0.21 vs ~$0.11
per run — about $37 a year** — against an open, named product question about
whether the brief is good enough. That is an unusually cheap experiment to have
declined on a percentage. Not a recommendation to raise effort; a recommendation
to re-decide it in pounds once AI238-01 is fixed, since the prompt fix changes
the thing effort would have been buying.

*Reproducibility.* The sweep that produced the 16,157 / 5,280 / 1,317 figures —
the sole basis for `anthropic_max_tokens = 24576`, `anthropic_read_timeout_seconds
= 550` and the 670s lease — was run from a script that was never committed.
`scripts/compare_model_prose.py` exists but does one run at current settings, not
a sweep. This pass reproduced the `medium` number (5,490 vs 5,280) only by
writing a throwaway. Fold an `--effort` sweep into `compare_model_prose.py` so
the numbers three config constants depend on can be re-measured on demand.

---

## §6 — Re-verification of `docs/claude-api-review.md` F1–F9

All nine re-checked against `2178381`. **None is closed.**

| F | Status | Note |
|---|---|---|
| F1 | **open** | `anthropic_text.py:298-303` — still one `client.post`, no attempt loop. Folded into AI238-04 |
| F2 | **open** | No `TimeoutException`/`RequestError` handler anywhere; `main.py:115` still the only exception handler. This is ledger item 234.7. AI238-04 |
| F3 | **open, worse** | `BriefChatError` still uncaught in both chat routers; the ceiling now shares its budget with thinking. AI238-11 |
| F4 | **open** | `morning_analysis.py:1275-1279` still sends `userId`, `latitude`, `longitude`; `post_workout_analysis.py:493` sends `userId`. No prompt reads any of them |
| F5 | **open** | `context_packet` still an unread parameter on the `generate()` clients (`morning_analysis.py:438,463` + 5 more) |
| F6 | **open, upgraded to Medium** | AI238-09 — now quantified: chat is more calls than every recorded path combined |
| F7 | **open** | `async with httpx.AsyncClient(...)` per call at `anthropic_text.py:298`; no shared client |
| F8 | **open, extended** | AI238-16 — plus the spend-cap gap in AI238-03 and the hardcoded 400 in the batch path |
| F9 | **open** | `workload_budget.py:25-26` still module-level `defaultdict`s |

**§4 (caching — "no finding") re-examined on 2026 numbers and largely upheld,
with one correction.** Across 87 stored generations in 30 days,
`cache_read_input_tokens` and `cache_creation_input_tokens` are 0 on every row.
That is *correct*: a once-daily call cannot hit a 5-minute cache, and even the
1-hour TTL (2× write, 0.1× read — pays back after two reads) does not survive
24 hours. The ~29k input tokens re-sent daily are genuinely not cacheable across
days. The correction is that the conclusion is now **unverifiable where it
matters**: §4 rests on chat being the case that benefits, and chat's usage is
discarded (AI238-09). Fix that first, then re-open the question with a number.

---

## §7 — What is done well, and must survive the fixes

1. **The verdict is computed before the model is called and persisted from the
   packet.** `morning_analysis.py:928` reads
   `context_packet["verdict"]["status"]`; the response supplies
   `output_markdown` and `raw_response` only. Re-verified this pass. Everything
   in Lead #1 — a 57% output collapse, two deleted sections, a model swap — left
   the verdict correct, because the model never had it. **This is the single
   most valuable property in the codebase.** Any fix to AI238-01 must not
   introduce a section the model is asked to *decide* rather than narrate.
2. **The boundary's purity.** `thinking` and `output_config` are absent from the
   payload unless passed (`anthropic_text.py:289-292`), so the no-argument path
   is byte-identical to the pre-233 request and the rollback is a settings
   change, not a code change. Pinned by a test. Keep this shape when adding
   retries — a retry wrapper must not start injecting defaults.
3. **The `type == "text"` filter** (`anthropic_text.py:318-325`) means thinking
   blocks can never be concatenated into Mark's prose. The comment says it is
   "safe by accident rather than by design"; it is now pinned by a test, which
   makes it design.
4. **The Floor registry with AST-discovered surfaces**
   (`coach_policy.py:FLOORS` + `tests/test_brief_chat_prompt_policy.py:61-75`)
   is a genuinely good idea: prompts are discovered from their model-boundary
   calls rather than listed, and every floor carries a `negative_control` that
   must *fail* its own pattern. AI238-06 and AI238-07 are about widening it, not
   replacing it.
5. **The packet contract.** Deterministic assembly, `sort_keys=True`
   serialisation, `basis` sentences alongside figures, `unavailableReason`
   instead of silence, and `_packet_without_stored_system_prompt`
   (`brief_chat.py:606-615`) replacing stored prompt text with a hash so chat
   cannot re-ingest instructions as data. The prompt-injection hygiene is better
   than the threat model requires.
6. **The Batch API path** pre-counts with `count_tokens` and enforces
   `MAX_INPUT_TOKENS` before spending a penny (`longitudinal_analysis.py:960-967`),
   and uses `output_config.format` json_schema properly. It is the best-built
   path in the layer — which makes AI238-08 (it has never run) the sadder
   finding.
7. **`.env.example`** documents the values production actually uses, with the
   reasoning, including why `ANTHROPIC_MAX_TOKENS=1600` was wrong. Rare and
   worth keeping.

---

## §8 — What this pass spent

**$0.118, all on Anthropic, all read-only.** Two probes, both writing nothing to
the database:

| probe | model | input | output | cost |
|---|---|---:|---:|---:|
| effort wiring (synthetic ~166-token prompt, `medium` + `high`) | `claude-sonnet-5` | 332 | 935 | ~$0.010 |
| 2026-08-31 morning packet replay at shipped settings | `claude-sonnet-5` | 26,474 | 5,490 | ~$0.108 |

At the live-verified $2/$10 per MTok. The replay doubles as the Batch 233.8
prose comparison that was blocked by the spend cap: same stored packet, only the
model and generation settings moved. Its two artifacts are in the session
scratchpad, not the repo.

Everything else was free: stored `coach.analyses` and `coach.job_runs` reads
(all column- or JSON-path-projected, no bare `select *`, no JSONB payload
fetched that was not read — one `context_packet` per probe), `railway variables`,
`/api/v1/health`, and a WebFetch of the live pricing page.

---

## The three highest-value fixes

1. **Re-baseline the morning brief's output contract (AI238-01).** One sentence
   at `morning_analysis.py:229` is deleting the user-visible output of half a
   dozen shipped batches. The replay proves it is the prompt and not the model,
   the effort, or the packet, so the fix is one prompt edit plus a version bump
   that self-heals on Mark's next open. Nothing else in this document returns
   more per line changed.

2. **Give the system one way to see its own output (AI238-02).** A deterministic
   section-presence assertion on the morning path plus a length-deviation check
   in closeout. Without it, fix #1 is a fix that can silently un-fix itself on
   the next model, prompt or provider change — which is exactly what happened
   this time. Cheap, needs no LLM judge, and turns the next regression from
   "someone read it and noticed" into a log line.

3. **Close the failure loop at the boundary and at the alert (AI238-04 +
   AI238-03).** Catch `httpx.TimeoutException`/`RequestError` and convert to
   `AnthropicApiError(reason="timeout")`; add three backoff attempts for the
   reasons already called retryable; alert the operator on **every** reason on
   the daily paths, not just `billing`; add the spend-cap wording to the
   `billing` branch; and either set `ADMIN_ALERT_USER_ID` or wire a log alert
   and say so. Two production outages (2026-07-21, 2026-08-30) are still
   reachable exactly as they occurred, and a third — the 2026-08-31 spend cap —
   was observed silently during Batch 233's own verification.
