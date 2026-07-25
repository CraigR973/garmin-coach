import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { workoutReadEnvelopeSchema } from '@coach/shared';
import type { planActionWorkoutSchema } from '@coach/shared';
import { Bike, Dumbbell, Wind } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Sheet } from '@/components/ui/sheet';
import { BriefFollowUpChat } from '@/components/BriefFollowUpChat';
import { DetailRow } from '@/components/DetailRow';
import { FeedbackControl } from '@/components/FeedbackControl';
import { Markdown } from '@/components/Markdown';
import { PowerProfilePreview } from '@/components/PowerProfilePreview';
import {
  categoryForWorkoutType,
  isBikeWorkoutType,
  workoutTypeLabel,
} from '@/lib/workoutCategories';
import { describeSegment, expand, parseStructuredWorkout } from '@/lib/structuredWorkout';

type PlanWorkout = typeof planActionWorkoutSchema._type;

type BadgeVariant = 'default' | 'muted' | 'success' | 'accent' | 'error';

function statusBadge(status: string): { label: string; variant: BadgeVariant } {
  if (status === 'completed') return { label: 'Completed', variant: 'success' };
  if (status === 'skipped') return { label: 'Skipped', variant: 'muted' };
  if (status === 'modified') return { label: 'Modified', variant: 'accent' };
  if (status === 'moved') return { label: 'Moved', variant: 'muted' };
  return { label: 'To do', variant: 'accent' };
}

function iconFor(workoutType: string) {
  const category = categoryForWorkoutType(workoutType);
  if (category === 'cycle') return Bike;
  if (category === 'weights') return Dumbbell;
  return Wind;
}

/**
 * Read-only detail for a planned workout, opened by tapping its row on the Week
 * view (Batch 135). It never edits — Move / Edit structure / Skip / Remove stay
 * on the admin editor rows. For a structured bike session it reuses the shared
 * power-profile preview + segment summariser; other sessions show their metadata
 * and an honest "no structured breakdown" line.
 */
export function WorkoutDetailSheet({
  open,
  workout,
  onClose,
}: {
  open: boolean;
  workout: PlanWorkout | null;
  onClose: () => void;
}) {
  const structure = useMemo(() => {
    if (!workout) return null;
    if (!isBikeWorkoutType(workout.workoutType)) return null;
    const parsed = parseStructuredWorkout(workout.structuredWorkout);
    if (parsed.segments.length === 0) return null;
    const bars = expand(parsed.segments);
    const totalMin = bars.reduce((sum, bar) => sum + bar.durationMin, 0);
    const peakPct = bars.reduce((max, bar) => Math.max(max, bar.startPct, bar.endPct), 0);
    const summaries = parsed.segments.map((segment, index) =>
      describeSegment(segment, index, parsed.segments.length),
    );
    return { delivery: parsed.delivery, bars, totalMin, peakPct, summaries };
  }, [workout]);

  if (!workout) return <Sheet open={open} onClose={onClose} title="Workout" children={null} />;

  const Icon = iconFor(workout.workoutType);
  const status = statusBadge(workout.status);
  const isBike = isBikeWorkoutType(workout.workoutType);
  const sourceLabel = workout.source === 'plan_action_add' ? 'You added this' : 'Coach-planned';
  const delivery = structure?.delivery ?? 'indoor';

  return (
    <Sheet open={open} onClose={onClose} title={workout.title}>
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
          <p className="min-w-0 flex-1 font-medium text-text-primary">
            {workoutTypeLabel(workout.workoutType)}
          </p>
          <Badge variant={status.variant} className="shrink-0">
            {status.label}
          </Badge>
        </div>

        <dl className="space-y-2">
          {workout.plannedDurationMin ? (
            <DetailRow label="Planned duration">{workout.plannedDurationMin} min</DetailRow>
          ) : null}
          {workout.intensityTarget ? (
            <DetailRow label="Intensity">{workout.intensityTarget}</DetailRow>
          ) : null}
          {isBike ? <DetailRow label="Where">{delivery === 'outdoor' ? 'Outdoor' : 'Indoor'}</DetailRow> : null}
          <DetailRow label="Source">{sourceLabel}</DetailRow>
        </dl>

        {isBike && delivery === 'outdoor' ? <DeliveryLine delivery={workout.outdoorDelivery ?? null} /> : null}

        {open && workout.status === 'completed' ? (
          <CompletedWorkoutRead plannedWorkoutId={workout.id} />
        ) : null}

        {structure ? (
          <div className="space-y-3">
            <p className="text-sm font-medium text-text-primary">Session structure</p>
            <PowerProfilePreview bars={structure.bars} totalMin={structure.totalMin} peakPct={structure.peakPct} />
            <ol className="space-y-1.5">
              {structure.summaries.map((summary, index) => (
                <li
                  key={index}
                  className="flex items-start justify-between gap-3 rounded-lg border border-border bg-bg px-3 py-2 text-sm"
                >
                  <span className="font-medium text-text-primary">{summary.title}</span>
                  <span className="text-right text-text-secondary">{summary.detail}</span>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-text-secondary">
            No structured breakdown for this session.
          </p>
        )}
      </div>
    </Sheet>
  );
}

function DeliveryLine({ delivery }: { delivery: PlanWorkout['outdoorDelivery'] | null }) {
  if (delivery?.status === 'pushed') {
    return <Badge variant="success">Sent to Garmin</Badge>;
  }
  if (delivery?.status === 'failed') {
    return (
      <Badge variant="error" title={delivery.lastError ?? undefined}>
        Garmin send failed — will retry
      </Badge>
    );
  }
  return <Badge variant="muted">Outdoor · sends to Garmin</Badge>;
}

/**
 * Batch 152: the persisted post-workout read for a completed session, fetched
 * lazily when its Week-view detail sheet opens. It reuses Home's read stack —
 * verdict + Markdown + rate/correct + follow-up chat — so looking back at an old
 * session is as rich as reading it the day of. The read is retrieved, never
 * regenerated; an absent read (still generating, or none) shows an honest line.
 */
function CompletedWorkoutRead({ plannedWorkoutId }: { plannedWorkoutId: string }) {
  const query = useQuery({
    queryKey: ['workout-read', plannedWorkoutId],
    queryFn: async () => {
      const response = await apiFetch<unknown>(
        `/api/v1/plan-actions/workouts/${plannedWorkoutId}/analysis`,
      );
      return workoutReadEnvelopeSchema.parse(response).data.read;
    },
  });

  const heading = <p className="text-sm font-medium text-text-primary">How it went</p>;
  const note = (message: string) => (
    <p className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-text-secondary">
      {message}
    </p>
  );

  if (query.isPending) {
    return (
      <div className="space-y-3">
        {heading}
        {note('Loading your read…')}
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="space-y-3">
        {heading}
        {note("Couldn't load your read just now — try again shortly.")}
      </div>
    );
  }

  const read = query.data;
  if (!read) {
    return (
      <div className="space-y-3">
        {heading}
        {note("No read yet — I'll write one once this session syncs and is analysed.")}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        {heading}
        {read.verdict ? (
          <Badge variant="muted" className="shrink-0 capitalize">
            {read.verdict}
          </Badge>
        ) : null}
      </div>
      <div className="rounded-lg border border-border bg-bg px-3 py-3">
        <Markdown>{read.outputMarkdown}</Markdown>
      </div>
      <FeedbackControl analysisId={read.analysisId} kind="summary" feedback={read.feedback ?? null} />
      <BriefFollowUpChat analysisId={read.analysisId} />
    </div>
  );
}
