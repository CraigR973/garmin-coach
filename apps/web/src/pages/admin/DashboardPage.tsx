import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { apiFetch } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SyncStatus {
  last_sync_at: string | null;
  last_sync_action: string | null;
  next_run_at: string | null;
  recent_errors: { id: string; action_type: string; timestamp: string }[];
}

interface UpcomingLock {
  match_id: string;
  match_number: number;
  kickoff_utc: string;
  home_team: string | null;
  away_team: string | null;
  minutes_until_lock: number;
}

interface PendingMatch {
  match_id: string;
  match_number: number;
  status: string;
  kickoff_utc: string;
  home_team: string | null;
  away_team: string | null;
}

interface AuditEntry {
  id: string;
  action_type: string;
  actor_type: string;
  timestamp: string;
  target_table: string;
}

interface Dashboard {
  active_players: number;
  upcoming_locks: UpcomingLock[];
  pending_result_matches: PendingMatch[];
  recent_audit: AuditEntry[];
  sync_status: SyncStatus;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function syncActionLabel(action: string | null): string {
  const map: Record<string, string> = {
    result_auto_fetched: 'OK',
    sync_failed: 'Failed',
    kickoff_changed: 'Kickoff updated',
    sync_triggered: 'Manual OK',
  };
  return action ? (map[action] ?? action) : 'Never run';
}

function syncBadgeVariant(action: string | null): 'success' | 'error' | 'muted' {
  if (!action) return 'muted';
  if (action === 'sync_failed') return 'error';
  return 'success';
}

function auditActionLabel(action: string): string {
  const map: Record<string, string> = {
    result_auto_fetched: 'Result auto-fetched',
    result_manual_entered: 'Result entered',
    result_overridden: 'Result overridden',
    match_postponed: 'Match postponed',
    match_rescheduled: 'Match rescheduled',
    match_cancelled: 'Match cancelled',
    kickoff_changed: 'Kickoff changed',
    predictions_locked: 'Predictions locked',
    player_removed: 'Player removed',
    player_pin_reset: 'PIN reset',
    invite_created: 'Invite created',
    invite_revoked: 'Invite revoked',
    sync_triggered: 'Sync triggered',
    sync_failed: 'Sync failed',
  };
  return map[action] ?? action;
}

// ---------------------------------------------------------------------------
// Widget components
// ---------------------------------------------------------------------------

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted mb-2">{label}</div>
        <div className="font-mono text-3xl font-semibold text-primary tabular-nums leading-none">{value}</div>
        {sub && <div className="text-xs font-sans text-text-muted mt-2">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function SyncWidget({ sync }: { sync: SyncStatus }) {
  const hasErrors = sync.recent_errors.length > 0;
  return (
    <Card className={hasErrors ? 'border-error/50' : ''}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted">Auto sync</span>
          <Badge variant={syncBadgeVariant(sync.last_sync_action)}>
            {syncActionLabel(sync.last_sync_action)}
          </Badge>
        </div>
        <div className="text-xs font-sans text-text-muted space-y-1">
          <div>
            Last run:{' '}
            <span className="text-text-primary">
              {sync.last_sync_at
                ? formatInTimeZone(new Date(sync.last_sync_at), 'UTC', 'HH:mm:ss') + ' UTC'
                : '—'}
            </span>
          </div>
          {sync.next_run_at && (
            <div>
              Next:{' '}
              <span className="text-text-primary">
                {formatInTimeZone(new Date(sync.next_run_at), 'UTC', 'HH:mm:ss')} UTC
              </span>
            </div>
          )}
          {hasErrors && (
            <div className="text-error font-medium">
              {sync.recent_errors.length} recent error{sync.recent_errors.length !== 1 ? 's' : ''}
            </div>
          )}
        </div>
        <Link to="/admin/sync" className="mt-3 block text-xs font-sans text-primary hover:underline">
          Manage sync →
        </Link>
      </CardContent>
    </Card>
  );
}

function UpcomingLocksWidget({ locks }: { locks: UpcomingLock[] }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted mb-3">
          Upcoming locks (24h)
        </div>
        {locks.length === 0 ? (
          <p className="text-text-muted text-xs font-sans">No matches locking in the next 24 hours.</p>
        ) : (
          <div className="space-y-2">
            {locks.map((m) => (
              <div key={m.match_id} className="flex items-center justify-between gap-2 text-sm">
                <span className="font-sans text-text-primary truncate">
                  {m.home_team ?? '?'} vs {m.away_team ?? '?'}
                </span>
                <Badge variant="warning" className="shrink-0">
                  {m.minutes_until_lock < 60
                    ? `${m.minutes_until_lock}m`
                    : `${Math.round(m.minutes_until_lock / 60)}h`}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PendingResultsWidget({ matches }: { matches: PendingMatch[] }) {
  return (
    <Card className={matches.length > 0 ? 'border-warning/40' : ''}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted">
            Pending results
          </span>
          {matches.length > 0 && (
            <Badge variant="warning">{matches.length}</Badge>
          )}
        </div>
        {matches.length === 0 ? (
          <p className="text-text-muted text-xs font-sans">No locked/live matches awaiting results.</p>
        ) : (
          <div className="space-y-2">
            {matches.map((m) => (
              <div key={m.match_id} className="flex items-center justify-between gap-2 text-sm">
                <span className="font-sans text-text-primary truncate">
                  #{m.match_number} · {m.home_team ?? '?'} vs {m.away_team ?? '?'}
                </span>
                <Badge variant={m.status === 'live' ? 'live' : 'warning'} className="shrink-0 capitalize">
                  {m.status}
                </Badge>
              </div>
            ))}
          </div>
        )}
        {matches.length > 0 && (
          <Link to="/admin/results" className="mt-3 block text-xs font-sans text-primary hover:underline">
            Enter results →
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

function RecentAuditWidget({ entries }: { entries: AuditEntry[] }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted mb-3">
          Recent activity
        </div>
        {entries.length === 0 ? (
          <p className="text-text-muted text-xs font-sans">No audit entries yet.</p>
        ) : (
          <div className="space-y-2">
            {entries.map((e) => (
              <div key={e.id} className="flex items-center justify-between gap-2">
                <span className="text-xs font-sans text-text-secondary truncate">
                  {auditActionLabel(e.action_type)}
                </span>
                <span className="text-xs font-mono text-text-muted shrink-0">
                  {formatInTimeZone(new Date(e.timestamp), 'UTC', 'HH:mm')}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function AdminDashboardPage() {
  const { data, isLoading, error } = useQuery<Dashboard>({
    queryKey: ['admin', 'dashboard'],
    queryFn: () => apiFetch<Dashboard>('/api/v1/admin/dashboard'),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  return (
    <div>
      <PageHeader title="Admin" eyebrow="Dashboard" />

      {error && (
        <div className="mb-4">
          <EmptyState
            title="Couldn't load admin dashboard"
            description="Try refreshing the page."
          />
        </div>
      )}

      {isLoading && !data && (
        <div className="space-y-4 mb-6" aria-label="Loading admin dashboard">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-[88px]" />
            ))}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[140px]" />
            ))}
          </div>
        </div>
      )}

      {data && (
        <>
          {/* Top stats */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
            <StatCard
              label="ACTIVE PLAYERS"
              value={data.active_players}
            />
            <StatCard
              label="UPCOMING LOCKS"
              value={data.upcoming_locks.length}
              sub="next 24 hours"
            />
            <StatCard
              label="PENDING RESULTS"
              value={data.pending_result_matches.length}
              sub="locked/live, no result"
            />
          </div>

          {/* Widgets grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <SyncWidget sync={data.sync_status} />
            <UpcomingLocksWidget locks={data.upcoming_locks} />
            <PendingResultsWidget matches={data.pending_result_matches} />
            <RecentAuditWidget entries={data.recent_audit} />
          </div>
        </>
      )}

      {/* Admin nav links */}
      <h2 className="text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted mb-3">Manage</h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { to: '/admin/sync', label: 'Sync' },
          { to: '/admin/results', label: 'Results' },
          { to: '/admin/players', label: 'Players' },
          { to: '/admin/invites', label: 'Invites' },
          { to: '/admin/all-leagues', label: 'All Leagues' },
        ].map(({ to, label }) => (
          <Link
            key={to}
            to={to}
            className="block p-3 rounded-lg border border-border bg-surface hover:bg-surface-elevated transition-colors text-center press-down focus-visible:outline-none focus-visible:shadow-glow"
          >
            <p className="font-sans text-sm font-semibold text-text-primary tracking-tight">{label}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
