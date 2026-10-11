# Batch 334: plan protection words for Craig's sign-off

**Status: proposed, not signed off.** Craig's sign-off is required before the merge.
Existing signed-off Plan No. 3 words remain in the 7 Oct Batch 323 and 324 drafts.

## Plan No. 3

| Place | Words |
|---|---|
| Why this plan | This proposal uses 30/30s then 30/15s for VO₂, rather than the longer 2–3-minute progression you wrote on 28 Aug. It follows the app's existing VO₂ protocol table; it has not compared the two approaches for you. Talk it through or change the sessions before accepting. |
| Interval edit summary | The whole session has 20 min above 106% FTP. *(The number is calculated from every set and ramp.)* |
| Live editor and coach change before upload | The whole session will have 20 min above 106% FTP across all its sets. Approve and upload? *(The number comes from a server preview of the edited ride. Cancel leaves Zwift untouched.)* |
| Dose refusal | That session would have 72 min above 106% FTP across all its sets. The limit is 30 min: Plan No. 3 peaks at 20 min, with a 10 min margin. Shorten the efforts or reduce the sets. *(The two numbers reflect the session.)* |
| Ramp test removed or altered | This change removes or alters the ramp test. Without that test, your next FTP and the ride targets based on it will not be checked in this plan. |
| VO₂ session removed or cut below half its proposed dose | This change removes or greatly reduces a VO₂ session. The plan will have less of the hard work it was built around. |
| Recovery week raised more than 10% above the proposal | This change makes a recovery week heavier. Its lighter load is there to let you recover before the next build weeks. |

The three cautions come from the plan content and appear on hand edits and coach
offers whatever the coach writes. A hand edit shows a caution before saving;
its summary keeps it after saving. The old authenticated `/refine` route has the
same dose refusal and its change summary carries applicable cautions.

## Accept and decline

| Place | Words |
|---|---|
| Accept dialog | As proposed → your plan |
| Under heading | Check the test, VO₂ sessions and recovery weeks before the plan goes to Zwift. |
| Comparison columns | As proposed · Your plan |
| Comparison sections | Ramp test · VO₂ sessions · Recovery weeks · total minutes |
| Missing session | None |
| Actions | Accept your plan · Keep reviewing |
| Comparison unavailable | Could not load the plan comparison. Refresh and try again. |
| Decline dialog | Decline this plan? |
| With two changes | This discards 2 changes you made. Nothing in your current plan changes. |
| With one change | This discards 1 change you made. Nothing in your current plan changes. |
| With no changes | You have no changes to discard. Nothing in your current plan changes. |
| Actions | Decline the plan · Keep the plan |

The accepted comparison also goes to Craig through a tagged Sentry event. The
Sentry email rule remains a separate Craig setup step.

## Home and symptom check-in

| Place | Words |
|---|---|
| A changed live Zwift ride, in place of swap and move offers | The ride on Zwift was already changed today. Moving it could carry that changed ride to another day. |
| Symptom question, on Home and the check-in | Any symptoms since your last check-in, including on a ride? |

The Home guard is a stopgap until Batch 335 repairs movement of a changed live
ride. The symptom change asks about the same four answers and changes no rule
of the daily call.

## Design choices for review

1. **Dose ceiling:** 30 minutes above 106% FTP for a whole bike session. Plan No.
   3's generated peak is 20 minutes; the 10-minute margin permits an edit but
   refuses the 72-minute review example.
2. **Recovery caution:** more than 10% above the proposed recovery week's total,
   including cumulative small edits.
3. **VO₂ caution:** removal or a cut below half of the proposed session's high
   intensity minutes.
4. **Refine route:** preserve the authenticated API and guard it rather than
   retire it, as Craig chose on 11 Oct.
