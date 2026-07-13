import { Badge } from '@/components/ui/badge';
import type { DailyLoopData } from '@/hooks/useDailyLoop';

export function WalkingBaseCard({
  brief,
  title = 'Walking base',
  description,
}: {
  brief: NonNullable<DailyLoopData['walkingBrief']>;
  title?: string;
  description?: string;
}) {
  const distanceKm = brief.window4w.totalDistanceM / 1000;

  return (
    <div className="rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-text-primary">{title}</p>
          <p className="text-sm text-text-secondary">
            {brief.window4w.sessionCount} walks · {distanceKm.toFixed(1)} km ·{' '}
            {brief.window4w.totalDurationMin} min in 4 weeks
          </p>
        </div>
        <Badge variant="muted">{brief.trend.replace(/_/g, ' ')}</Badge>
      </div>
      <p className="mt-2 text-sm text-text-secondary">{brief.trendReason}</p>
      {description ? <p className="mt-2 text-xs text-text-muted">{description}</p> : null}
    </div>
  );
}
