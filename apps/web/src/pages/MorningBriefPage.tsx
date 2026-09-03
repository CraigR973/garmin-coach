import { useEffect } from 'react';
import { Activity, BedDouble, ClipboardCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { AcutePhysiologyNotice, MedicalBoundaryFooter } from '@/components/AcutePhysiologyNotice';
import { BriefListenControls } from '@/components/BriefListenControls';
import { BriefPendingCta } from '@/components/BriefPendingCta';
import { StaleDataNotice } from '@/components/EmptyState';
import { useRegisterCoachAnchor } from '@/contexts/CoachAnchorContext';
import { Markdown } from '@/components/Markdown';
import { MetricComparisonTable } from '@/components/MetricComparisonTable';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { TodayActions } from '@/components/TodayActions';
import { VerdictHero } from '@/components/VerdictHero';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { useDailyLoopFreshness } from '@/hooks/useDailyLoopFreshness';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { markBriefReviewed } from '@/lib/briefReview';
import { formatDateTime, friendlyDate } from '@/lib/dailyFlow';

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
  useRegisterCoachAnchor(query.data?.data.morningAnalysis?.id);

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
  const analysis = data.morningAnalysis;
  const dataSufficiencyLine =
    analysis?.acutePhysiology?.dataSufficiency?.status === 'insufficient_data'
      ? (analysis.acutePhysiology.dataSufficiency.message ?? undefined)
      : undefined;
  const requiresBikeRest = analysis?.acutePhysiology?.requiresBikeRest === true;

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
            label={requiresBikeRest ? 'Take today off the bike' : undefined}
            line={
              dataSufficiencyLine ??
              (requiresBikeRest ? 'An acute recovery signal rules out riding today.' : undefined)
            }
          />
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
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-primary" aria-hidden />
                Coach read
              </CardTitle>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <CardDescription>Generated {formatDateTime(analysis.generatedAtUtc)}</CardDescription>
                <BriefListenControls markdown={analysis.outputMarkdown} hostedTtsConsent={data.hostedTtsConsent} />
              </div>
            </CardHeader>
            <CardContent>
              <Markdown>{analysis.outputMarkdown}</Markdown>
            </CardContent>
          </Card>
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
