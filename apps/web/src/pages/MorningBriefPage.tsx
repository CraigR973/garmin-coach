import { useEffect } from 'react';
import { Activity, BedDouble, ClipboardCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { AcutePhysiologyNotice, MedicalBoundaryFooter } from '@/components/AcutePhysiologyNotice';
import { gradedVerdictCopy, REST_DAY_LINE } from '@/lib/copy';
import { restHeadline } from '@/lib/restHeadline';
import { BriefListenControls } from '@/components/BriefListenControls';
import { BriefPendingCta } from '@/components/BriefPendingCta';
import { BriefStatusCard } from '@/components/BriefStatusCard';
import { StaleDataNotice } from '@/components/EmptyState';
import { useRegisterCoachAnchor } from '@/contexts/CoachAnchorContext';
import { Markdown } from '@/components/Markdown';
import { DisputeForm } from '@/components/DisputeForm';
import { ProvenancePanel } from '@/components/ProvenancePanel';
import { MetricComparisonTable } from '@/components/MetricComparisonTable';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { TodayActions } from '@/components/TodayActions';
import { VerdictHero } from '@/components/VerdictHero';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { useDailyLoopFreshness } from '@/hooks/useDailyLoopFreshness';
import { useRetryBrief } from '@/hooks/useRetryBrief';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { markBriefReviewed } from '@/lib/briefReview';
import { friendlyDate, writtenAt } from '@/lib/dailyFlow';
import { briefState, noteUnread, storedMorning } from '@/lib/storedMorning';
import { dayStateForWorkouts } from '@/lib/workoutCategories';
import { dissentFromVerdict, VERDICT_DISSENT_COPY } from '@/lib/disputes';

export function MorningBriefPage() {
  const query = useDailyLoop();
  // Batch 248 (UX241-11): the stale-payload banner Batch 138 built for Home now
  // reaches the page the brief-ready push actually opens. Hooks run before the
  // loading/error early returns so the hook count never changes between renders.
  const isOnline = useOnlineStatus();
  const freshness = useDailyLoopFreshness(query.data?.data, { isOnline });

  // Opening the brief completes Home's Batch 96 unviewed-brief CTA (per-day
  // client flag) — gated on a present morning read so a pre-sync visit doesn't
  // mark a brief reviewed before one exists.
  useEffect(() => {
    const loaded = query.data?.data;
    if (loaded?.morningAnalysis != null) {
      markBriefReviewed(loaded.subjectDate);
    }
  }, [query.data]);

  // Batch 207: no inline chat on this page any more — the app-wide coach
  // anchors to this read instead, so a question asked from the launcher while
  // standing on the brief still arrives attached to it. Registered above the
  // loading/error early returns so the hook count never changes between
  // renders.
  // Batch 302: a morning stored without its brief anchors too; the coach is told
  // its brief did not finish rather than handed an empty one.
  useRegisterCoachAnchor(storedMorning(query.data?.data)?.id);
  const retry = useRetryBrief();

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title="Morning brief" back={{ to: '/', label: 'Home' }} />
        <Skeleton className="h-48 w-full rounded-2xl" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="Morning brief" back={{ to: '/', label: 'Home' }} />
        <Card>
          <CardHeader>
            <CardTitle>Today&apos;s brief couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const data = query.data.data;
  // Batch 302: the colour, the notices and Today's actions come from the stored
  // morning, which exists before its brief is written and when it did not finish.
  const analysis = storedMorning(data);
  const brief = briefState(data);
  const dataSufficiencyLine =
    analysis?.acutePhysiology?.dataSufficiency?.status === 'insufficient_data'
      ? (analysis.acutePhysiology.dataSufficiency.message ?? undefined)
      : undefined;
  const rest = restHeadline(analysis?.acutePhysiology);
  const graded = gradedVerdictCopy(
    analysis?.verdict,
    analysis?.verdictHeld,
    analysis?.verdictEngine,
    analysis?.verdictLightWeekHold,
  );
  // Batch 298: on a rest or holiday day the brief says what Home says. On 1 Oct's
  // holiday it said "Ease the hard work" while Home said the day was for recovery.
  const restOrHoliday = dayStateForWorkouts(data.plannedWorkouts).isRest || data.holiday.isActive;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Morning brief"
        eyebrow={friendlyDate(data.subjectDate)}
        back={{ to: '/', label: 'Home' }}
        action={
          <Button asChild size="sm">
            <Link to="/check-in">
              <ClipboardCheck className="mr-2 h-4 w-4" aria-hidden />
              Check in
            </Link>
          </Button>
        }
      />

      {freshness.isStale && (
        <StaleDataNotice
          description={`Showing ${friendlyDate(data.subjectDate)}'s brief — refresh for today's.`}
          onRefresh={freshness.refresh}
          isRefreshing={freshness.isRefreshing}
        />
      )}

      {analysis ? (
        <>
          <VerdictHero
            verdict={analysis.verdict}
            label={rest?.label ?? graded.label}
            line={dataSufficiencyLine ?? rest?.line ?? (restOrHoliday ? REST_DAY_LINE : graded.line)}
          />
          {/* Batch 274: disagreement is recorded beside the day and changes nothing. */}
          <div className="px-1">
            <DisputeForm
              copy={VERDICT_DISSENT_COPY}
              onSubmit={async (reason) => {
                await dissentFromVerdict(data.subjectDate, reason);
              }}
            />
          </div>
          <AcutePhysiologyNotice boundary={analysis.acutePhysiology} />
          <TodayActions actions={analysis.todayActions} workouts={data.plannedWorkouts} />
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BedDouble className="h-4 w-4 text-primary" aria-hidden />
                Last night&apos;s metrics
              </CardTitle>
            </CardHeader>
            <CardContent>
              <MetricComparisonTable
                rows={analysis.metricsVsBaselines}
                ageComparison={analysis.ageComparison}
              />
            </CardContent>
          </Card>
          {brief === 'written' ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-primary" aria-hidden />
                  Coach read
                </CardTitle>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <CardDescription>
                    {/* Batch 302: when the brief was written, which after an outage can be
                        hours after the morning was graded. */}
                    {writtenAt(analysis.briefWrittenAtUtc ?? analysis.generatedAtUtc, {
                      timeZone: data.timezone,
                    }) ?? 'Not synced'}
                  </CardDescription>
                  <BriefListenControls markdown={analysis.outputMarkdown} hostedTtsConsent={data.hostedTtsConsent} />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <Markdown>{analysis.outputMarkdown}</Markdown>
                <ProvenancePanel
                  sources={[
                    analysis.thermalReview?.provenance,
                    analysis.acutePhysiology?.overnightHrv?.provenance,
                  ]}
                  timeZone={data.timezone}
                  analysisId={analysis.id}
                />
              </CardContent>
            </Card>
          ) : (
            // Batch 302: the colour and the plan above are complete; only the written
            // brief is missing, and this says where it is.
            <BriefStatusCard
              state={brief === 'failed' ? 'failed' : 'writing'}
              noteUnread={noteUnread(analysis)}
              onRetry={freshness.isStale ? undefined : () => retry.mutate(data.subjectDate)}
              retrying={retry.isPending}
            />
          )}
          <MedicalBoundaryFooter boundary={analysis.acutePhysiology} />
        </>
      ) : (
        // Batch 248 (UX241-02): this was one "No morning brief yet" card for all
        // three pre-brief states — failed, generating and not-checked-in rendered
        // byte-identically on the page the brief-ready push opens. The same
        // component Home uses now decides, so the two cannot drift apart again.
        <BriefPendingCta daily={data} />
      )}
    </div>
  );
}
