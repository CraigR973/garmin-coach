# Batch 345 release contract — draft, 16 Oct

Craig approved a no-cost engineering pass. This contract does not approve Mark-facing words,
Anthropic spend, a merge or a production deploy.

## Factual gate

Case 10 asks about a claimed change in Garmin's HRV floor. The relevant wake rows, already
recorded by the 19 Sep question, show 45 ms through 17 Sep and 46 ms on 18–19 Sep. The
draft now adds a small, dated comparison to the chat context only for an explicit HRV-floor
challenge. It reads this profile's rows from the preceding eight dates, prefers the wake
observation, and excludes rows recorded, inserted or updated after the question. The 19 Sep
read-only production replay yields **45 → 46 ms, rose, 17 → 18 Sep** with no model call.
It does not add a new training rule or treat a floor change as proof of a bodily change.

The single authorised paid case-10 retest on 16 Oct answered whether today's cut
stands before correcting the figure, stated the 45 → 46 ms direction correctly,
and kept the computed easing. It was 108 words, with no banned terms, and cost an
estimated $0.265. The source morning rows show a 45 ms seven-day average on
17–19 Sep, a lower baseline of 45 then 46 ms, and BALANCED then UNBALANCED
status. The read also marks the extra next-week change suppressed by the planned
recovery block. Its pass-on was simulated, not delivered to Sentry.

## Reply-length gate

The last case-11 monitoring answer was 135 words. It answered the request first and covered
three needed points: comparison on request rather than automatic trial monitoring, the
weather/house-heat confounders, and where to record the chosen target. It exceeded the
ledger's approximately 120-word target by 15 words; Mark did not ask for detail.

**Craig's 16 Oct decision:** allow one explicit length exception for case 11's
monitoring reply, provided he approves the final answer's exact Mark-facing words.
The previous 135-word answer is evidence for the choice, not wording sign-off or a
pass for a future model answer. Keep the general approximately 120-word target;
do not extend this exception to other cases or longer case-11 answers without
another review.

The server logs answer length and prohibited terms but does not trim, rewrite or reject a
long answer. Cutting generated text can remove a safety boundary or a promised pass-on;
another model rewrite costs money and could introduce a new factual error. A sample gate
cannot guarantee every future answer's length, so live shape logs remain the follow-up
signal. No runtime length change is proposed in this pass.

## Finite paid gate, later

No further paid calls are authorised now. Craig reported $42.46 of the $45
organisation limit before the case-10 call; the provider total after it is not
verified. The Batch log is $32.362 plus a $0.80 reserve under the $35 cap.
Before another retest, reconcile current provider headroom and agree one fixed
cap with a per-call stop reserve. Use new-only answers. Case 10 passed; run
case 11, then case 6, each with the same stop check. Only then run the other 11,
including both safety probes. The completed older paired comparison remains
directional evidence of relative voice, not a release proof for this changed
prompt; dated source rows decide facts.
The runner's $0.40 allowance per call is a stop estimate based on observed usage, not a
guarantee of provider billing for an unpriced timeout.

## Promotion gate

Reconcile PR #380 with main; keep it draft. Prove `pass_to_craig` reaches Sentry with its
tag in a real controlled test; Craig's email rule is a separate owner action. Craig then
reviews and signs off the actual Mark-facing replies. Full local gates, both CI waves,
the migration check, the permitted London deploy window, exact-SHA production freshness
and read-only smoke checks follow before marking Batch 345 shipped.
