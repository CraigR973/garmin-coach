import { Activity } from 'lucide-react';
import { MetricsBaselineTable, type MetricBaselineRow } from '@/components/MetricsBaselineTable';
import { PageHeader } from '@/components/PageHeader';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { friendlyDate } from '@/lib/dailyFlow';

export function BaselinesPage() {
  const query = useDailyLoop();

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title="Baselines" back={{ to: '/', label: 'Home' }} />
        <Skeleton className="h-48 w-full rounded-2xl" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="Baselines" back={{ to: '/', label: 'Home' }} />
        <Card>
          <CardHeader>
            <CardTitle>Baselines couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const data = query.data.data;
  const rows = (data.morningAnalysis?.metricsVsBaselines ?? []) as MetricBaselineRow[];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Baselines"
        eyebrow={friendlyDate(data.subjectDate)}
        back={{ to: '/', label: 'Home' }}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" aria-hidden />
            Metrics vs your baselines
          </CardTitle>
          <CardDescription>How last night compares with your own normal range.</CardDescription>
        </CardHeader>
        <CardContent>
          <MetricsBaselineTable rows={rows} />
        </CardContent>
      </Card>
    </div>
  );
}
