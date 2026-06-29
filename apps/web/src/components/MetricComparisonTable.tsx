import { Check, Minus, TriangleAlert } from 'lucide-react';
import { type MetricBaselineRow } from '@/components/MetricsBaselineTable';
import { cn } from '@/lib/utils';

/**
 * The last-night comparison table: each metric's value, then how it compares to
 * the user's own normal and to the typical person their age, stated as the
 * difference (the verdict is what you read, not a raw value). It is a bare table
 * — it renders inside the "Last night's sleep" card on Home, so it has no card
 * chrome or title of its own.
 *
 * It joins two server-computed reads (both on the daily-loop morning analysis):
 * `metricsVsBaselines` (`_metrics_vs_baselines`, the "vs your own normal" frame)
 * and `ageComparison` (`services/age_norms.py`, the population frame). The two
 * frames cover different metrics — only resting HR and HRV have both — so a
 * column with no yardstick renders "—".
 *
 * This component only renders. Each frame's tone is direction-aware (a low
 * resting HR is good, a high VO₂max is good), so the difference text is tinted
 * green/amber with the good/bad call already made.
 */

type Tone = 'good' | 'warn' | 'neutral';

export interface AgeComparisonRow {
  metricKey: string;
  label: string;
  value: number;
  unit: string;
  ageAverage: number;
  ageBand: string;
  betterDirection: 'higher' | 'lower';
  tone: Tone;
  descriptor: string;
}

export interface AgeComparison {
  age?: number | null;
  ageBand?: string | null;
  fitnessAge?: number | null;
  fitnessAgeDelta?: number | null;
  fitnessAgeTone?: Tone | null;
  rows: AgeComparisonRow[];
}

// Metrics where a higher value is the better outcome (mirrors MetricsBaselineTable).
const HIGHER_IS_BETTER = new Set([
  'sleep_score',
  'age_adjusted_sleep_score',
  'hrv_7_day_avg_ms',
  'body_battery_charge',
  'average_spo2_pct',
]);
const LOWER_IS_BETTER = new Set(['resting_heart_rate_bpm']);

const BASELINE_UNIT: Record<string, string> = {
  average_spo2_pct: '%',
};

// Which baseline metric an age-norm row lines up against. Resting HR shares a
// key; the age HRV norm is overnight RMSSD, which we sit against the 7-day HRV
// baseline. VO₂max has no nightly baseline, so it appends as an age-only row.
const AGE_TO_BASELINE_KEY: Record<string, string> = {
  resting_heart_rate_bpm: 'resting_heart_rate_bpm',
  hrv_overnight_ms: 'hrv_7_day_avg_ms',
};

const toneText: Record<Tone, string> = {
  good: 'text-success',
  warn: 'text-warning',
  neutral: 'text-text-muted',
};

