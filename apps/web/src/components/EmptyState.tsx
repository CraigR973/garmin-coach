import type { LucideIcon } from 'lucide-react';
import { CloudOff, Inbox, RefreshCw, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface StateAction {
  label: string;
  onClick: () => void;
}

interface StateCardProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: StateAction;
  className?: string;
}

/** The shared visual shell for on-brand empty/error/offline notices (Batch 55) —
 *  say what happened, then offer one clear recovery action, replacing the
 *  generic "please try again" cards scattered across Home/Sleep/Week/Check-in. */
function StateCard({ icon: Icon, title, description, action, className }: StateCardProps) {
  return (
    <Card className={cn('border-dashed', className)}>
      <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-surface-elevated text-text-secondary">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
        <div className="space-y-1">
          <p className="font-medium text-text-primary">{title}</p>
          {description && <p className="text-sm text-text-secondary">{description}</p>}
        </div>
        {action && (
          <Button type="button" variant="outline" size="sm" onClick={action.onClick}>
            {action.label}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

/** Something failed to load. Always carries a retry action (say what happened,
 *  then how to recover). */
export function ErrorState({
  title = "That didn't load",
  description,
  onRetry,
  retryLabel = 'Try again',
  className,
}: {
  title?: string;
  description?: string;
  onRetry: () => void;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <StateCard
      icon={TriangleAlert}
      title={title}
      description={description}
      action={{ label: retryLabel, onClick: onRetry }}
      className={className}
    />
  );
}

/** Nothing to show yet — not a failure, just no data for this view. The
 *  recovery action is optional since there isn't always something to retry. */
export function EmptyState({
  icon = Inbox,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: StateAction;
  className?: string;
}) {
  return (
    <StateCard icon={icon} title={title} description={description} action={action} className={className} />
  );
}

/** Offline with cached data still on screen — distinct from a hard error. */
export function OfflineNotice({ description }: { description: string }) {
  return (
    <div
      role="status"
      className="flex items-center gap-2 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
    >
      <CloudOff className="h-4 w-4 shrink-0" aria-hidden />
      {description}
    </div>
  );
}

/** Online, but the brief on screen is for an earlier day than today — the
 *  persisted/service-worker cache painted a stale day before a fresh fetch
 *  landed (Batch 138). Unlike {@link OfflineNotice}, this offers a real refresh
 *  that bypasses the cache. */
export function StaleDataNotice({
  description,
  onRefresh,
  isRefreshing = false,
}: {
  description: string;
  onRefresh: () => void;
  isRefreshing?: boolean;
}) {
  return (
    <div
      role="status"
      className="flex items-center gap-2 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
    >
      <RefreshCw
        className={cn('h-4 w-4 shrink-0', isRefreshing && 'animate-spin')}
        aria-hidden
      />
      <span className="flex-1">{description}</span>
      <Button
        variant="ghost"
        size="sm"
        onClick={onRefresh}
        disabled={isRefreshing}
        className="h-auto shrink-0 px-2 py-1 font-medium text-warning hover:bg-warning/20 hover:text-warning"
      >
        {isRefreshing ? 'Refreshing…' : 'Refresh'}
      </Button>
    </div>
  );
}
