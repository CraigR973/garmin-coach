import {
  MetricComparisonTable,
  type AgeComparison,
  type MetricBaselineRow,
} from '@/components/MetricComparisonTable';
import { OvernightGlance } from '@/components/OvernightGlance';
import { DetailLinkCard } from '@/components/DetailLinkCard';
import { ChronicSuggestionsCard } from '@/components/ChronicSuggestionsCard';
import type { DailyLoopData } from '@/hooks/useDailyLoop';

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
}: {
  metricsVsBaselines: MetricBaselineRow[];
  ageComparison: AgeComparison | null;
  chronicSuggestions?: DailyLoopData['chronicSuggestions'] | null;
  morningBriefLink: string;
  showOvernightGlance?: boolean;
}) {
  return (
    <div className="space-y-4">
      <MetricComparisonTable rows={metricsVsBaselines} ageComparison={ageComparison} />
      <ChronicSuggestionsCard suggestions={chronicSuggestions} />
      {/* Last night's room read (retrospective) lives with last night's sleep;
          tonight's live fan/bedroom controls stay in the evening card (Batch 35). */}
      {showOvernightGlance && <OvernightGlance />}
      <DetailLinkCard
        to={morningBriefLink}
        title="Full morning brief"
        description="Open the complete coach read and verdict notes."
      />
    </div>
  );
}
