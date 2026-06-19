import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '@/lib/api';
import type { JoinRequest } from '@/lib/types';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { PageHeader } from '@/components/PageHeader';

export function LeagueJoinRequestsPage() {
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  const queryClient = useQueryClient();
  const [actingOn, setActingOn] = useState<string | null>(null);

  const { data: requests, isLoading } = useQuery<JoinRequest[]>({
    queryKey: ['league-join-requests', slug],
    queryFn: () => apiFetch<JoinRequest[]>(`/api/v1/leagues/${slug}/join-requests`),
  });

  const pending = requests?.filter((r) => r.status === 'pending') ?? [];

  async function approve(id: string) {
    setActingOn(id);
    try {
      await apiFetch(`/api/v1/leagues/${slug}/join-requests/${id}/approve`, { method: 'POST' });
      toast.success('Request approved');
      queryClient.invalidateQueries({ queryKey: ['league-join-requests', slug] });
      queryClient.invalidateQueries({ queryKey: ['league-members', slug] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to approve');
    } finally {
      setActingOn(null);
    }
  }

  async function reject(id: string) {
    setActingOn(id);
    try {
      await apiFetch(`/api/v1/leagues/${slug}/join-requests/${id}/reject`, { method: 'POST' });
      toast.success('Request rejected');
      queryClient.invalidateQueries({ queryKey: ['league-join-requests', slug] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to reject');
    } finally {
      setActingOn(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Join Requests" back={{ to: `/leagues/${slug}`, label: 'Back' }} />

      {isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
        </div>
      )}

      {!isLoading && pending.length === 0 && (
        <Card>
          <CardContent className="pt-8 pb-8 text-center">
            <p className="text-text-secondary font-sans text-sm">No pending join requests.</p>
          </CardContent>
        </Card>
      )}

      {!isLoading && pending.length > 0 && (
        <div className="space-y-2">
          {pending.map((req) => (
            <Card key={req.id}>
              <CardContent className="pt-3 pb-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-sans font-medium">{req.display_name}</p>
                    <p className="text-xs text-text-muted font-sans">
                      {new Date(req.requested_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="muted" className="text-xs">Pending</Badge>
                    <Button
                      size="sm"
                      disabled={actingOn === req.id}
                      onClick={() => approve(req.id)}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-error/40 text-error hover:bg-error/10"
                      disabled={actingOn === req.id}
                      onClick={() => reject(req.id)}
                    >
                      Reject
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
