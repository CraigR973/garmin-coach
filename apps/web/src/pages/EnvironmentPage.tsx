import { Fan, Thermometer } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/EmptyState';
import { BedroomBody } from '@/components/BedroomBody';
import { OvernightChartCard } from '@/components/OvernightChartCard';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { friendlyDate } from '@/lib/dailyFlow';

/** Batch 101: the dedicated home for the growing room/fan surface. */
export function EnvironmentPage() {
  const query = useDailyLoop();

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title="Climate" />
        <Skeleton className="h-40 w-full rounded-2xl" />
        <Skeleton className="h-80 w-full rounded-2xl" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="Climate" />
        <ErrorState
          title="Climate data couldn't load"
          description={query.error instanceof Error ? query.error.message : "We couldn't reach the server just now."}
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }

  const data = query.data.data;

  return (
    <div className="space-y-5">
      <PageHeader title="Climate" eyebrow={friendlyDate(data.subjectDate)} />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Thermometer className="h-4 w-4 text-primary" aria-hidden />
            Bedroom climate
          </CardTitle>
          <CardDescription>
            The live room read, overnight weather, and the fan controls that run the bedroom.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <BedroomBody thermal={data.thermalState} variant="full" />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Fan className="h-4 w-4 text-primary" aria-hidden />
            Auto mode
          </CardTitle>
          <CardDescription>
            The overnight autopilot follows the room temperature and winds down in the morning.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-text-secondary">
          Manual controls always work. Using one turns the overnight autopilot off until you switch it
          back on.
        </CardContent>
      </Card>

      <OvernightChartCard />
    </div>
  );
}
