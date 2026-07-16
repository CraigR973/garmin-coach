import { useEffect } from 'react';
import { Activity, BedDouble, ClipboardCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { BriefFollowUpChat } from '@/components/BriefFollowUpChat';
import { BriefListenControls } from '@/components/BriefListenControls';
import { Markdown } from '@/components/Markdown';
import { MetricComparisonTable } from '@/components/MetricComparisonTable';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { TodayActions } from '@/components/TodayActions';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { markBriefReviewed } from '@/lib/briefReview';
import { formatDateTime, friendlyDate } from '@/lib/dailyFlow';

export function MorningBriefPage() {
  const query = useDailyLoop();

  // Opening the brief completes Home's Batch 96 unviewed-brief CTA (per-day
  // client flag) — gated on a present morning read so a pre-sync visit doesn't
  // mark a brief reviewed before one exists.
  useEffect(() => {
    const loaded = query.data?.data;
    if (loaded?.morningAnalysis != null) {
      markBriefReviewed(loaded.subjectDate);
    }
  }, [query.data]);

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

      {analysis ? (
        <>
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
          <Card>
            <CardContent className="pt-6">
              <BriefFollowUpChat analysisId={analysis.id} />
            </CardContent>
          </Card>
        </>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>No morning brief yet</CardTitle>
            <CardDescription>
              The coach read appears here once today&apos;s morning analysis has run.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );
}
