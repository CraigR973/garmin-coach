import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { trendsNarrativeEnvelopeSchema } from '@coach/shared';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { CalendarRange, Sparkles, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';
import { colors } from '@/theme/tokens';
import { Markdown } from '@/components/Markdown';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { WalkingBaseCard } from '@/components/WalkingBaseCard';
import { useDailyLoop, type DailyLoopData } from '@/hooks/useDailyLoop';
import { apiFetch } from '@/lib/api';

type TrendsEnvelope = typeof trendsNarrativeEnvelopeSchema._type;
type TrendBucket = TrendsEnvelope['data']['bucket'];
type YoYMetric = TrendsEnvelope['data']['yearOnYear']['metrics'][number];
type TrendWindow = TrendsEnvelope['data']['recentWindows'][number];

const BASE = '/api/v1/trends';

async function fetchTrends(bucket: TrendBucket) {
  const response = await apiFetch<unknown>(`${BASE}/narrative?bucket=${bucket}`);
  return trendsNarrativeEnvelopeSchema.parse(response);
}

async function runTrends(bucket: TrendBucket) {
  const response = await apiFetch<unknown>(`${BASE}/narrative/run?bucket=${bucket}`, { method: 'POST' });
  return trendsNarrativeEnvelopeSchema.parse(response);
}

function fmt(value: number | null, suffix = ''): string {
  return value === null ? '—' : `${value}${suffix}`;
}

function pct(value: number | null): string {
  if (value === null) return '';
  const sign = value > 0 ? '+' : '';
  return `${sign}${(value * 100).toFixed(1)}%`;
}

// Sleep and readiness rising is good; resting HR is shown separately.
const HIGHER_IS_BETTER = new Set(['sleep_score', 'readiness_score', 'hrv_last_night_ms', 'vo2_max']);

function deltaVariant(metric: YoYMetric): 'success' | 'error' | 'muted' {
  if (metric.status !== 'ok' || metric.delta === null) return 'muted';
  const better = HIGHER_IS_BETTER.has(metric.metricKey);
  if (metric.delta > 0) return better ? 'success' : 'error';
  if (metric.delta < 0) return better ? 'error' : 'success';
  return 'muted';
}

function metricMean(window: TrendWindow, metricKey: string): number | null {
  return window.metrics.find((m) => m.metricKey === metricKey)?.mean ?? null;
}

export function TrendsPage() {
  const queryClient = useQueryClient();
  const [bucket, setBucket] = useState<TrendBucket>('month');
  const query = useQuery({ queryKey: ['trends', bucket], queryFn: () => fetchTrends(bucket) });
  const dailyLoopQuery = useDailyLoop();

  const runMutation = useMutation({
    mutationFn: () => runTrends(bucket),
    onSuccess: (envelope) => {
      queryClient.setQueryData(['trends', bucket], envelope);
      if (envelope.errors.length > 0) {
        toast.error(envelope.errors[0]?.detail ?? 'Could not write the summary');
      } else if (envelope.data.status === 'insufficient_history') {
        toast.message('Not enough history yet for a year-on-year summary.');
      } else {
        toast.success('Summary written');
      }
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not write the summary'),
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Trends" />

      <div className="flex gap-2" role="tablist" aria-label="Group by">
        {(['month', 'season'] as const).map((b) => (
          <Button
            key={b}
            type="button"
            role="tab"
            aria-selected={bucket === b}
            variant={bucket === b ? 'default' : 'outline'}
            onClick={() => setBucket(b)}
          >
            {b === 'month' ? 'By month' : 'By season'}
          </Button>
        ))}
      </div>

      {query.isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Loading your trends…</CardTitle>
          </CardHeader>
        </Card>
      ) : query.isError || !query.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Trends couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <TrendsBody
          data={query.data.data}
          walkingBrief={dailyLoopQuery.data?.data.walkingBrief ?? null}
          generating={runMutation.isPending}
          onGenerate={() => runMutation.mutate()}
        />
      )}
    </div>
  );
}

function TrendsBody({
  data,
  walkingBrief,
  generating,
  onGenerate,
}: {
  data: TrendsEnvelope['data'];
  walkingBrief: DailyLoopData['walkingBrief'] | null;
  generating: boolean;
  onGenerate: () => void;
}) {
  const { yearOnYear, recentWindows, narrative } = data;
  const insufficient = yearOnYear.status !== 'ok';

  // Oldest → newest so the line reads left-to-right (sort by window start).
  const chartData = [...recentWindows]
    .sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0))
    .map((w) => ({
      label: w.label,
      Sleep: metricMean(w, 'sleep_score'),
      Readiness: metricMean(w, 'readiness_score'),
    }));

  return (
    <div className="space-y-4">
      {walkingBrief ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Walking base</CardTitle>
            <CardDescription>
              Keep deliberate walking credited in the long-range view instead of inside today&apos;s workout card.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <WalkingBaseCard brief={walkingBrief} description="This 4-week base sits alongside your broader trends." />
          </CardContent>
        </Card>
      ) : null}

      {/* Trend chart */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" aria-hidden />
            Sleep &amp; readiness over time
          </CardTitle>
          <CardDescription>Your averages for each {data.bucket === 'season' ? 'season' : 'month'}.</CardDescription>
        </CardHeader>
        <CardContent>
          {chartData.length >= 2 ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                <XAxis dataKey="label" tick={{ fill: colors.textMuted, fontSize: 11 }} stroke={colors.border} />
                <YAxis tick={{ fill: colors.textMuted, fontSize: 11 }} stroke={colors.border} width={36} />
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface-elevated)',
                    border: '1px solid var(--border)',
                    borderRadius: 12,
                    color: 'var(--text-primary)',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="Sleep" stroke={colors.primary} strokeWidth={2} dot={{ r: 3 }} connectNulls />
                <Line type="monotone" dataKey="Readiness" stroke={colors.accent} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-text-muted">Not enough history yet to draw a trend.</p>
          )}
        </CardContent>
      </Card>

      {/* This year vs last year */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {yearOnYear.currentLabel ?? data.targetKey} vs {yearOnYear.priorLabel ?? 'last year'}
          </CardTitle>
          <CardDescription>How this period compares with the same time last year.</CardDescription>
        </CardHeader>
        <CardContent>
          {insufficient ? (
            <div className="flex items-start gap-2 text-sm text-text-secondary">
              <CalendarRange className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" aria-hidden />
              <span>
                {yearOnYear.reasons[0] ??
                  "Not enough history yet — a full year is needed before last-year comparisons appear."}
              </span>
            </div>
          ) : (
            <ul className="space-y-2">
              {yearOnYear.metrics
                .filter((m) => m.status === 'ok')
                .map((m) => (
                  <li key={m.metricKey} className="flex items-center justify-between gap-3 text-sm">
                    <span className="text-text-primary">{m.label}</span>
                    <span className="flex items-center gap-2">
                      <span className="text-text-muted tabular-nums">
                        {fmt(m.priorMean)} → {fmt(m.currentMean)}
                      </span>
                      <Badge variant={deltaVariant(m)}>
                        {m.delta !== null && m.delta > 0 ? '+' : ''}
                        {fmt(m.delta)} {pct(m.pctChange)}
                      </Badge>
                    </span>
                  </li>
                ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Exact figures per window */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Recent {data.bucket === 'season' ? 'seasons' : 'months'}</CardTitle>
        </CardHeader>
        <CardContent>
          {recentWindows.length === 0 ? (
            <p className="text-sm text-text-muted">No data yet.</p>
          ) : (
            <ul className="space-y-2">
              {recentWindows.map((w) => (
                <li key={w.key} className="flex items-center justify-between gap-3 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="font-medium text-text-primary">{w.label}</span>
                    <span className="text-xs text-text-muted">{w.sampleDays}d</span>
                  </span>
                  <span className="text-text-muted tabular-nums">
                    Sleep {fmt(metricMean(w, 'sleep_score'))} · Readiness {fmt(metricMean(w, 'readiness_score'))} · RHR{' '}
                    {fmt(metricMean(w, 'resting_hr_bpm'))}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Written summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            Written summary
          </CardTitle>
          <CardDescription>
            {narrative
              ? `Written ${new Date(narrative.generatedAtUtc).toLocaleString()}`
              : insufficient
                ? 'A written summary appears once last-year comparisons are possible.'
                : 'No summary written for this period yet.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {narrative ? (
            <div className="rounded-xl border border-border bg-bg px-4 py-3">
              <Markdown>{narrative.markdown}</Markdown>
            </div>
          ) : null}
          <div className="flex justify-end">
            <Button type="button" onClick={onGenerate} disabled={generating || insufficient}>
              {narrative ? 'Rewrite' : 'Write summary'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
