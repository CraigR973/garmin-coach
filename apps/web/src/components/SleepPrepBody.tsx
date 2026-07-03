import { Check } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { DailyLoopData } from '@/hooks/useDailyLoop';

type SleepProjection = DailyLoopData['sleepProjection'];

/** Tonight's evening sleep projection (Batch 46) — the wind-down headline, prep
 *  actions, and evidence disclosure. Shared by Home's "Tonight" section (compact
 *  context) and the `/sleep` hub's "Tonight" view (Batch 49) — extracted from
 *  `DashboardPage` so both render the same piece. */
export function SleepPrepBody({ projection }: { projection: SleepProjection | null }) {
  if (!projection) {
    return (
      <p className="text-sm leading-6 text-text-primary">
        Aim for the usual sleep setup: pre-cool the room, keep the evening calm, and stay on the bedtime routine.
      </p>
    );
  }

  return (
    <div className="space-y-3 text-sm">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={projection.tone === 'protect' ? 'warning' : projection.tone === 'watch' ? 'default' : 'muted'}>
            {projection.tone === 'protect' ? 'Protect' : projection.tone === 'watch' ? 'Watch' : 'Routine'}
          </Badge>
          <p className="font-medium text-text-primary">{projection.headline}</p>
        </div>
        <p className="leading-6 text-text-secondary">{projection.summary}</p>
      </div>
      {projection.prepActions.length > 0 && (
        <ul className="space-y-2">
          {projection.prepActions.map((action) => (
            <li key={action} className="flex gap-2 leading-6 text-text-primary">
              <Check className="mt-1 h-4 w-4 shrink-0 text-success" aria-hidden />
              <span>{action}</span>
            </li>
          ))}
        </ul>
      )}
      {projection.evidence.length > 0 && (
        <details className="rounded-lg border border-border bg-bg px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-text-primary">Evidence</summary>
          <ul className="mt-2 space-y-1.5 text-text-secondary">
            {projection.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
