import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { trendsNarrativeEnvelopeSchema } from '@coach/shared';
import { CalendarRange, Sparkles, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
  const response = await apiFetch<unknown>(`${BASE}/narrative/run?bucket=${bucket}`, {
    method: 'POST',
  });
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

function deltaVariant(metric: YoYMetric): 'success' | 'error' | 'muted' {
  if (metric.status !== 'ok' || metric.delta === null) return 'muted';
  if (metric.delta > 0) return 'success';
  if (metric.delta < 0) return 'error';
  return 'muted';
}

export function TrendsPage() {
  const queryClient = useQueryClient();
  const [bucket, setBucket] = useState<TrendBucket>('month');
  const query = useQuery({ queryKey: ['trends', bucket], queryFn: () => fetchTrends(bucket) });

  const runMutation = useMutation({
    mutationFn: () => runTrends(bucket),
    onSuccess: (envelope) => {
      queryClient.setQueryData(['trends', bucket], envelope);
      if (envelope.errors.length > 0) {
        toast.error(envelope.errors[0]?.detail ?? 'Failed to generate the summary');
      } else if (envelope.data.status === 'insufficient_history') {
        toast.message('Not enough history yet for a year-on-year summary.');
      } else {
        toast.success('Trend summary generated');
      }
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Failed to generate the summary'),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Trends" eyebrow="Year-on-year & seasonal" />

      <div className="flex gap-2" role="tablist" aria-label="Trend bucket">
        {(['month', 'season'] as const).map((b) => (
          <Button
            key={b}
            type="button"
            role="tab"
            aria-selected={bucket === b}
            variant={bucket === b ? 'default' : 'outline'}
            onClick={() => setBucket(b)}
          >
            {b === 'month' ? 'Monthly' : 'Seasonal'}
          </Button>
        ))}
      </div>

      {query.isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Loading {bucket} trends…</CardTitle>
          </CardHeader>
        </Card>
      ) : query.isError || !query.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Trends unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'The trends could not load.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <TrendsBody
          data={query.data.data}
          generating={runMutation.isPending}
          onGenerate={() => runMutation.mutate()}
        />
      )}
    </div>
  );
}

function TrendsBody({
  data,
  generating,
  onGenerate,
}: {
  data: TrendsEnvelope['data'];
  generating: boolean;
  onGenerate: () => void;
}) {
  const { yearOnYear, recentWindows, narrative } = data;
  const insufficient = yearOnYear.status !== 'ok';

  return (
    <div className="space-y-4">
      <Card className="bg-surface-elevated/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" aria-hidden />
            {yearOnYear.currentLabel ?? data.targetKey} vs {yearOnYear.priorLabel ?? 'last year'}
          </CardTitle>
          <CardDescription>
            Same-period comparison against the prior year. All windows are computed deterministically
            and degrade gracefully until a full year of history exists.
          </CardDescription>
        </CardHeader>
      </Card>

      {insufficient ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarRange className="h-4 w-4 text-text-muted" aria-hidden />
              Insufficient history
            </CardTitle>
            <CardDescription>
              {yearOnYear.reasons[0] ??
                'A full prior-year window is needed before year-on-year deltas appear.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Year-on-year deltas</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {yearOnYear.metrics
                .filter((m) => m.status === 'ok')
                .map((m) => (
                  <li
                    key={m.metricKey}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span className="text-text-primary">{m.label}</span>
                    <span className="flex items-center gap-2">
                      <span className="text-text-muted">
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
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Recent windows</CardTitle>
          <CardDescription>Mean sleep score, readiness and resting HR per window.</CardDescription>
        </CardHeader>
        <CardContent>
          {recentWindows.length === 0 ? (
            <p className="text-sm text-text-muted">No windows with data yet.</p>
          ) : (
            <ul className="space-y-2">
              {recentWindows.map((w) => (
                <WindowRow key={w.key} window={w} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            Narrative summary
          </CardTitle>
          <CardDescription>
            {narrative
              ? `Generated ${new Date(narrative.generatedAtUtc).toLocaleString()}${
                  narrative.modelName ? ` · ${narrative.modelName}` : ''
                }`
              : insufficient
                ? 'A narrative is generated once a year-on-year comparison is possible.'
                : 'No narrative has been generated for this period yet.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {narrative ? (
            <div className="rounded-xl border border-border bg-bg px-4 py-3 text-sm leading-6 text-text-primary whitespace-pre-wrap">
              {narrative.markdown}
            </div>
          ) : null}
          <div className="flex justify-end">
            <Button type="button" onClick={onGenerate} disabled={generating || insufficient}>
              {narrative ? 'Regenerate' : 'Generate summary'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function metricMean(window: TrendWindow, metricKey: string): number | null {
  return window.metrics.find((m) => m.metricKey === metricKey)?.mean ?? null;
}

function WindowRow({ window }: { window: TrendWindow }) {
  return (
    <li className="flex items-center justify-between gap-3 text-sm">
      <span className="flex items-center gap-2">
        <span className="font-medium text-text-primary">{window.label}</span>
        <span className="text-xs text-text-muted">{window.sampleDays}d</span>
      </span>
      <span className="text-text-muted">
        Sleep {fmt(metricMean(window, 'sleep_score'))} · Readiness{' '}
        {fmt(metricMean(window, 'readiness_score'))} · RHR{' '}
        {fmt(metricMean(window, 'resting_hr_bpm'))}
      </span>
    </li>
  );
}
