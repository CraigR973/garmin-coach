# Batch 326 — the words Mark sees when rides are not reaching Zwift

Drafted 7 Oct 2026 for Craig's sign-off before the merge (outside the G8 delegation).
Tests pin the web's words to this file.

## Today card, a bike session

| When | Line |
|---|---|
| Rides reach Zwift | Already in Zwift, ready to ride. *(unchanged)* |
| The login falls due within 7 days | Already in Zwift, ready to ride. Then, below it: Log in at intervals.icu before Tue 5 Jan to keep your rides reaching Zwift. |
| intervals.icu has paused the account | Not reaching Zwift: intervals.icu has paused your account. Log in at intervals.icu once, then restart Zwift. |
| The Zwift link is lost | Not reaching Zwift: intervals.icu has lost its link to Zwift. Reconnect Zwift in intervals.icu's settings. |
| The app has not been able to check for 24 hours | Sent to intervals.icu. The app can't check that it reached Zwift. |

The date is the day the account would pause: 90 days after the last login. The paused
and lost-link lines head any bike session's card, sent or not, ahead of "The coach adjusted
today's session…": whatever he approves will not arrive until it is fixed. The "can't
check" line shows only on a session already sent; one not yet sent keeps "Not yet in
Zwift.".

## After an action, when rides are not reaching Zwift (any of the last three above)

| Today | Becomes |
|---|---|
| Coach's adjustment uploaded to Zwift | Coach's adjustment sent to intervals.icu |
| Interval change approved and uploaded to Zwift | Interval change approved and sent to intervals.icu |
| Done — today's session is now {change}, and it's in Zwift. | Done — today's session is now {change}, and it's sent to intervals.icu. |
| {Plan} is in your plan, and its rides are on their way to Zwift. | {Plan} is in your plan, and its rides are on their way to intervals.icu. |

The Skip and Remove confirmations use their existing other line ("It will be marked as
skipped." / "It will disappear from your plan."), so they add no words. The buttons keep
"Approve & upload to Zwift" and "Confirm & upload to Zwift": they name the action.

## Not Mark-facing

Craig's admin alert (`delivery_rail`) names the state, the days since the login, the pause
date and the one fix.
