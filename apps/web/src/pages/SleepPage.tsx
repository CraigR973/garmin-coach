import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BedDouble, ClipboardCheck, Fan, MoonStar } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/EmptyState';
import { Tabs } from '@/components/ui/tabs';
import { DetailLinkCard } from '@/components/DetailLinkCard';
import { SleepSnapshotBody } from '@/components/SleepSnapshotBody';
import { SleepPrepBody } from '@/components/SleepPrepBody';
import { OvernightChartCard } from '@/components/OvernightChartCard';
import { SleepStageAgeTable } from '@/components/SleepStageAgeTable';
import { GoodMorningCta } from '@/components/GoodMorningCta';
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
 * projection + bedroom summary (tonight, prospective). Batch 101 moves the
 * growing control surface to the dedicated Climate tab while keeping the sleep
 * context here. No new data — reads the same `/api/v1/daily-loop` +
 * `/api/v1/bedroom/overnight` queries the Home sections already use.
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
  const hasSleepAccess = data.manualEntry != null || analysis != null;

  return (
    <div className="space-y-5">
      <PageHeader title="Sleep" eyebrow={friendlyDate(data.subjectDate)} />

      {!hasSleepAccess ? <GoodMorningCta dateLabel={friendlyDate(data.subjectDate)} /> : null}

      {hasSleepAccess ? <Tabs items={VIEW_ITEMS} value={view} onChange={setView} variant="segmented" /> : null}

      {hasSleepAccess ? (
        <>
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
                    Bedroom climate
                  </CardTitle>
                  <CardDescription>
                    Keep the thermal context here, then jump to Climate when you need the full controls.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                    <SleepStat
                      label="Indoor now"
                      value={thermal.latestTemperatureC != null ? `${thermal.latestTemperatureC.toFixed(1)}°C` : 'Not synced'}
                    />
                    <SleepStat
                      label="Thermostat"
                      value={thermal.targetTemperatureC != null ? `${thermal.targetTemperatureC.toFixed(1)}°C` : '—'}
                    />
                    <SleepStat
                      label="Overnight low"
                      value={thermal.overnightLowC != null ? `${thermal.overnightLowC.toFixed(1)}°C` : '—'}
                    />
                    <SleepStat
                      label="Wind"
                      value={thermal.overnightWindMaxMph != null ? `${thermal.overnightWindMaxMph.toFixed(0)} mph` : '—'}
                    />
                  </div>
                  <DetailLinkCard
                    to="/environment"
                    title="Open Climate"
                    description="Control the fans and see the full overnight room chart."
                  />
                </CardContent>
              </Card>
            </div>
          )}

          {/* Batch 60: the morning check-in folds into the sleep review as one step
              and is optional — offered here (and in the Today footer), never nagged.
              Logging how he feels can still ease today's ride (DECISIONS #126). */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ClipboardCheck className="h-4 w-4 text-primary" aria-hidden />
                Add today&apos;s check-in
              </CardTitle>
              <CardDescription>
                Optional — logging how you feel, plus any BP or notes, sharpens the coach&apos;s read and can
                ease today&apos;s ride.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild variant="outline" className="w-full">
                <Link to="/check-in">
                  <ClipboardCheck className="h-4 w-4" aria-hidden />
                  Morning check-in
                </Link>
              </Button>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

function SleepStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border px-3 py-3">
      <p className="text-xs text-text-muted">{label}</p>
      <p className="text-lg font-semibold text-text-primary">{value}</p>
    </div>
  );
}