function ToneIcon({ tone, className }: { tone: Tone; className?: string }) {
  const Icon = tone === 'good' ? Check : tone === 'warn' ? TriangleAlert : Minus;
  return <Icon className={cn('h-4 w-4 shrink-0', className)} aria-hidden />;
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

interface Diff {
  tone: Tone;
  text: string;
}

// "vs your own normal" as a difference: in-band reads "in range"; outside the
// trailing-quartile band reads "<n> above/below", tinted by whether that
// direction is good for the metric.
function baselineDiff(row: MetricBaselineRow): Diff | null {
  const current = row.currentValue;
  const center = row.baselineMedian ?? row.baselineMean;
  if (current === null || current === undefined || center == null) return null;

  const lower = row.lowerQuartile ?? center;
  const upper = row.upperQuartile ?? center;
  const tol = Math.max(Math.abs(center) * 0.03, 0.5);

  if (current >= lower - tol && current <= upper + tol) {
    return { tone: 'good', text: 'in range' };
  }
  const above = current > upper + tol;
  const magnitude = above ? current - upper : lower - current;
  const good =
    (above && HIGHER_IS_BETTER.has(row.metricKey)) ||
    (!above && LOWER_IS_BETTER.has(row.metricKey));
  return { tone: good ? 'good' : 'warn', text: `${fmt(magnitude)} ${above ? 'above' : 'below'}` };
}

// "vs the typical person your age" as a difference off the population average.
// Tone is pre-computed direction-aware by age_norms; near-average reads as a
// flat "about average" rather than a tiny signed number.
function ageDiff(row: AgeComparisonRow): Diff {
  if (row.tone === 'neutral') return { tone: 'neutral', text: 'about average' };
  const delta = row.value - row.ageAverage;
  return { tone: row.tone, text: `${fmt(Math.abs(delta))} ${delta >= 0 ? 'above' : 'below'}` };
}

interface UnifiedRow {
  key: string;
  label: string;
  current: number | null | undefined;
  currentUnit: string;
  baseline: MetricBaselineRow | null;
  age: AgeComparisonRow | null;
}

// Left-join the two frames into one row per metric: every baseline metric, then
// any age-only metric (VO₂max) appended.
function buildRows(baseline: MetricBaselineRow[], ageRows: AgeComparisonRow[]): UnifiedRow[] {
  const byBaselineKey = new Map<string, AgeComparisonRow>();
  const ageOnly: AgeComparisonRow[] = [];
  for (const a of ageRows) {
    const bkey = AGE_TO_BASELINE_KEY[a.metricKey];
    if (bkey) byBaselineKey.set(bkey, a);
    else ageOnly.push(a);
  }

  const rows: UnifiedRow[] = baseline.map((b) => {
    const a = byBaselineKey.get(b.metricKey) ?? null;
    byBaselineKey.delete(b.metricKey);
    return {
      key: b.metricKey,
      label: b.label,
      current: b.currentValue,
      currentUnit: BASELINE_UNIT[b.metricKey] ?? '',
      baseline: b,
      age: a,
    };
  });

  // Age metrics with no matching baseline row (VO₂max always; RHR/HRV only if a
  // baseline hasn't been computed yet) get their own row with no "normal".
  for (const a of [...ageOnly, ...byBaselineKey.values()]) {
    rows.push({
      key: a.metricKey,
      label: a.label,
      current: a.value,
      currentUnit: a.unit,
      baseline: null,
      age: a,
    });
  }
  return rows;
}

function DiffCell({ diff }: { diff: Diff | null }) {
  if (!diff) {
    return <td className="whitespace-nowrap px-1.5 py-2 text-right text-text-muted sm:px-3">—</td>;
  }
  return (
    <td
      className={cn(
        'whitespace-nowrap px-1.5 py-2 text-right font-medium sm:px-3',
        toneText[diff.tone],
      )}
    >
      <span className="inline-flex items-center justify-end gap-1.5">
        <ToneIcon tone={diff.tone} className="h-3.5 w-3.5" />
        {diff.text}
      </span>
    </td>
  );
}

export function MetricComparisonTable({
  rows: baselineRows,
  ageComparison,
}: {
  rows: MetricBaselineRow[];
  ageComparison: AgeComparison | null;
}) {
  const age = ageComparison ?? { rows: [] };
  const rows = buildRows(baselineRows, age.rows);

  if (rows.length === 0) {
    return (
      <p className="text-sm text-text-secondary">
        This fills in as more nights sync — your baselines and age comparison need a little history
        first.
      </p>
    );
  }

  const reliabilityNote = baselineRows.some(
    (r) => (r.excludedSampleCount ?? 0) > 0 && r.reliabilityStartDate,
  );
  const hasAge = rows.some((r) => r.age != null);

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full border-collapse text-xs sm:text-sm">
          <thead className="bg-surface-elevated">
            <tr>
              <th className="px-2 py-2 text-left font-semibold text-text-secondary sm:px-3">
                Metric
              </th>
              <th className="px-1.5 py-2 text-right font-semibold text-text-secondary sm:px-3">
                Last night
              </th>
              <th className="px-1.5 py-2 text-right font-semibold text-text-secondary sm:px-3">
                vs your normal
              </th>
              <th className="px-1.5 py-2 text-right font-semibold text-text-secondary sm:px-3">
                vs your age
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-t border-border">
                <td className="px-2 py-2 text-text-primary sm:px-3">{row.label}</td>
                <td className="whitespace-nowrap px-1.5 py-2 text-right font-semibold text-text-primary tabular-nums sm:px-3">
                  {row.current == null ? '—' : `${fmt(row.current)}${row.currentUnit}`}
                </td>
                <DiffCell diff={row.baseline ? baselineDiff(row.baseline) : null} />
                <DiffCell diff={row.age ? ageDiff(row.age) : null} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {reliabilityNote && (
        <p className="text-xs text-text-muted">
          HRV &amp; SpO₂ baselines use readings from after the strap was re-fitted (11 Jun); earlier
          nights are excluded.
        </p>
      )}
      {hasAge && (
        <p className="text-[11px] text-text-muted">
          “vs your age” compares you with the general-population average for{' '}
          {age.ageBand ? `the typical ${age.ageBand} year-old` : 'your age and sex'} — a rough
          guide, not medical advice.
        </p>
      )}
    </div>
  );
}
