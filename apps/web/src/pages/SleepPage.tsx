import { useEffect, useMemo, useState } from 'react';
import { format, parseISO, subDays } from 'date-fns';
import { Link } from 'react-router-dom';
import { BedDouble, CalendarDays, ClipboardCheck, Fan, MoonStar } from 'lucide-react';
import { ChronicSuggestionsCard } from '@/components/ChronicSuggestionsCard';
import { DetailLinkCard } from '@/components/DetailLinkCard';
import { MetricComparisonTable } from '@/components/MetricComparisonTable';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';
import { SleepDateCalendar } from '@/components/SleepDateCalendar';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/EmptyState';
import { Tabs } from '@/components/ui/tabs';
import { SleepPrepBody } from '@/components/SleepPrepBody';
import { OvernightChartCard } from '@/components/OvernightChartCard';
import { SleepStageAgeTable } from '@/components/SleepStageAgeTable';
import { GoodMorningCta } from '@/components/GoodMorningCta';
import { BreathworkRhythmCard } from '@/components/BreathworkRhythmCard';
import { hm } from '@/lib/dailyFlow';
import { useDailyLoop, type DailyLoopData } from '@/hooks/useDailyLoop';
import { markSleepReviewed } from '@/lib/sleepReview';
import { friendlyDate } from '@/lib/dailyFlow';
import { verdictBadgeVariant, verdictLabel } from '@/lib/copy';
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
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
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

  useEffect(() => {
    const subjectDate = query.data?.data.subjectDate;
    if (selectedDate == null && subjectDate) {
      setSelectedDate(subjectDate);
    }
  }, [query.data, selectedDate]);

  const loadedData = query.data?.data ?? null;
  const canBrowseHistory = loadedData != null;
  const currentSubjectDate = loadedData?.subjectDate ?? selectedDate ?? '1970-01-02';
  const historySubjectDate = selectedDate ?? loadedData?.subjectDate ?? '1970-01-02';
  const historyQuery = useDailyLoop(historySubjectDate, {
    enabled: canBrowseHistory && historySubjectDate !== currentSubjectDate,
  });
  const historyNight = useMemo(
    () => format(subDays(parseISO(historySubjectDate), 1), 'yyyy-MM-dd'),
    [historySubjectDate],
  );

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
  const holiday = data.holiday;
  const thermal = data.thermalState;
  const breathworkBrief = data.breathworkBrief ?? null;
  const hasTodaySleepAccess = data.manualEntry != null || analysis != null;
  const historyData = historySubjectDate === currentSubjectDate ? data : historyQuery.data?.data;
  const historyLoading = historySubjectDate !== currentSubjectDate && historyQuery.isLoading;
  const historyError = historySubjectDate !== currentSubjectDate ? historyQuery.error : null;
  const historyAnalysis = (historyData?.morningAnalysis ?? null) as typeof analysis;
  const historyMetricsVsBaselines = (historyAnalysis?.metricsVsBaselines ?? []) as MetricBaselineRow[];
  const historyAgeComparison = (historyAnalysis?.ageComparison ?? null) as AgeComparison | null;
  const historyChronicSuggestions = historyData?.chronicSuggestions ?? null;
  const historySleep = historyData?.sleep ?? null;
  const showingHistoricalDate = historySubjectDate !== currentSubjectDate;

  return (
    <div className="space-y-5">
      <PageHeader title="Sleep" eyebrow={friendlyDate(data.subjectDate)} />

      {!hasTodaySleepAccess ? <GoodMorningCta dateLabel={friendlyDate(data.subjectDate)} /> : null}

      {hasTodaySleepAccess ? <Tabs items={VIEW_ITEMS} value={view} onChange={setView} variant="segmented" /> : null}

      {hasTodaySleepAccess || view === 'last-night' ? (
        <>
          {view === 'last-night' || !hasTodaySleepAccess ? (
            <div className="space-y-5">
              <SleepDateCalendar
                selectedDate={historySubjectDate}
                maxDate={currentSubjectDate}
                onSelectDate={setSelectedDate}
              />
              {!hasTodaySleepAccess && !showingHistoricalDate ? (
                <TodaySleepLockedCard subjectDate={data.subjectDate} />
              ) : (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <BedDouble className="h-4 w-4 text-primary" aria-hidden />
                      {showingHistoricalDate ? `Sleep for ${friendlyDate(historySubjectDate)}` : "Last night's sleep"}
                    </CardTitle>
                    <CardDescription>
                      {showingHistoricalDate
                        ? 'Browse the stored sleep read for that date and compare it with the overnight room history below.'
                        : 'How last night compares to your own normal and your age group.'}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {historyLoading ? (
                      <Skeleton className="h-48 w-full rounded-xl" />
                    ) : historyError ? (
                      <p className="text-sm text-text-muted">
                        {historyError instanceof Error ? historyError.message : 'That date could not load just now.'}
                      </p>
                    ) : historyAnalysis ? (
                      <div className="space-y-4">
                        <MetricComparisonTable rows={historyMetricsVsBaselines} ageComparison={historyAgeComparison} />
                        <ChronicSuggestionsCard suggestions={historyChronicSuggestions} />
                        {!showingHistoricalDate ? (
                          <DetailLinkCard
                            to="/brief"
                            title="Full morning brief"
                            description="Open the complete coach read and verdict notes."
                          />
                        ) : null}
                      </div>
                    ) : historySleep ? (
                      <HistoricalSleepFallback sleep={historySleep} />
                    ) : (
                      <p className="text-sm text-text-muted">
                        No stored sleep read was found for that date yet. The overnight room chart below will still show
                        any climate history that exists.
                      </p>
                    )}
                  </CardContent>
                </Card>
              )}
              {showingHistoricalDate && !historyLoading && !historyError ? <HistoricalDayCard data={historyData ?? null} /> : null}
              {historyAnalysis ? (
                <Card>
                  <CardHeader>
                    <CardTitle>Sleep stages vs your age</CardTitle>
                    <CardDescription>
                      Duration and stage balance compared with the typical overnight pattern for your age group.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <SleepStageAgeTable rows={historyAgeComparison?.sleepRows ?? []} ageBand={historyAgeComparison?.ageBand} />
                  </CardContent>
                </Card>
              ) : null}
              {holiday.isActive ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <MoonStar className="h-4 w-4 text-primary" aria-hidden />
                      Holiday away
                    </CardTitle>
                    <CardDescription>The overnight room/fan chart stays dormant while you are away.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-text-secondary">
                      Climate history resumes {friendlyDate(holiday.activeWindow?.endDate ?? data.subjectDate)}.
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <OvernightChartCard night={historyNight} captionDate={historySubjectDate} showPager={false} />
              )}
            </div>
          ) : (
            <div className="space-y-5">
              {holiday.isActive ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <MoonStar className="h-4 w-4 text-primary" aria-hidden />
                      Holiday away
                    </CardTitle>
                    <CardDescription>
                      Tonight&apos;s sleep-prep and bedroom controls stay paused while you are away.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <p className="text-sm text-text-secondary">
                      These wind-down surfaces resume {friendlyDate(holiday.activeWindow?.endDate ?? data.subjectDate)}.
                    </p>
                    <DetailLinkCard
                      to="/holiday"
                      title="Open Holiday"
                      description="Review or resume your holiday window."
                    />
                  </CardContent>
                </Card>
              ) : (
                <>
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <MoonStar className="h-4 w-4 text-primary" aria-hidden />
                        Tonight&apos;s sleep prep
                      </CardTitle>
                      <CardDescription>What tonight's training and drivers mean for your wind-down.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        <SleepPrepBody projection={data.sleepProjection ?? null} />
                        {breathworkBrief ? (
                          <BreathworkRhythmCard
                            brief={breathworkBrief}
                            description="Keep the 20:00 breathing habit with tonight's wind-down, not in the workout card."
                          />
                        ) : null}
                      </div>
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
                        description="Control the fans here; the overnight room chart stays on Sleep."
                      />
                    </CardContent>
                  </Card>
                </>
              )}
            </div>
          )}

          {/* Batch 60: the morning check-in folds into the sleep review as one step
              and is optional — offered here (and in the Today footer), never nagged.
              Logging how he feels can still ease today's ride (DECISIONS #126).
              Batch 114: only offer it before he's actually checked in — once
              `manualEntry` exists the check-in is done, so this card is redundant
              (and, per Batch 97, a brief may still be generating). */}
          {data.manualEntry == null ? (
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
          ) : null}
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

function TodaySleepLockedCard({ subjectDate }: { subjectDate: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BedDouble className="h-4 w-4 text-primary" aria-hidden />
          Today&apos;s sleep
        </CardTitle>
        <CardDescription>
          Today&apos;s sleep detail unlocks after you say good morning. Past dates stay browseable from the calendar.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-2xl border border-dashed border-border px-4 py-4 text-sm text-text-secondary">
          Today is {friendlyDate(subjectDate)}. Check in when you&apos;re ready and the full sleep, verdict, and room
          read will land here.
        </div>
        <Button asChild variant="outline" className="w-full">
          <Link to="/check-in">
            <ClipboardCheck className="h-4 w-4" aria-hidden />
            Morning check-in
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function HistoricalDayCard({ data }: { data: DailyLoopData | null }) {
  if (!data) return null;

  const analysis = data.morningAnalysis;
  const workouts = data.plannedWorkouts ?? [];
  const readCount =
    (data.postWorkoutAnalyses?.length ?? 0) +
    (data.postFlexibilityAnalyses?.length ?? 0) +
    (data.postStrengthAnalyses?.length ?? 0) +
    (data.postWalkAnalyses?.length ?? 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarDays className="h-4 w-4 text-primary" aria-hidden />
          The whole day
        </CardTitle>
        <CardDescription>That date&apos;s verdict and planned sessions, alongside the sleep and room history above.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-2xl border border-border px-4 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-text-primary">Verdict</p>
            <Badge variant={verdictBadgeVariant(analysis?.verdict)}>{verdictLabel(analysis?.verdict)}</Badge>
          </div>
          <p className="mt-2 text-sm text-text-secondary">
            {analysis?.reasons?.[0] ?? 'No stored morning verdict was saved for this date.'}
          </p>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-text-primary">Planned sessions</p>
            {readCount > 0 ? <p className="text-xs text-text-muted">Stored reads: {readCount}</p> : null}
          </div>
          {workouts.length > 0 ? (
            <div className="space-y-2">
              {workouts.map((workout) => (
                <div key={workout.id} className="rounded-xl border border-border px-3 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium text-text-primary">{workout.title}</p>
                    <Badge variant="muted">{prettifyStatus(workout.status)}</Badge>
                  </div>
                  <p className="mt-1 text-sm text-text-secondary">
                    {prettifyType(workout.workoutType)}
                    {workout.plannedDurationMin != null ? ` · ${workout.plannedDurationMin} min` : ''}
                    {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-border px-4 py-4 text-sm text-text-secondary">
              No planned sessions were stored for that date.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function HistoricalSleepFallback({
  sleep,
}: {
  sleep: DailyLoopData['sleep'];
}) {
  if (!sleep) return null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <SleepStat label="Score" value={sleep.score != null ? `${sleep.score}` : '—'} />
        <SleepStat label="Age-adjusted" value={sleep.ageAdjustedScore != null ? `${sleep.ageAdjustedScore}` : '—'} />
        <SleepStat label="Duration" value={hm(sleep.durationSec)} />
        <SleepStat label="Restless moments" value={sleep.restlessMomentsCount != null ? `${sleep.restlessMomentsCount}` : '—'} />
      </div>
      <p className="text-sm leading-6 text-text-secondary">
        Stored sleep data is available for this date even though there is no saved morning brief packet to compare
        against baselines.
        {sleep.sleepStartUtc || sleep.sleepEndUtc
          ? ` ${formatSleepWindow(sleep.sleepStartUtc, sleep.sleepEndUtc)}`
          : ''}
      </p>
    </div>
  );
}

function formatSleepWindow(startUtc: string | null | undefined, endUtc: string | null | undefined): string {
  const formatClock = (value: string | null | undefined) =>
    value
      ? new Date(value).toLocaleTimeString([], {
          hour: 'numeric',
          minute: '2-digit',
        })
      : null;
  const start = formatClock(startUtc);
  const end = formatClock(endUtc);
  if (start && end) return `Sleep window ${start} to ${end}.`;
  if (start) return `Sleep started around ${start}.`;
  if (end) return `Wake time landed around ${end}.`;
  return '';
}

function prettifyType(value: string | null | undefined): string {
  if (!value) return 'Session';
  const cleaned = value.replace(/[_-]+/g, ' ').trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function prettifyStatus(value: string | null | undefined): string {
  if (!value) return 'Planned';
  const cleaned = value.replace(/[_-]+/g, ' ').trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}
