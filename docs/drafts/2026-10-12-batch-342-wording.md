# Batch 342 — wording for Craig's sign-off

**Status: signed off by Craig 12 Oct 2026; shipped in PR #379.** These are the new lines Mark can see. Existing fixed plan-safety refusals remain as written.

| When | Exact wording |
|---|---|
| A read or response cannot load | “We couldn't load this right now. Your saved data is safe. Try again.” |
| A write fails or its outcome cannot be confirmed | “We couldn't confirm that change. Refresh before trying again.” |
| Home: bedroom section cannot parse | “Couldn't load bedroom data” / “Bedroom data couldn't load” |
| Home or Sleep: sleep section cannot parse | “Couldn't load sleep data” / “Sleep data couldn't load” |
| Home or Brief: today's plan cannot parse | “Couldn't load today's plan” / “Today's plan couldn't load” |
| Home or Brief: brief status cannot parse | “Brief status couldn't load” |
| Climate: bedroom section cannot parse | “Climate data couldn't load” |
| Plan builder: draft cannot load | “Plan builder couldn't load” |
| Plan builder: later weeks | “Show weeks 3–13” / “Hide weeks 3–13” |
| Plan builder: interval lasting at least a minute | “Effort (minutes)” / “Recovery (minutes)” |
| Plan builder: shorter interval | Existing “Effort (seconds)” / “Recovery (seconds)” |

The failed-write line deliberately avoids “nothing was changed”: a network failure can occur after the server has committed a change. A specific, fixed 422 plan-safety refusal still explains its bound or reason. All error cards offer the existing **Try again** control.
