import { useEffect, useState } from 'react';
import { BedDouble, Fan, MoonStar } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/EmptyState';
import { Tabs } from '@/components/ui/tabs';
import { SleepSnapshotBody } from '@/components/SleepSnapshotBody';
import { SleepPrepBody } from '@/components/SleepPrepBody';
import { BedroomBody } from '@/components/BedroomBody';
import { OvernightChartCard } from '@/components/OvernightChartCard';
import { SleepStageAgeTable } from '@/components/SleepStageAgeTable';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { markSleepReviewed } from '@/lib/sleepReview';
import { friendlyDate } from '@/lib/dailyFlow';
import type { AgeComparison, MetricBaselineRow } from '@/components/MetricComparisonTable';

type SleepView = 'last-night' | 'tonight';

const VIEW_ITEMS = [
  { value: 'last-night' as const, label: 'Last night' },
  { value: 'tonight' as const, label: 'Tonight' },
];

/**
 * The sleep loop's nav home (Batch 49): a Last night | Tonight split composing
 * surfaces that already exist elsewhere — the morning metrics table + overnight
 * room glance/chart (last night, retrospective) and the evening sleep
 * projection + live bedroom/fan controls (tonight, prospective). Absorbs the
 * retired `/bedroom` page. No new data — reads the same `/api/v1/daily-loop`
 * + `/api/v1/bedroom/overnight` queries the Home sections already use.
 */
export function SleepPage() {
  const [view, setView] = useState<SleepView>('last-night');
  const query = useDailyLoop();

  // Opening Sleep with synced overnight metrics completes Home's morning
  // "Review last night's sleep" rung (per-day client flag) so it steps down to
  // the check-in. Gated on a present morning read: opening pre-sync (nothing to
  // review) must not pre-empt the prompt once metrics land the same day.
  useEffect(() => {
    const loaded = query.data?.data;
    if (loaded?.morningAnalysis != null) {
      markSleepReviewed(loaded.subjectDate);
    }
  }, [query.data]);

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title="Sleep" />
        <Skeleton className="h-10 w-48 rounded-md" />
        <Skeleton className="h-48 w-full rounded-2xl" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="Sleep" />
        <ErrorState
          title="Sleep data couldn't load"
          description={query.error instanceof Error ? query.error.message : "We couldn't reach the server just now."}
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }

  const data = query.data.data;
  const analysis = data.morningAnalysis;
  const metricsVsBaselines = (analysis?.metricsVsBaselines ?? []) as MetricBaselineRow[];
  const ageComparison = (analysis?.ageComparison ?? null) as AgeComparison | null;
  const chronicSuggestions = data.chronicSuggestions ?? null;
  const thermal = data.thermalState;

  return (
    <div className="space-y-5">
      <PageHeader title="Sleep" eyebrow={friendlyDate(data.subjectDate)} />

      <Tabs items={VIEW_ITEMS} value={view} onChange={setView} variant="segmented" />

      {view === 'last-night' ? (
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BedDouble className="h-4 w-4 text-primary" aria-hidden />
                Last night&apos;s sleep
              </CardTitle>
              <CardDescription>How last night compares to your own normal and your age group.</CardDescription>
            </CardHeader>
            <CardContent>
              <SleepSnapshotBody
                metricsVsBaselines={metricsVsBaselines}
                ageComparison={ageComparison}
                chronicSuggestions={chronicSuggestions}
                morningBriefLink="/brief"
                showOvernightGlance={false}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Sleep stages vs your age</CardTitle>
              <CardDescription>
                Duration and stage balance compared with the typical overnight pattern for your age
                group.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SleepStageAgeTable rows={ageComparison?.sleepRows ?? []} ageBand={ageComparison?.ageBand} />
            </CardContent>
          </Card>
          <OvernightChartCard />
        </div>
      ) : (
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MoonStar className="h-4 w-4 text-primary" aria-hidden />
                Tonight&apos;s sleep prep
              </CardTitle>
              <CardDescription>What tonight's training and drivers mean for your wind-down.</CardDescription>
            </CardHeader>
            <CardContent>
              <SleepPrepBody projection={data.sleepProjection ?? null} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Fan className="h-4 w-4 text-primary" aria-hidden />
                Bedroom &amp; fan
              </CardTitle>
              <CardDescription>
                When the autopilot is on, the fan runs itself overnight from the room temperature.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <BedroomBody thermal={thermal} variant="full" />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
