import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  intervalEditApproveInputSchema,
  intervalEditPreviewEnvelopeSchema,
  type CoachIntervalChange,
} from '@coach/shared';
import { Check, LockKeyhole } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useZwiftRail } from '@/hooks/useZwiftRail';
import { apiFetch } from '@/lib/api';
import { appliedChangeTail } from '@/lib/zwiftRail';

/**
 * The change a coach answer carries, put in front of Mark where he is standing.
 *
 * Batch 264. The button this replaces said "Propose this adjustment" and called
 * the ordinary propose endpoint, which builds the workout straight from the
 * stored plan row — so on 2026-09-08 the coach offered 2×10 min of 35s/25s and
 * both taps queued the unchanged 40s/20s session. Eight such rows exist across
 * six days, every one unadjusted and expired, and the toast pointed at another
 * screen where he would have found the unchanged session anyway.
 *
 * Two things follow from that and are the whole of this component. The numbers
 * are shown before the tap, not described in prose — the card is the second
 * place the prescription appears, so a wrong number is visible rather than
 * implied. And the outcome lands here: confirming replaces the card with what
 * was applied, so nothing sends him elsewhere to find out whether it worked.
 *
 * The tap previews the whole-session dose before confirming the existing
 * interval-editor approve endpoint. Both the coach card and editor use the
 * same server guard and the same delivery rail.
 */
export function CoachIntervalChangeCard({ change }: { change: CoachIntervalChange }) {
  const queryClient = useQueryClient();
  const zwiftRail = useZwiftRail();
  const [applied, setApplied] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      if (change.status !== 'proposed') return false;
      const body = intervalEditApproveInputSchema.parse({ block: change.changeTo });
      const previewResponse = await apiFetch<unknown>(
        `/api/v1/workout-delivery/planned-workouts/${change.plannedWorkoutId}/interval-editor/preview`,
        { method: 'POST', body: JSON.stringify(body) },
      );
      const preview = intervalEditPreviewEnvelopeSchema.parse(previewResponse);
      const confirmed = window.confirm(
        `The whole session will have ${preview.data.wholeSessionVo2Minutes} min above 106% FTP across all its sets. Approve and upload?`,
      );
      if (!confirmed) return false;
      await apiFetch(
        `/api/v1/workout-delivery/planned-workouts/${change.plannedWorkoutId}/interval-editor/approve`,
        { method: 'POST', body: JSON.stringify(body) },
      );
      return true;
    },
    onSuccess: async (approved) => {
      if (change.status !== 'proposed' || !approved) return;
      setApplied(change.changeToLabel);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
        queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
        queryClient.invalidateQueries({ queryKey: ['workout-delivery'] }),
      ]);
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not make that change'),
  });

  if (change.status === 'unavailable') {
    return (
      <p className="mt-2 text-xs text-text-muted" role="note">
        {UNAVAILABLE_COPY[change.reason]}
      </p>
    );
  }

  if (applied) {
    return (
      <p
        className="mt-2 flex items-start gap-1.5 text-xs text-text-secondary"
        role="status"
      >
        <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success-text" aria-hidden />
        <span>
          Done — today’s session is now {applied}, {appliedChangeTail(zwiftRail)}
        </span>
      </p>
    );
  }

  return (
    <div className="mt-2 rounded-lg border border-border bg-bg/60 px-3 py-2.5">
      <p className="text-xs font-medium uppercase tracking-wide text-text-secondary">
        Change to confirm
      </p>
      <dl className="mt-1.5 space-y-1 text-sm tabular-nums">
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-text-muted">Now</dt>
          <dd className="text-right text-text-secondary line-through">{change.currentLabel}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-text-muted">Change to</dt>
          <dd className="text-right font-medium text-text-primary">{change.changeToLabel}</dd>
        </div>
      </dl>
      {change.matchingSets > 1 ? (
        <p className="mt-1.5 text-xs text-text-secondary">
          Today’s session has {change.matchingSets} matching sets; both change together.
        </p>
      ) : null}
      {change.heldConstant.length > 0 ? (
        <p className="mt-1.5 flex items-start gap-1.5 text-xs text-text-muted">
          <LockKeyhole className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          <span>Unchanged: {change.heldConstant.join(', ')}.</span>
        </p>
      ) : null}
      <Button
        type="button"
        size="sm"
        className="mt-2.5 w-full sm:w-auto"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? 'Uploading…' : 'Confirm & upload to Zwift'}
      </Button>
    </div>
  );
}

/** Plain sentences, never the reason token itself (`NO_PLUMBING_RULE`). */
const UNAVAILABLE_COPY: Record<
  Extract<CoachIntervalChange, { status: 'unavailable' }>['reason'],
  string
> = {
  not_editable: 'There’s no session to change today.',
  unchanged: 'That’s what today’s session already prescribes.',
  out_of_range: 'That change is outside what can be set on today’s session here.',
  malformed: 'That change couldn’t be prepared — ask again and it’ll try afresh.',
};
