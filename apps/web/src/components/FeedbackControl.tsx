import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  feedbackInputSchema,
  type Feedback,
  type FeedbackKind,
  type FeedbackRating,
  type FeedbackReasonTag,
} from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

/**
 * Rate & correct any AI summary (Batch 64, Decision #137).
 *
 * The rating is the doorway; a negative tap reveals an optional "what did we get
 * wrong?" box, and the free-text correction is the payload that feeds the next
 * read forward. Two axes by content type: `summary` rates accuracy, `suggestion`
 * rates agreement. One row per (user, analysis) — every save upserts.
 */

interface RatingOption {
  value: FeedbackRating;
  label: string;
  /** A negative tap reveals the correction box — the correction is the real signal. */
  negative: boolean;
}

const OPTIONS: Record<FeedbackKind, RatingOption[]> = {
  summary: [
    { value: 'spot_on', label: 'Spot on', negative: false },
    { value: 'a_bit_off', label: 'A bit off', negative: true },
    { value: 'way_off', label: 'Way off', negative: true },
  ],
  suggestion: [
    { value: 'agree', label: 'Agree', negative: false },
    { value: 'not_for_me', label: 'Not for me', negative: true },
    { value: 'already_doing', label: 'Already doing', negative: false },
  ],
};

const PROMPT: Record<FeedbackKind, string> = {
  summary: 'Was this right?',
  suggestion: 'How does this land?',
};

interface ReasonTagOption {
  value: FeedbackReasonTag;
  label: string;
}

// One-tap "what's off" reasons, scoped by kind (Batch 118). Shown alongside the
// free-text box on a negative tap, so Mark can say what's off without typing.
const REASON_TAGS: Record<FeedbackKind, ReasonTagOption[]> = {
  summary: [
    { value: 'sleep_read', label: 'Sleep read' },
    { value: 'load_read', label: 'Load read' },
    { value: 'thermal_read', label: 'Thermal read' },
    { value: 'plan_mismatch', label: 'Plan/schedule' },
    { value: 'other', label: 'Other' },
  ],
  suggestion: [
    { value: 'too_cautious', label: 'Too cautious' },
    { value: 'too_aggressive', label: 'Too aggressive' },
    { value: 'bad_timing', label: 'Bad timing' },
    { value: 'not_practical', label: 'Not practical' },
    { value: 'other', label: 'Other' },
  ],
};

function isNegative(kind: FeedbackKind, rating: FeedbackRating | null): boolean {
  if (rating === null) return false;
  return OPTIONS[kind].some((option) => option.value === rating && option.negative);
}

export interface FeedbackControlProps {
  analysisId: string;
  kind: FeedbackKind;
  feedback?: Feedback | null;
  className?: string;
}

export function FeedbackControl({ analysisId, kind, feedback, className }: FeedbackControlProps) {
  const queryClient = useQueryClient();
  const [rating, setRating] = useState<FeedbackRating | null>(
    (feedback?.rating as FeedbackRating | undefined) ?? null,
  );
  const [correction, setCorrection] = useState(feedback?.correctionText ?? '');
  const [reasonTags, setReasonTags] = useState<FeedbackReasonTag[]>(
    (feedback?.reasonTags as FeedbackReasonTag[] | undefined) ?? [],
  );
  const [showCorrection, setShowCorrection] = useState(
    Boolean(feedback?.correctionText) || isNegative(kind, (feedback?.rating as FeedbackRating) ?? null),
  );

  // Keep local state in step when the server payload refreshes (e.g. after a
  // background refetch surfaces feedback saved on another device).
  useEffect(() => {
    setRating((feedback?.rating as FeedbackRating | undefined) ?? null);
    setCorrection(feedback?.correctionText ?? '');
    setReasonTags((feedback?.reasonTags as FeedbackReasonTag[] | undefined) ?? []);
    setShowCorrection(
      Boolean(feedback?.correctionText) ||
        isNegative(kind, (feedback?.rating as FeedbackRating) ?? null),
    );
  }, [feedback?.rating, feedback?.correctionText, feedback?.reasonTags, kind]);

  const mutation = useMutation({
    mutationFn: async (next: {
      rating: FeedbackRating;
      correctionText: string | null;
      reasonTags: FeedbackReasonTag[];
    }) => {
      const payload = feedbackInputSchema.parse({
        kind,
        rating: next.rating,
        correctionText: next.correctionText,
        reasonTags: next.reasonTags,
      });
      await apiFetch(`/api/v1/analyses/${analysisId}/feedback`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    },
    onSuccess: async () => {
      // Every summary widget rides one of these two query trees; invalidate both
      // so the saved rating is reflected wherever the analysis is shown.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
        queryClient.invalidateQueries({ queryKey: ['review'] }),
      ]);
      toast.success('Thanks — noted');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not save your feedback'),
  });

  const options = OPTIONS[kind];
  const reasonOptions = REASON_TAGS[kind];

  function handleRate(next: FeedbackRating) {
    setRating(next);
    const negative = isNegative(kind, next);
    // Switching to a positive rating hides the reason chips; drop any tags
    // picked under a since-abandoned negative tap so they don't ride along.
    const nextReasonTags = negative ? reasonTags : [];
    setReasonTags(nextReasonTags);
    setShowCorrection(negative || correction.trim().length > 0);
    // A rating saves in one tap; any existing correction rides along.
    mutation.mutate({
      rating: next,
      correctionText: correction.trim() || null,
      reasonTags: nextReasonTags,
    });
  }

  function toggleReasonTag(tag: FeedbackReasonTag) {
    if (rating === null) return;
    const next = reasonTags.includes(tag)
      ? reasonTags.filter((value) => value !== tag)
      : [...reasonTags, tag];
    setReasonTags(next);
    // A reason tag saves in one tap, same as the rating itself.
    mutation.mutate({ rating, correctionText: correction.trim() || null, reasonTags: next });
  }

  function handleSaveCorrection() {
    if (rating === null) return;
    mutation.mutate({ rating, correctionText: correction.trim() || null, reasonTags });
  }

  return (
    <div className={cn('space-y-2', className)}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-text-secondary">{PROMPT[kind]}</span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={PROMPT[kind]}>
          {options.map((option) => (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant={rating === option.value ? 'default' : 'outline'}
              aria-pressed={rating === option.value}
              disabled={mutation.isPending}
              onClick={() => handleRate(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {showCorrection ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="What's off?">
            {reasonOptions.map((option) => (
              <Button
                key={option.value}
                type="button"
                size="sm"
                variant={reasonTags.includes(option.value) ? 'default' : 'outline'}
                aria-pressed={reasonTags.includes(option.value)}
                disabled={mutation.isPending}
                onClick={() => toggleReasonTag(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
          <Textarea
            aria-label="What did we get wrong?"
            placeholder="What did we get wrong? (optional)"
            value={correction}
            onChange={(event) => setCorrection(event.target.value)}
            maxLength={2000}
            className="min-h-[64px]"
          />
          <div className="flex justify-end">
            <Button
              type="button"
              size="sm"
              variant="subtle"
              disabled={mutation.isPending || rating === null}
              onClick={handleSaveCorrection}
            >
              Save note
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
