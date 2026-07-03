import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

/** A tappable card that links through to a deeper detail page. Extracted from
 *  `DashboardPage` (Batch 49) so it can be shared with the `/sleep` hub. */
export function DetailLinkCard({
  to,
  title,
  description,
}: {
  to: string;
  title: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className="flex items-center justify-between rounded-xl border border-border bg-bg px-4 py-4 transition hover:border-accent/40 hover:bg-panel"
    >
      <div>
        <p className="font-medium text-text-primary">{title}</p>
        <p className="mt-1 text-sm text-text-secondary">{description}</p>
      </div>
      <ChevronRight className="h-4 w-4 text-text-muted" aria-hidden />
    </Link>
  );
}
