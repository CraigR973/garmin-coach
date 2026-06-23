import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { reviewEnvelopeSchema } from '@coach/shared';
import { Activity, BedDouble, Dumbbell, FileText, HeartPulse, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';

type ReviewEnvelope = typeof reviewEnvelopeSchema._type;
type ReviewPeriod = ReviewEnvelope['data']['period'];

const BASE = '/api/v1/reviews';

async function fetchReview(period: ReviewPeriod) {
  const response = await apiFetch<unknown>(`${BASE}/${period}`);
  return reviewEnvelopeSchema.parse(response);
}

async function runReview(period: ReviewPeriod) {
  const response = await apiFetch<unknown>(`${BASE}/${period}/run`, { method: 'POST' });
  return reviewEnvelopeSchema.parse(response);
}

function trendVariant(trend: string): 'success' | 'warning' | 'error' | 'muted' {
  if (trend === 'increasing') return 'success';
  if (trend === 'decreasing') return 'error';
  if (trend === 'insufficient_data') return 'muted';
  return 'warning';
}

function fmt(value: number | null, suffix = ''): string {
  return value === null ? '—' : `${value}${suffix}`;
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  });
}

export function ReviewsPage() {
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState<ReviewPeriod>('weekly');
  const query = useQuery({ queryKey: ['review', period], queryFn: () => fetchReview(period) });

  const runMutation = useMutation({
    mutationFn: () => runReview(period),
    onSuccess: (envelope) => {
      queryClient.setQueryData(['review', period], envelope);
      if (envelope.errors.length > 0) {
        toast.error(envelope.errors[0]?.detail ?? 'Failed to generate the review');
      } else {
        toast.success('Review generated');
      }
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Failed to generate the review'),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Deep reviews" eyebrow="Weekly & monthly" />

      <div className="flex gap-2" role="tablist" aria-label="Review period">
        {(['weekly', 'monthly'] as const).map((p) => (
          <Button
            key={p}
            type="button"
            role="tab"
            aria-selected={period === p}
            variant={period === p ? 'default' : 'outline'}
            onClick={() => setPeriod(p)}
          >
            {p === 'weekly' ? 'Weekly' : 'Monthly'}
          </Button>
        ))}
      </div>

      {query.isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Loading the {period} review…</CardTitle>
          </CardHeader>
        </Card>
      ) : query.isError || !query.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Review unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'The review could not load.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <ReviewBody
          data={query.data.data}
          generating={runMutation.isPending}
          onGenerate={() => runMutation.mutate()}
        />
      )}
    </div>
  );
}

function ReviewBody({
  data,
  generating,
  onGenerate,
}: {
  data: ReviewEnvelope['data'];
  generating: boolean;
  onGenerate: () => void;
}) {
  const { rollup, strength, insights, review } = data;

  return (
    <div className="space-y-4">
      <Card className="bg-surface-elevated/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" aria-hidden />
            {data.period === 'weekly' ? 'This week' : 'This month'}
          </CardTitle>
          <CardDescription>
            {formatDate(data.periodStart)} – {formatDate(data.periodEnd)} · {data.dayCount} days. The
            rollup is computed deterministically; the narrative is generated on demand.
          </CardDescription>
        </CardHeader>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <SummaryCard
          icon={<BedDouble className="h-4 w-4 text-primary" aria-hidden />}
          title="Sleep"
          trend={rollup.sleep.trend}
          rows={[
            ['Nights', String(rollup.sleep.nights)],
            ['Avg score', fmt(rollup.sleep.avgScore)],
            ['Avg age-adj.', fmt(rollup.sleep.avgAgeAdjustedScore)],
            ['Avg duration', fmt(rollup.sleep.avgDurationMin, ' min')],
          ]}
        />
        <SummaryCard
          icon={<HeartPulse className="h-4 w-4 text-primary" aria-hidden />}
          title="Recovery"
          trend={rollup.recovery.trend}
          rows={[
            ['Days', String(rollup.recovery.days)],
            ['Avg HRV', fmt(rollup.recovery.avgHrvMs, ' ms')],
            ['Avg readiness', fmt(rollup.recovery.avgReadiness)],
            ['Avg resting HR', fmt(rollup.recovery.avgRestingHrBpm, ' bpm')],
          ]}
        />
        <SummaryCard
          icon={<Activity className="h-4 w-4 text-primary" aria-hidden />}
          title="Training load"
          rows={[
            ['Activities', String(rollup.trainingLoad.activityCount)],
            ['Total load', fmt(rollup.trainingLoad.totalLoad)],
            ['Total time', fmt(rollup.trainingLoad.totalDurationMin, ' min')],
            [
              'Verdicts',
              `${rollup.verdicts.green}G · ${rollup.verdicts.amber}A · ${rollup.verdicts.red}R`,
            ],
          ]}
        />
        <SummaryCard
          icon={<Dumbbell className="h-4 w-4 text-primary" aria-hidden />}
          title="Strength & signals"
          trend={strength.trend}
          rows={[
            ['Sessions (4w)', String(strength.sessions4w)],
            ['Per week (4w)', String(strength.sessionsPerWeek4w)],
            ['FTP drift', insights.ftpDriftStatus],
            ['Early warning', insights.earlyWarningStatus],
          ]}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            Narrative review
          </CardTitle>
          <CardDescription>
            {review
              ? `Generated ${new Date(review.generatedAtUtc).toLocaleString()}${
                  review.modelName ? ` · ${review.modelName}` : ''
                }`
              : 'No review has been generated for this period yet.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {review ? (
            <div className="rounded-xl border border-border bg-bg px-4 py-3 text-sm leading-6 text-text-primary whitespace-pre-wrap">
              {review.markdown}
            </div>
          ) : null}
          <div className="flex justify-end">
            <Button type="button" onClick={onGenerate} disabled={generating}>
              {review ? 'Regenerate' : 'Generate review'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({
  icon,
  title,
  trend,
  rows,
}: {
  icon: React.ReactNode;
  title: string;
  trend?: string;
  rows: ReadonlyArray<readonly [string, string]>;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            {icon}
            {title}
          </span>
          {trend ? <Badge variant={trendVariant(trend)}>{trend.replace('_', ' ')}</Badge> : null}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex flex-col">
              <dt className="text-xs text-text-muted">{label}</dt>
              <dd className="font-medium text-text-primary">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
