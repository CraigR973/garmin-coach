import { Link } from 'react-router-dom';
import { ChevronRight, LineChart } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useBedroomOvernight } from '@/hooks/useBedroomOvernight';
import { overnightGlanceText } from '@/lib/dailyFlow';
import { verdictBadgeVariant, verdictToneLabel } from '@/lib/copy';

/** One-line last-night room/fan glance, shown in the morning brief alongside last
 *  night's sleep (Batch 31) — it explains *last* night, not tonight's live fan state,
 *  so it belongs with the morning read rather than the evening bedroom card.
 *  Fetches the last completed night (shared cache with `/sleep`) and stays silent
 *  until there's something to say, so Home never shows a spinner for it. Extracted
 *  from `DashboardPage` (Batch 49) so `/sleep` can render the same glance. */
export function OvernightGlance() {
  const query = useBedroomOvernight();
  const summary = query.data?.data.summary;
  const glance = overnightGlanceText(summary);
  if (!glance) return null;
  return (
    <Link
      to="/sleep"
      className="flex items-center justify-between gap-2 rounded-xl border border-border bg-bg px-3 py-2.5 text-sm transition hover:border-accent/40"
    >
      <span className="flex items-center gap-2 text-text-secondary">
        <LineChart className="h-4 w-4 shrink-0 text-primary" aria-hidden />
        {summary ? (
          <Badge
            variant={verdictBadgeVariant(summary.roomVerdict)}
            className="shrink-0"
            data-testid="overnight-room-verdict-badge"
          >
            {verdictToneLabel(summary.roomVerdict)}
          </Badge>
        ) : null}
        {glance}
      </span>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
    </Link>
  );
}
