import {
  MetricComparisonTable,
  type AgeComparison,
  type MetricBaselineRow,
} from '@/components/MetricComparisonTable';
import { OvernightGlance } from '@/components/OvernightGlance';
import { DetailLinkCard } from '@/components/DetailLinkCard';
import { ChronicSuggestionsCard } from '@/components/ChronicSuggestionsCard';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { friendlyDate } from '@/lib/dailyFlow';

/**
 * Last night's sleep read: the metrics-vs-baselines table, the retrospective
 * overnight room glance, and a link into the full morning brief. Shared by
 * Home's "Last night's sleep" section (compact context) and the `/sleep` hub's
 * "Last night" view (Batch 49) — extracted from `DashboardPage` so both render
 * the same piece. The `/sleep` hub renders the full `OvernightChartCard`
 * alongside this body, which already carries the room-verdict badge, so it
 * passes `showOvernightGlance={false}` there to avoid a glance that links to
 * the page it's already on.
 */
export function SleepSnapshotBody({
  metricsVsBaselines,
  ageComparison,
  chronicSuggestions,
  morningBriefLink,
  showOvernightGlance = true,
  holiday,
}: {
  metricsVsBaselines: MetricBaselineRow[];
  ageComparison: AgeComparison | null;
  chronicSuggestions?: DailyLoopData['chronicSuggestions'] | null;
  morningBriefLink: string;
  showOvernightGlance?: boolean;
  /** Batch 121: while away, the retrospective room glance stays dormant, mirroring
   *  Sleep's Last-night "Holiday away" card (Batch 113.3). */
  holiday?: { isActive: boolean; endDate?: string | null };
}) {
  return (
    <div className="space-y-4">
      <MetricComparisonTable rows={metricsVsBaselines} ageComparison={ageComparison} />
      <ChronicSuggestionsCard suggestions={chronicSuggestions} />
      {/* Last night's room read (retrospective) lives with last night's sleep;
          tonight's live fan/bedroom controls stay in the evening card (Batch 35). */}
      {holiday?.isActive ? (
        <div className="rounded-2xl border border-dashed border-border bg-bg px-4 py-4">
          <p className="font-medium text-text-primary">Holiday away</p>
          <p className="mt-1 text-sm text-text-secondary">
            The overnight room read stays dormant while you are away. Resumes{' '}
            {holiday.endDate ? friendlyDate(holiday.endDate) : 'when you are back'}.
          </p>
        </div>
      ) : (
        showOvernightGlance && <OvernightGlance />
      )}
      <DetailLinkCard
        to={morningBriefLink}
        title="Full morning brief"
        description="Open the complete coach read and verdict notes."
      />
    </div>
  );
}
