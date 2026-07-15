import { Fan, MoonStar, Thermometer } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/EmptyState';
import { BedroomBody } from '@/components/BedroomBody';
import { DetailLinkCard } from '@/components/DetailLinkCard';
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
  const holiday = data.holiday;

  if (holiday.isActive) {
    return (
      <div className="space-y-5">
        <PageHeader title="Climate" eyebrow={friendlyDate(data.subjectDate)} />
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MoonStar className="h-4 w-4 text-primary" aria-hidden />
              Holiday away
            </CardTitle>
            <CardDescription>
              The room read and fan controls stay dormant while you are away.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-text-secondary">
              Climate resumes{' '}
              {holiday.activeWindow?.endDate ? friendlyDate(holiday.activeWindow.endDate) : 'when you are back'}.
            </p>
            <DetailLinkCard
              to="/holiday"
              title="Open Holiday"
              description="Review or resume your holiday window."
            />
          </CardContent>
        </Card>
      </div>
    );
  }

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
            The canonical live room read and fan controls for the bedroom.
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
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MoonStar className="h-4 w-4 text-primary" aria-hidden />
            Last night
          </CardTitle>
          <CardDescription>
            The retrospective overnight room and fan chart lives with Sleep, not the live Climate controls.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DetailLinkCard
            to="/sleep"
            title="Review last night in Sleep"
            description="Open Sleep for the retrospective overnight room, fan, and sleep chart."
          />
        </CardContent>
      </Card>
    </div>
  );
}
