import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { reviewEnvelopeSchema } from '@coach/shared';
import { Activity, BedDouble, Dumbbell, FileText, HeartPulse, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { FeedbackControl } from '@/components/FeedbackControl';
import { Markdown } from '@/components/Markdown';
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

function trendLabel(trend: string): string {
  switch (trend) {
    case 'increasing':
      return 'Improving';
    case 'decreasing':
      return 'Slipping';
    case 'stable':
      return 'Steady';
    case 'insufficient_data':
      return 'Not enough data';
    default:
      return trend.replace(/_/g, ' ');
  }
}

function fmt(value: number | null, suffix = ''): string {
  return value === null ? '—' : `${value}${suffix}`;
}

function sourceLabel(value: string): string {
  return value.replace(/_/g, ' ');
}

function trendEvidenceLabel(evidence: ReviewEnvelope['data']['rollup']['sleep']['trendEvidence']): string {
  if (evidence.firstHalfMean === null || evidence.secondHalfMean === null) {
    return `${evidence.firstHalfCount}+${evidence.secondHalfCount} samples`;
  }
  const delta = evidence.delta === null ? '' : ` (${evidence.delta > 0 ? '+' : ''}${evidence.delta})`;
  return `${evidence.firstHalfMean} → ${evidence.secondHalfMean}${delta}`;
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
      <PageHeader title="Reviews" />

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
  const planSourceNote = rollup.adherence.zeroInterpretation;
  const strengthSourceNote = strength.zeroInterpretation ?? strength.trendReason;

  return (
    <div className="space-y-4">
      <Card className="bg-surface-elevated/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" aria-hidden />
            {data.period === 'weekly' ? 'This week' : 'This month'}
          </CardTitle>
          <CardDescription>
            {formatDate(data.periodStart)} – {formatDate(data.periodEnd)} · {data.dayCount} days at a glance.
            {' '}Coverage is {sourceLabel(rollup.coverage.coverageStatus)}: {rollup.coverage.sleepNights}/
            {rollup.coverage.expectedDays} sleep nights and {rollup.coverage.recoveryDays}/
            {rollup.coverage.expectedDays} recovery days.
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
            ['Coverage', `${rollup.coverage.sleepNights}/${rollup.coverage.expectedDays}`],
            ['Avg score', fmt(rollup.sleep.avgScore)],
            ['Trend basis', trendEvidenceLabel(rollup.sleep.trendEvidence)],
          ]}
        />
        <SummaryCard
          icon={<HeartPulse className="h-4 w-4 text-primary" aria-hidden />}
          title="Recovery"
          trend={rollup.recovery.trend}
          rows={[
            ['Days', String(rollup.recovery.days)],
            ['Coverage', `${rollup.coverage.recoveryDays}/${rollup.coverage.expectedDays}`],
            ['Avg HRV', fmt(rollup.recovery.avgHrvMs, ' ms')],
            ['Readiness trend', trendEvidenceLabel(rollup.recovery.trendEvidence)],
          ]}
        />
        <SummaryCard
          icon={<Activity className="h-4 w-4 text-primary" aria-hidden />}
          title="Training load"
          rows={[
            ['Activities', String(rollup.trainingLoad.activityCount)],
            ['Total load', fmt(rollup.trainingLoad.totalLoad)],
            ['Total time', fmt(rollup.trainingLoad.totalDurationMin, ' min')],
            ['Plan source', sourceLabel(rollup.adherence.sourceState)],
            [
              'Verdicts',
              `${rollup.verdicts.green}G · ${rollup.verdicts.amber}A · ${rollup.verdicts.red}R`,
            ],
          ]}
          note={planSourceNote ?? undefined}
        />
        <SummaryCard
          icon={<Dumbbell className="h-4 w-4 text-primary" aria-hidden />}
          title="Strength & signals"
          trend={strength.trend}
          rows={[
            ['Sessions (4w)', String(strength.sessions4w)],
            ['Per week (4w)', String(strength.sessionsPerWeek4w)],
            ['Source', sourceLabel(strength.sourceState)],
            ['Fitness trend', insights.ftpDriftStatus],
          ]}
          note={strengthSourceNote}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            Written review
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
            <div className="space-y-3 rounded-xl border border-border bg-bg px-4 py-3">
              <Markdown>{review.markdown}</Markdown>
              <FeedbackControl
                analysisId={review.analysisId}
                kind="summary"
                feedback={review.feedback ?? null}
              />
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
  note,
}: {
  icon: React.ReactNode;
  title: string;
  trend?: string;
  rows: ReadonlyArray<readonly [string, string]>;
  note?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            {icon}
            {title}
          </span>
          {trend ? <Badge variant={trendVariant(trend)}>{trendLabel(trend)}</Badge> : null}
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
        {note ? <p className="mt-3 text-xs leading-relaxed text-text-muted">{note}</p> : null}
      </CardContent>
    </Card>
  );
}
