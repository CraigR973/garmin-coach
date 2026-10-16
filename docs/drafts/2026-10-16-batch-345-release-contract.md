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

The later current-candidate case-11 retest was 107 words, so it met the general
target without using that exception. It offered comparison when asked, did not
promise automatic monitoring, told Mark where to note the 18°C target, and
named outdoor temperature and house-heat retention as confounders. It cost an
estimated $0.186. Craig still needs to approve its exact words before merge.

## Holiday-return gate

The current-candidate case-6 retest was 67 words, answered the omission first,
and simulated one `pass_to_craig` call. A read-only source check of the stored
5 Oct morning brief found the holiday note used for sleep-stage and waking
context; the brief did not address Mark's forward-looking request about
training on return. The new answer identified that gap without promising a
training-rule change. It cost an estimated $0.221. No real Sentry alert was
sent, and Craig has not signed off its exact words.

The server logs answer length and prohibited terms but does not trim, rewrite or reject a
long answer. Cutting generated text can remove a safety boundary or a promised pass-on;
another model rewrite costs money and could introduce a new factual error. A sample gate
cannot guarantee every future answer's length, so live shape logs remain the follow-up
signal. No runtime length change is proposed in this pass.

## Finite paid gate, later

No further paid calls are authorised now. Craig reported $42.46 of the $45
organisation limit immediately before cases 11 and 6; the provider total
after their estimated $0.408 cost is not verified and may lag. The Batch log
is $32.770 plus a $0.80 reserve under the $35 cap, leaving $1.430 of effective
room. Cases 10, 11 and 6 pass their targeted gates. The remaining 11 cases,
including both safety probes, have not run on this current candidate. Earlier
answers carry a different prompt hash and cannot be promoted as release proof;
the completed paired comparison remains directional evidence of relative voice.
The earlier 11 new-only answers cost $1.676, an estimate for planning rather
than a price guarantee. At that same cost the $35 Batch cap would stop short,
and the reported $45 organisation limit would leave only about $0.46 after
all 11, assuming no other usage and instant billing. Before another retest,
reconcile provider headroom and agree one fixed cap with a per-call stop
reserve. Run both safety probes first; stop on any failure before the other
nine. Dated source rows decide factual claims.
The runner's $0.40 allowance per call is a stop estimate based on observed usage, not a
guarantee of provider billing for an unpriced timeout.

## Promotion gate

Reconcile PR #380 with main; keep it draft. Prove `pass_to_craig` reaches Sentry with its
tag in a real controlled test; Craig's email rule is a separate owner action. Craig then
reviews and signs off the actual Mark-facing replies. Full local gates, both CI waves,
the migration check, the permitted London deploy window, exact-SHA production freshness
and read-only smoke checks follow before marking Batch 345 shipped.
