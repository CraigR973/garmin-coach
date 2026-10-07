import { useMutation, useQueryClient } from '@tanstack/react-query';
import { appliedPlanChangeEnvelopeSchema, type CoachPlanChange } from '@coach/shared';
import { Check, ClipboardList } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { apiFetch } from '@/lib/api';
import { APPLIED, APPLY, APPLYING, OFFER_HEADING, SEE_PLAN } from '@/lib/planChanges';

/**
 * Batch 324: a change to his proposed next plan, offered by the coach, applied by his tap.
 *
 * The server checked the change against the plan as it stood when the answer was written,
 * and the tap applies it only if the plan is still at that revision; otherwise the server
 * says why in words, and the card shows them. Applying changes the proposed plan only:
 * nothing goes to Zwift until he accepts the whole plan in the builder.
 */
export function CoachPlanChangeCard({
  messageId,
  change,
}: {
  messageId: string;
  change: CoachPlanChange;
}) {
  const queryClient = useQueryClient();
  const [refusal, setRefusal] = useState<string | null>(null);

  // A refusal (the plan moved on, or was accepted or declined) is an answer, not a failure:
  // the server's words come back as the result and the card shows them.
  const mutation = useMutation({
    mutationFn: async (): Promise<{ applied: boolean; words: string | null }> => {
      try {
        appliedPlanChangeEnvelopeSchema.parse(
          await apiFetch<unknown>(`/api/v1/coach/messages/${messageId}/apply-plan-change`, {
            method: 'POST',
          }),
        );
        return { applied: true, words: null };
      } catch (error) {
        return { applied: false, words: error instanceof Error ? error.message : null };
      }
    },
    onSuccess: (result) => {
      if (!result.applied) setRefusal(result.words);
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['coach-thread'] }),
        queryClient.invalidateQueries({ queryKey: ['block-generator'] }),
        queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
      ]);
    },
  });

  const applied = change.status === 'applied' || mutation.data?.applied === true;
  if (applied) {
    return (
      <p className="mt-2 flex items-start gap-1.5 text-xs text-text-secondary" role="status">
        <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success-text" aria-hidden />
        <span>
          {APPLIED}{' '}
          <Link to="/builder" className="underline underline-offset-2">
            {SEE_PLAN}
          </Link>
        </span>
      </p>
    );
  }

  if (change.status === 'unavailable' || change.status === 'stale' || refusal) {
    const words =
      refusal ?? (change.status === 'unavailable' || change.status === 'stale' ? change.words : null);
    return words ? (
      <p className="mt-2 text-xs text-text-muted" role="note">
        {words}
      </p>
    ) : null;
  }

  return (
    <div className="mt-2 rounded-lg border border-border bg-bg/60 px-3 py-2.5">
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-text-secondary">
        <ClipboardList className="h-3.5 w-3.5" aria-hidden />
        {OFFER_HEADING}
      </p>
      <p className="mt-1.5 text-sm text-text-primary">{change.summary}</p>
      <Button
        type="button"
        size="sm"
        className="mt-2.5 w-full sm:w-auto"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? APPLYING : APPLY}
      </Button>
    </div>
  );
}
