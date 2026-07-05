import { Check, Minus, TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AgeComparisonRow } from '@/components/MetricComparisonTable';

type Tone = 'good' | 'warn' | 'neutral';

const toneText: Record<Tone, string> = {
  good: 'text-success',
  warn: 'text-warning',
  neutral: 'text-text-muted',
};

function ToneIcon({ tone }: { tone: Tone }) {
  const Icon = tone === 'good' ? Check : tone === 'warn' ? TriangleAlert : Minus;
  return <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />;
}

function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function SleepStageAgeTable({
  rows,
  ageBand,
}: {
  rows: AgeComparisonRow[];
  ageBand?: string | null;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-text-secondary">
        This fills in when the overnight sleep stages are available.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full border-collapse text-xs sm:text-sm">
          <thead className="bg-surface-elevated">
            <tr>
              <th className="px-2 py-2 text-left font-semibold text-text-secondary sm:px-3">
                Stage
              </th>
              <th className="px-2 py-2 text-right font-semibold text-text-secondary sm:px-3">
                Last night
              </th>
              <th className="px-2 py-2 text-right font-semibold text-text-secondary sm:px-3">
                Typical
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metricKey} className="border-t border-border">
                <td className="px-2 py-2 text-text-primary sm:px-3">{row.label}</td>
                <td className="px-2 py-2 text-right font-semibold tabular-nums text-text-primary sm:px-3">
                  {fmt(row.value)}
                  {row.unit}
                </td>
                <td className="px-2 py-2 text-right sm:px-3">
                  <div className="font-medium tabular-nums text-text-secondary">
                    {fmt(row.ageAverage)}
                    {row.unit}
                  </div>
                  <div
                    className={cn(
                      'mt-0.5 inline-flex items-center justify-end gap-1 text-[11px] font-medium',
                      toneText[row.tone],
                    )}
                  >
                    <ToneIcon tone={row.tone} />
                    {row.descriptor}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-text-muted">
        “Typical” uses the general-population average for{' '}
        {ageBand ? `the ${ageBand} age band` : 'your age band'} and is a rough guide, not medical
        advice.
      </p>
    </div>
  );
}
