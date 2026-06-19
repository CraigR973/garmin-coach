import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Trash2, Users, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';

interface AdminLeague {
  slug: string;
  name: string;
  privacy: string;
  member_count: number;
  created_at: string;
  join_code: string | null;
}

function privacyVariant(privacy: string): 'muted' | 'success' | 'warning' {
  if (privacy === 'private') return 'muted';
  if (privacy === 'public_open') return 'success';
  return 'warning';
}

export function AdminAllLeaguesPage() {
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState<AdminLeague | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [rotatingSlug, setRotatingSlug] = useState<string | null>(null);

  async function handleRotateCode(league: AdminLeague) {
    setRotatingSlug(league.slug);
    try {
      const data = await apiFetch<{ join_code: string }>(
        `/api/v1/admin/leagues/${league.slug}/rotate-join-code`,
        { method: 'POST' },
      );
      queryClient.setQueryData<AdminLeague[]>(['admin', 'all-leagues'], (old) =>
        old?.map((l) => (l.slug === league.slug ? { ...l, join_code: data.join_code } : l)) ?? [],
      );
      toast.success(`Join code rotated: ${data.join_code}`);
    } catch {
      toast.error('Failed to rotate join code');
    } finally {
      setRotatingSlug(null);
    }
  }

  const { data = [], isLoading, error, refetch } = useQuery<AdminLeague[]>({
    queryKey: ['admin', 'all-leagues'],
    queryFn: () => apiFetch<AdminLeague[]>('/api/v1/admin/leagues'),
    staleTime: 30_000,
  });

  async function handleDelete() {
    if (!deleting) return;
    setIsSubmitting(true);
    try {
      await apiFetch(`/api/v1/leagues/${deleting.slug}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirm_name: deleting.name }),
      });
      toast.success(`League "${deleting.name}" deleted`);
      queryClient.invalidateQueries({ queryKey: ['admin', 'all-leagues'] });
      setDeleting(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete league');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div>
      <PageHeader title="All Leagues" eyebrow="Superadmin" />

      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {error && (
        <EmptyState
          title="Couldn't load leagues"
          description="Refresh the page or check your connection."
          action={
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Try again
            </Button>
          }
        />
      )}

      {!isLoading && !error && data.length === 0 && (
        <EmptyState title="No leagues yet" description="Leagues will appear here once created." />
      )}

      {data.length > 0 && (
        <div className="rounded-lg border border-border bg-surface overflow-hidden divide-y divide-border/50">
          {data.map((league) => (
            <div
              key={league.slug}
              className="flex items-center justify-between gap-4 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="font-sans text-sm font-semibold text-text-primary truncate">
                  {league.name}
                </p>
                <p className="font-mono text-xs text-text-muted mt-0.5">
                  /{league.slug} · {league.member_count} member{league.member_count !== 1 ? 's' : ''}
                  {league.join_code && (
                    <span className="ml-2 text-text-secondary">· code: <span className="text-text-primary font-semibold">{league.join_code}</span></span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant={privacyVariant(league.privacy)} className="capitalize text-xs">
                  {league.privacy.replace('_', ' ')}
                </Badge>
                <Button asChild variant="ghost" size="sm" aria-label={`View members of ${league.name}`}>
                  <Link to={`/leagues/${league.slug}/admin/members`}>
                    <Users className="h-4 w-4" aria-hidden />
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRotateCode(league)}
                  disabled={rotatingSlug === league.slug}
                  aria-label={`Rotate join code for ${league.name}`}
                  title="Rotate join code"
                >
                  <RefreshCw className={`h-4 w-4 ${rotatingSlug === league.slug ? 'animate-spin' : ''}`} aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-error hover:text-error hover:bg-error/10"
                  onClick={() => setDeleting(league)}
                  aria-label={`Delete ${league.name}`}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={!!deleting} onOpenChange={(open) => { if (!open) setDeleting(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete league?</DialogTitle>
            <DialogDescription>
              This will permanently delete{' '}
              <strong className="text-text-primary">{deleting?.name}</strong>{' '}
              and all its memberships. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-3 justify-end mt-2">
            <Button variant="outline" onClick={() => setDeleting(null)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Deleting…' : 'Delete league'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
