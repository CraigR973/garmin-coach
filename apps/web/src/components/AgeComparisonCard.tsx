import { Check, Minus, TriangleAlert, Users } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * "How you compare for your age" — the population-average read Mark asked for,
 * alongside the "vs your own baseline" table. Garmin's fitness age is the
 * headline (its own age-equivalent for his VO2max); below it, each metric sits
 * against the general-population average for his sex + decade band.
 *
 * The data is computed deterministically server-side (`services/age_norms.py`)
 * and surfaced on the daily-loop morning analysis. Tone + descriptor arrive
 * pre-derived (direction-aware: a low resting HR is good), so this component
 * only renders — it never re-decides what "better" means.
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

const toneText: Record<Tone, string> = {
  good: 'text-success',
  warn: 'text-warning',
  neutral: 'text-text-muted',
};

const toneTile: Record<Tone, string> = {
  good: 'border-success/30 bg-success/5',
  warn: 'border-warning/40 bg-warning/10',
  neutral: 'border-border',
};

function ToneIcon({ tone, className }: { tone: Tone; className?: string }) {
  const Icon = tone === 'good' ? Check : tone === 'warn' ? TriangleAlert : Minus;
  return <Icon className={cn('h-4 w-4 shrink-0', className)} aria-hidden />;
}

function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function fitnessAgeLine(comparison: AgeComparison): { text: string; tone: Tone } | null {
  if (comparison.fitnessAge == null) return null;
  const delta = comparison.fitnessAgeDelta;
  const tone = comparison.fitnessAgeTone ?? 'neutral';
  if (delta == null || delta === 0) {
    return { text: 'In line with your actual age', tone };
  }
  const years = Math.abs(delta);
  const yearWord = years === 1 ? 'year' : 'years';
  return {
    text: `${years} ${yearWord} ${delta > 0 ? 'younger' : 'older'} than your actual age`,
    tone,
  };
}

export function AgeComparisonCard({ comparison }: { comparison: AgeComparison }) {
  const headline = fitnessAgeLine(comparison);
  const hasContent = headline != null || comparison.rows.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Users className="h-4 w-4 text-primary" aria-hidden />
          How you compare for your age
        </CardTitle>
        <CardDescription>
          {comparison.ageBand
            ? `You vs the typical ${comparison.ageBand} year-old.`
            : 'You vs the typical person your age.'}
        </CardDescription>
      </CardHeader>
      {hasContent ? (
        <CardContent className="space-y-4">
          {headline && comparison.fitnessAge != null && (
            <div className={cn('rounded-xl border px-4 py-3', toneTile[headline.tone])}>
              <p className="text-xs text-text-muted">Garmin fitness age</p>
              <p className="text-2xl font-semibold text-text-primary">{comparison.fitnessAge}</p>
              <p className={cn('mt-0.5 flex items-center gap-1.5 text-sm font-medium', toneText[headline.tone])}>
                <ToneIcon tone={headline.tone} />
                {headline.text}
              </p>
            </div>
          )}

          {comparison.rows.length > 0 && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {comparison.rows.map((row) => (
                <div key={row.metricKey} className={cn('rounded-xl border px-3 py-3', toneTile[row.tone])}>
                  <p className="text-xs text-text-muted">{row.label}</p>
                  <p className="text-lg font-semibold text-text-primary tabular-nums">
                    {fmt(row.value)}
                    {row.unit}
                  </p>
                  <p className="text-[11px] text-text-muted">
                    avg {fmt(row.ageAverage)}
                    {row.unit} · {row.ageBand}
                    {row.betterDirection === 'lower' ? ' · lower is better' : ''}
                  </p>
                  <p className={cn('mt-1 flex items-center gap-1.5 text-xs font-medium', toneText[row.tone])}>
                    <ToneIcon tone={row.tone} className="h-3.5 w-3.5" />
                    {row.descriptor}
                  </p>
                </div>
              ))}
            </div>
          )}

          <p className="text-[11px] text-text-muted">
            Compared with general-population averages for your age — a rough guide, not medical advice.
          </p>
        </CardContent>
      ) : (
        <CardContent>
          <p className="text-sm text-text-secondary">
            Your age comparison shows up once VO₂max and overnight metrics have synced.
          </p>
        </CardContent>
      )}
    </Card>
  );
}
