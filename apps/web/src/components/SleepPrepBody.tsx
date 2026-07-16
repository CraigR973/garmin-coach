import { Badge } from '@/components/ui/badge';
import type { DailyLoopData } from '@/hooks/useDailyLoop';

type SleepProjection = DailyLoopData['sleepProjection'];

function projectionBasisSummary(projection: NonNullable<SleepProjection>): string {
  if (projection.status !== 'personalized') {
    return "Right now this is your standard sleep routine. It has not seen enough personal training signal to move off the default plan yet.";
  }

  const evidence = projection.evidence.map((line) => line.toLowerCase());
  const basis: string[] = [];

  if (
    evidence.some(
      (line) =>
        line.includes('latest session') ||
        line.includes('training effect') ||
        line.includes('load/duration') ||
        line.includes('early/light'),
    )
  ) {
    basis.push("today's training");
  }
  if (evidence.some((line) => line.includes('sleep score') || line.includes('measured driver'))) {
    basis.push('your measured sleep drivers');
  }
  if (evidence.some((line) => line.includes('bedroom is currently'))) {
    basis.push('the room right now');
  } else if (evidence.some((line) => line.includes('forecast overnight low'))) {
    basis.push('the overnight forecast');
  }

  if (basis.length === 0) {
    return 'Right now this is based on the signals collected so far.';
  }

  if (basis.length === 1) {
    return `Right now this is based on ${basis[0]}.`;
  }

  const head = basis.slice(0, -1).join(', ');
  const tail = basis[basis.length - 1];
  return `Right now this is based on ${head}, and ${tail}.`;
}

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
        <p className="text-xs leading-5 text-text-muted">{projectionBasisSummary(projection)}</p>
      </div>
      {projection.prepActions.length > 0 && (
        <ul className="space-y-2">
          {projection.prepActions.map((action) => (
            <li key={action} className="flex gap-2.5 leading-6 text-text-primary">
              {/* Neutral bullet, not a green check — these are things to do
                  tonight, not items already completed. */}
              <span className="mt-[0.5rem] h-1.5 w-1.5 shrink-0 rounded-full bg-text-muted" aria-hidden />
              <span>{action}</span>
            </li>
          ))}
        </ul>
      )}
      {projection.evidence.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-xs font-medium text-text-muted transition hover:text-text-secondary">
            Evidence
          </summary>
          <ul className="mt-2 space-y-1.5 border-l border-border pl-3 text-text-secondary">
            {projection.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
