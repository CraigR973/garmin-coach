# Batch 345 coach voice: one repair, one bounded proof attempt

**Status: Craig approved the no-cost prompt repair on 20 Oct.** Prompt v25 and its regression tests are built in draft PR #380. The paid pass and $43 Batch cap need separate approval; exact Mark-facing wording needs Craig's sign-off before the usual merge and deployment gate.

## Why the current candidate cannot ship

The independent editorial review accepted three of ten unsigned saved answers as examples (cases 4, 6 and 12) and requested revisions to seven (1, 2, 3, 5, 7, 13 and 14). Case 2 turns a Garmin HRV classification change into evidence of recovery; case 5 risks promising an automatic future training adjustment from a read that only offers advice. Mechanical banned-term and word-count checks missed both. Craig already approved the exact source-backed wording for cases 8–10. Case 11 has no current-prompt answer on its frozen pre-question context.

## Proposed repair

Make **one compact edit to the shared coach reply instructions** in the draft PR. Before writing, the coach should identify (1) Mark's actual question, (2) what the dated record proves, (3) what is only a possible explanation, and (4) whether a training change is advice, a proposal awaiting confirmation or an applied change. The final reply should lead with the answer, use one or two decisive facts, acknowledge uncertainty and Mark's own experience, and use ordinary training language. Keep the existing fixed training floors, lookup and pass-on behaviour, source-backed replies and data contract intact. Remove repeated generic reply instructions rather than adding another long layer of rules. Add examples for the two serious failure modes: a changed HRV classification does not establish recovery, and a read's advice does not prove code changed or promise an automatic future adjustment. Clarify that an ambiguous earlier sleep instruction must be owned as unclear, and that a plan swap precedes its fallback recovery spin.

This is a prompt design, not a promise that the model will follow it. The current prompt already contains some of these rules, so the editorial retest must decide whether the shorter, more prominent instruction actually works. Do not hardcode responses to historical questions or use a text-replacement guard to manufacture an apparently passing answer; those cannot safely fix causal inferences or product promises. Do not lower the release criteria or treat a passing word count as editorial approval.

The generic prompt version and hash will change. Chat history is an unfiltered artifact, so this withdraws no stored answers and requires no paid regeneration. The 180-second timeout has already shipped separately.

## No-cost gate before any model call

1. Check the prompt diff against every fixed training floor, tool contract and Mark-facing reply rule. Add focused regression tests for the contract and run the local backend, shared and web gates, then push and PR CI on the exact candidate SHA.
2. Replay cases 8–10 against their saved, read-only source contexts with simulated alerts. Their source-backed paths bypass the model; require their delivered text, selector and alert behaviour to match Craig's approved wording exactly. If any falls back to the model, stop and re-estimate the paid scope before making a call.
3. Validate the frozen fixtures and prompt hashes for the other 11 cases. This is preparation only: no production writes or Anthropic calls.

## Paid proof only after a separate explicit go and sufficient organisation headroom

The last reported organisation position is $49.65 of $50. Wait for a billing-cycle reset rather than raising that limit for this attempt. Check its then-current headroom before any call. The Batch ledger has $37.2765 logged spend plus a $0.80 unpriced reserve; the $40 cap leaves $1.9235 after that reserve, and only $0.8305 remains in Craig's separately approved increment.

The shared prompt change makes **11 model answers** stale: cases 1–7 and 11–14. Cases 8–10 are deterministic and can be rechecked for $0. The 11 corresponding previous calls totalled **$1.555** in estimated provider charges; that is a planning estimate, not a ceiling. The evaluator reserves $0.40 per call, so 11 reservations need $4.40. With the existing unpriced reserve, a **$43 total Batch cap** would accommodate one 11-case pass ($37.2765 + $0.80 + $4.40 = $42.4765). That would raise the current Batch cap by $3. It does not guarantee a provider charge ceiling: tool rounds and provider billing can differ from the estimate. The organisation limit also includes other app traffic.

Run cases 2 and 5 first, one at a time. Read their delivered wording and source grounding after each; stop at the first substantive, safety, length, banned-term, timeout or cost failure. Only if both pass, run the other nine once, checking each before continuing. No automatic rewrite, retry or cap increase after a failure. A passing set still needs Craig's exact wording approval, Sentry inbox receipt, refreshed final CI, merge and exact-SHA production verification. This plan does not guarantee a pass or a release.

## Current gate

The full local gate on 20 Oct passed: 2,274 backend tests (534 expected PostgreSQL skips), Ruff, mypy, 54 shared tests, 604 web tests, shared typecheck, web build and lint (0 errors, 9 standing warnings). The first push and PR CI waves each passed six checks and failed one DB-enabled exact-string safety-floor assertion. Its sentence was restored; code SHA `65c9e9c` then passed all seven checks in both CI waves. The five frozen fixtures (5 and 11–14) validate with the final prompt and unchanged source hashes at $0. Saved source-backed deliveries for cases 8–10 still show Craig's approved 87-, 91- and 109-word answers with zero model calls, and the unchanged source-backed routes pass focused tests. Direct read-only production database queries reconfirmed the dated HRV and proposed ride-minute inputs behind all three saved replies, including the pre-question morning reads. This does not replace a full application evaluator replay, which still needs an application database connection before any paid run. Final wording is still pending.

The paid pass and $43 total Batch cap remain separate decisions after the no-cost gate and organisation reset; there is no implied top-up. If the one pass fails, hold the voice release and decide whether a smaller independently useful feature should ship, using the actual failure as evidence.
