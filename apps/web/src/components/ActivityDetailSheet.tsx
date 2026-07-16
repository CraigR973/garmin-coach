import type { planActivitySchema } from '@coach/shared';
import { Bike, Dumbbell, Footprints, Wind, type LucideIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Sheet } from '@/components/ui/sheet';
import { DetailRow } from '@/components/DetailRow';

type PlanActivity = typeof planActivitySchema._type;

const KIND_META: Record<PlanActivity['activityKind'], { icon: LucideIcon; label: string }> = {
  ride: { icon: Bike, label: 'Ride' },
  strength: { icon: Dumbbell, label: 'Strength' },
  flexibility: { icon: Wind, label: 'Flexibility' },
  walk: { icon: Footprints, label: 'Walk' },
};

function formatStartTime(startUtc: string): string {
  return new Date(startUtc).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function formatStartDate(startUtc: string): string {
  return new Date(startUtc).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

/**
 * Read-only detail for an unplanned logged activity (walk / ride / strength /
 * flexibility), opened by tapping its chip on the Week view (Batch 136). The
 * Week payload carries only the light `planActivitySchema` shape, so this shows
 * kind, name, duration, and local start time — and is honest that it is
 * something Mark did, not part of the plan.
 */
export function ActivityDetailSheet({
  open,
  activity,
  onClose,
}: {
  open: boolean;
  activity: PlanActivity | null;
  onClose: () => void;
}) {
  if (!activity) return <Sheet open={open} onClose={onClose} title="Activity" children={null} />;

  const meta = KIND_META[activity.activityKind];
  const Icon = meta.icon;

  return (
    <Sheet open={open} onClose={onClose} title={activity.name}>
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
          <p className="min-w-0 flex-1 font-medium text-text-primary">{meta.label}</p>
          <Badge variant="muted" className="shrink-0">
            Logged
          </Badge>
        </div>

        <dl className="space-y-2">
          {activity.durationMin ? <DetailRow label="Duration">{activity.durationMin} min</DetailRow> : null}
          <DetailRow label="Started">{formatStartTime(activity.startUtc)}</DetailRow>
          <DetailRow label="Day">{formatStartDate(activity.startUtc)}</DetailRow>
        </dl>

        <p className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-text-secondary">
          You did this — it wasn&apos;t part of the plan. I read it after the fact.
        </p>
      </div>
    </Sheet>
  );
}
