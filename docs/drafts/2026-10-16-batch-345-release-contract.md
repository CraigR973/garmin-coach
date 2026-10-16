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

This is an input repair, not proof of the next model answer. A paid case-10 retest must
answer whether the cut is justified before correcting the figure, state the 45 → 46 ms
direction correctly, and hold the computed call. A failure stops the evaluation.

## Reply-length gate

The last case-11 monitoring answer was 135 words. It answered the request first and covered
three needed points: comparison on request rather than automatic trial monitoring, the
weather/house-heat confounders, and where to record the chosen target. It exceeded the
ledger's approximately 120-word target by 15 words; Mark did not ask for detail.

**Recommendation for Craig's wording review:** consider this one answer as an explicit
exception if its full wording reads well on a phone. Do not silently raise the general
target or count it as passing before Craig decides. If Craig rejects the exception, revise
the response guidance and retest it within the separately approved fixed budget.

The server logs answer length and prohibited terms but does not trim, rewrite or reject a
long answer. Cutting generated text can remove a safety boundary or a promised pass-on;
another model rewrite costs money and could introduce a new factual error. A sample gate
cannot guarantee every future answer's length, so live shape logs remain the follow-up
signal. No runtime length change is proposed in this pass.

## Finite paid gate, later

No paid calls are authorised now. Before a retest, reconcile the provider bill and current
organisation headroom; state one new Batch cap and a per-call stop reserve. Use new-only
answers. Run case 10 alone and inspect its dated claim before another call; then
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
