import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { apiFetch } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';

interface AuditEntry {
  id: string;
  action_type: string;
  timestamp: string;
  changes: Record<string, unknown> | null;
}

interface SyncStatus {
  last_sync_at: string | null;
  last_sync_action: string | null;
  next_run_at: string | null;
  recent_errors: AuditEntry[];
}

function actionBadgeVariant(action: string | null): 'success' | 'error' | 'muted' {
  if (!action) return 'muted';
  if (action === 'sync_failed') return 'error';
  return 'success';
}

function actionLabel(action: string | null): string {
  const map: Record<string, string> = {
    result_auto_fetched: 'Results fetched',
    sync_failed: 'Sync failed',
    kickoff_changed: 'Kickoff updated',
    sync_triggered: 'Sync OK',
  };
  return action ? (map[action] ?? action) : '—';
}

function useCountdown(targetIso: string | null): string {
  const [label, setLabel] = useState('—');

  useEffect(() => {
    if (!targetIso) { setLabel('—'); return; }
    function calc() {
      const diff = Math.max(0, Math.floor((new Date(targetIso!).getTime() - Date.now()) / 1000));
      if (diff === 0) { setLabel('Now'); return; }
      const m = Math.floor(diff / 60);
      const s = diff % 60;
      setLabel(m > 0 ? `${m}m ${s}s` : `${s}s`);
    }
    calc();
    const id = setInterval(calc, 1000);
    return () => clearInterval(id);
  }, [targetIso]);

  return label;
}

export function SyncStatusWidget() {
  const { data, isLoading } = useQuery<SyncStatus>({
    queryKey: ['admin', 'sync-status'],
    queryFn: () => apiFetch<SyncStatus>('/api/v1/admin/sync/status'),
    refetchInterval: 30_000,
  });

  const countdown = useCountdown(data?.next_run_at ?? null);

  if (isLoading) return <Skeleton className="h-[140px]" aria-label="Loading sync status" />;

  const hasErrors = (data?.recent_errors.length ?? 0) > 0;

  return (
    <Card className={hasErrors ? 'border-error/50' : ''}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="font-mono text-xs uppercase tracking-[0.25em] text-text-secondary">Auto sync</span>
          <Badge variant={actionBadgeVariant(data?.last_sync_action ?? null)}>
            {actionLabel(data?.last_sync_action ?? null)}
          </Badge>
        </div>
        <div className="text-xs font-sans text-text-muted space-y-1">
          <div>
            Last run:{' '}
            <span className="text-text-primary">
              {data?.last_sync_at
                ? formatInTimeZone(new Date(data.last_sync_at), 'UTC', 'HH:mm:ss')
                : '—'}
            </span>
          </div>
          <div>
            Next run: <span className="text-text-primary">{countdown}</span>
          </div>
          {hasErrors && (
            <div className="text-error font-medium">
              {data!.recent_errors.length} recent error{data!.recent_errors.length !== 1 ? 's' : ''}
            </div>
          )}
        </div>
        <div className="mt-3">
          <Link
            to="/admin/sync"
            className="text-xs font-sans text-primary hover:underline"
          >
            Manage sync →
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export function AdminSyncPage() {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery<SyncStatus>({
    queryKey: ['admin', 'sync-status'],
    queryFn: () => apiFetch<SyncStatus>('/api/v1/admin/sync/status'),
    refetchInterval: 15_000,
  });

  const trigger = useMutation({
    mutationFn: () => apiFetch<SyncStatus>('/api/v1/admin/sync/trigger', { method: 'POST' }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(['admin', 'sync-status'], fresh);
    },
  });

  const countdown = useCountdown(data?.next_run_at ?? null);

  return (
    <div>
      <PageHeader
        title="Sync Status"
        eyebrow="Admin"
        back={{ to: '/admin', label: 'Admin' }}
      />

      {error && (
        <EmptyState
          title="Couldn't load sync status"
          description="The sync API isn't responding. Try refreshing in a moment."
        />
      )}

      {isLoading && !data && (
        <div className="space-y-4 max-w-xl" aria-label="Loading sync status">
          <Skeleton className="h-[180px]" />
          <Skeleton className="h-[80px]" />
        </div>
      )}

      {data && (
        <div className="space-y-6 max-w-xl">
          {/* Status card */}
          <Card>
            <CardContent className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono uppercase tracking-[0.25em] text-text-secondary text-xs">Status</span>
                <Badge variant={actionBadgeVariant(data.last_sync_action)}>
                  {actionLabel(data.last_sync_action)}
                </Badge>
              </div>

              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm font-sans">
                <dt className="text-text-muted">Last sync</dt>
                <dd className="text-text-primary font-mono">
                  {data.last_sync_at
                    ? formatInTimeZone(new Date(data.last_sync_at), 'UTC', 'yyyy-MM-dd HH:mm:ss') + ' UTC'
                    : '—'}
                </dd>

                <dt className="text-text-muted">Next run</dt>
                <dd className="text-text-primary font-mono">
                  {data.next_run_at
                    ? `${formatInTimeZone(new Date(data.next_run_at), 'UTC', 'HH:mm:ss')} UTC (${countdown})`
                    : '—'}
                </dd>
              </dl>

              <div className="pt-2">
                <Button
                  onClick={() => trigger.mutate()}
                  disabled={trigger.isPending}
                  variant="default"
                  size="sm"
                >
                  {trigger.isPending ? 'Syncing…' : 'Sync Now'}
                </Button>
                {trigger.isError && (
                  <p className="mt-1 text-xs text-error font-sans">Sync failed. Check errors below.</p>
                )}
                {trigger.isSuccess && (
                  <p className="mt-1 text-xs text-success font-sans">Sync triggered successfully.</p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Error log */}
          <div>
            <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-3">
              RECENT ERRORS
            </h2>
            {data.recent_errors.length === 0 ? (
              <EmptyState
                title="No recent errors"
                description="The auto-sync has been running cleanly."
              />
            ) : (
              <div className="space-y-2">
                {data.recent_errors.map((e) => (
                  <Card key={e.id} className="border-error/40">
                    <CardContent className="p-3">
                      <div className="flex items-center justify-between mb-1">
                        <Badge variant="error">{e.action_type}</Badge>
                        <span className="text-xs font-mono text-text-muted">
                          {formatInTimeZone(new Date(e.timestamp), 'UTC', 'yyyy-MM-dd HH:mm:ss')} UTC
                        </span>
                      </div>
                      {e.changes && (
                        <pre className="text-xs font-mono text-text-secondary mt-1 overflow-x-auto whitespace-pre-wrap">
                          {JSON.stringify(e.changes, null, 2)}
                        </pre>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
