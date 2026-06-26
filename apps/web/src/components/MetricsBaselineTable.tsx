import { Check, TriangleAlert, Minus } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * "Metrics vs your baselines" — the Copilot-style table Mark explicitly asked
 * for (Metric | Last night | Baseline | Status with ✔/⚠).
 *
 * The data is computed deterministically server-side (`_metrics_vs_baselines`)
 * and surfaced on the daily-loop morning analysis. Status here is derived
 * deterministically from the trailing-window quartile band, direction-aware per
 * metric (higher-is-better vs lower-is-better).
 */

export interface MetricBaselineRow {
  metricKey: string;
  label: string;
  currentValue?: number | null;
  baselineMedian?: number | null;
  baselineMean?: number | null;
  deltaVsBaseline?: number | null;
  lowerQuartile?: number | null;
  upperQuartile?: number | null;
  sampleCount?: number;
  excludedSampleCount?: number;
  reliabilityStartDate?: string | null;
}

// Metrics where a higher value is the better outcome. Resting HR is the only
// lower-is-better metric here; respiration is treated as in-band-is-best.
const HIGHER_IS_BETTER = new Set([
  'sleep_score',
  'age_adjusted_sleep_score',
  'hrv_7_day_avg_ms',
  'body_battery_charge',
  'average_spo2_pct',
]);
const LOWER_IS_BETTER = new Set(['resting_heart_rate_bpm']);

const UNIT: Record<string, string> = {
  average_spo2_pct: '%',
};

type Tone = 'good' | 'warn' | 'neutral';

interface Status {
  tone: Tone;
  label: string;
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatCurrent(row: MetricBaselineRow): string {
  if (row.currentValue === null || row.currentValue === undefined) return '—';
  return `${fmt(row.currentValue)}${UNIT[row.metricKey] ?? ''}`;
}

function formatBaseline(row: MetricBaselineRow): string {
  const unit = UNIT[row.metricKey] ?? '';
  if (row.lowerQuartile != null && row.upperQuartile != null) {
    return `${fmt(row.lowerQuartile)}–${fmt(row.upperQuartile)}${unit}`;
  }
  const center = row.baselineMedian ?? row.baselineMean;
  return center == null ? '—' : `~${fmt(center)}${unit}`;
}

function deriveStatus(row: MetricBaselineRow): Status {
  const current = row.currentValue;
  const center = row.baselineMedian ?? row.baselineMean;
  if (current === null || current === undefined || center == null) {
    return { tone: 'neutral', label: 'No data' };
  }

  const lower = row.lowerQuartile ?? center;
  const upper = row.upperQuartile ?? center;
  const tol = Math.max(Math.abs(center) * 0.03, 0.5); // tolerance when no band

  const below = current < lower - tol;
  const above = current > upper + tol;
  if (!below && !above) return { tone: 'good', label: 'Normal' };

  const higherBetter = HIGHER_IS_BETTER.has(row.metricKey);
  const lowerBetter = LOWER_IS_BETTER.has(row.metricKey);

  if (above) {
    if (higherBetter) return { tone: 'good', label: 'Strong' };
    if (lowerBetter) return { tone: 'warn', label: 'High' };
    return { tone: 'warn', label: 'High' };
  }
  // below
  if (lowerBetter) return { tone: 'good', label: 'Low' };
  if (higherBetter) return { tone: 'warn', label: 'Low' };
  return { tone: 'warn', label: 'Low' };
}

const toneClasses: Record<Tone, string> = {
  good: 'text-success',
  warn: 'text-warning',
  neutral: 'text-text-muted',
};

function StatusCell({ status }: { status: Status }) {
  const Icon = status.tone === 'good' ? Check : status.tone === 'warn' ? TriangleAlert : Minus;
  return (
    <span className={cn('inline-flex items-center gap-1.5 font-medium', toneClasses[status.tone])}>
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      {status.label}
    </span>
  );
}

export function MetricsBaselineTable({ rows }: { rows: MetricBaselineRow[] }) {
  if (!rows.length) {
    return (
      <p className="text-sm text-text-secondary">
        Your baselines build up as more nights sync — this table fills in once there's enough history.
      </p>
    );
  }

  const hasReliabilityNote = rows.some(
    (r) => (r.excludedSampleCount ?? 0) > 0 && r.reliabilityStartDate,
  );

  return (
    <div>
      <div className="overflow-hidden rounded-xl border border-border">
        <table className="w-full table-fixed border-collapse text-xs sm:text-sm">
          <thead className="bg-surface-elevated">
            <tr>
              <th className="px-2 py-2 text-left font-semibold text-text-secondary sm:px-3">Metric</th>
              <th className="px-1.5 py-2 text-right font-semibold text-text-secondary sm:px-3">Last night</th>
              <th className="px-1.5 py-2 text-right font-semibold text-text-secondary sm:px-3">Baseline</th>
              <th className="w-[88px] px-2 py-2 text-left font-semibold text-text-secondary sm:w-auto sm:px-3">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metricKey} className="border-t border-border">
                <td className="px-2 py-2 text-text-primary sm:px-3">{row.label}</td>
                <td className="whitespace-nowrap px-1.5 py-2 text-right font-semibold text-text-primary tabular-nums sm:px-3">
                  {formatCurrent(row)}
                </td>
                <td className="whitespace-nowrap px-1.5 py-2 text-right text-text-secondary tabular-nums sm:px-3">
                  {formatBaseline(row)}
                </td>
                <td className="px-2 py-2 sm:px-3">
                  <StatusCell status={deriveStatus(row)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasReliabilityNote && (
        <p className="mt-2 text-xs text-text-muted">
          HRV &amp; SpO₂ baselines use readings from after the strap was re-fitted (11 Jun); earlier
          nights are excluded.
        </p>
      )}
    </div>
  );
}
