import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Share2, ChevronDown, RefreshCw } from 'lucide-react';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '@/lib/api';
import type { LeagueDetail, LeagueInvite } from '@/lib/types';
import { buildInviteMessage, shareInvite } from '@/lib/invite';
import { getAccessToken } from '@/lib/tokens';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { PageHeader } from '@/components/PageHeader';

const BASE = import.meta.env.VITE_API_URL ?? '';

export function LeagueAdminInvitesPage() {
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  const queryClient = useQueryClient();
  const [isSharing, setIsSharing] = useState(false);
  const [isRotating, setIsRotating] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const { data: league } = useQuery<LeagueDetail>({
    queryKey: ['league', slug],
    queryFn: () => apiFetch<LeagueDetail>(`/api/v1/leagues/${slug}`),
  });

  const { data: invites, isLoading } = useQuery<LeagueInvite[]>({
    queryKey: ['league-invites', slug],
    queryFn: () => apiFetch<LeagueInvite[]>(`/api/v1/leagues/${slug}/invites`),
  });

  async function handleShare() {
    if (!league?.join_code) return;
    setIsSharing(true);
    try {
      const message = buildInviteMessage({
        leagueName: league.name,
        joinCode: league.join_code,
        origin: window.location.origin,
      });
      await shareInvite({ message });
    } catch {
      toast.error('Could not share invite');
    } finally {
      setIsSharing(false);
    }
  }

  async function handleRotate() {
    if (!window.confirm('Generate a new join code? The old link will stop working immediately.')) return;
    setIsRotating(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/leagues/${slug}/join-code/rotate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getAccessToken()}` },
      });
      if (resp.ok) {
        const data = await resp.json() as { join_code: string };
        queryClient.setQueryData(['league', slug], (old: LeagueDetail | undefined) =>
          old ? { ...old, join_code: data.join_code } : old,
        );
        toast.success('New join code generated');
      } else {
        toast.error('Failed to rotate join code');
      }
    } catch {
      toast.error('Failed to rotate join code');
    } finally {
      setIsRotating(false);
    }
  }

  async function createInvite(e: React.FormEvent) {
    e.preventDefault();
    setIsCreating(true);
    try {
      const invite = await apiFetch<LeagueInvite>(`/api/v1/leagues/${slug}/invites`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      toast.success('Invite created');
      queryClient.invalidateQueries({ queryKey: ['league-invites', slug] });
      const joinUrl = `${window.location.origin}/join/${invite.token}`;
      await navigator.clipboard.writeText(joinUrl).catch(() => {});
      toast.info('Join link copied to clipboard');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create invite');
    } finally {
      setIsCreating(false);
    }
  }

  async function revokeInvite(id: string) {
    setRevokingId(id);
    try {
      await apiFetch(`/api/v1/leagues/${slug}/invites/${id}`, { method: 'DELETE' });
      toast.success('Invite revoked');
      queryClient.invalidateQueries({ queryKey: ['league-invites', slug] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to revoke');
    } finally {
      setRevokingId(null);
    }
  }

  function copyLink(token: string) {
    const url = `${window.location.origin}/join/${token}`;
    navigator.clipboard.writeText(url).then(
      () => toast.success('Link copied'),
      () => toast.info(url),
    );
  }

  const activeInvites = invites?.filter((i) => !i.used_at) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="Invites" back={{ to: `/leagues/${slug}`, label: 'Back' }} />

      {/* Primary action — join code share */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Invite friends</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-text-secondary font-sans">
            Share the league join code so anyone can join from the link or the app.
          </p>
          {league?.join_code ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="font-mono text-lg font-semibold text-primary tracking-widest">
                  {league.join_code}
                </span>
                <Button
                  variant="accent"
                  size="sm"
                  className="gap-1.5"
                  onClick={handleShare}
                  disabled={isSharing}
                >
                  <Share2 className="h-3.5 w-3.5" aria-hidden />
                  {isSharing ? 'Sharing…' : 'Share invite'}
                </Button>
              </div>
              <button
                onClick={handleRotate}
                disabled={isRotating}
                className="flex items-center gap-1.5 text-xs text-text-muted hover:text-error transition-colors disabled:opacity-50"
              >
                <RefreshCw className="h-3 w-3" aria-hidden />
                {isRotating ? 'Rotating…' : 'Generate new code — old links stop working'}
              </button>
            </div>
          ) : (
            <Skeleton className="h-9 w-48" />
          )}
        </CardContent>
      </Card>

      {/* Advanced — one-time private link (collapsed by default) */}
      <details className="group">
        <summary className="flex cursor-pointer select-none items-center justify-between rounded-lg border border-border bg-surface px-4 py-3 text-sm font-sans text-text-secondary hover:text-text-primary transition-colors">
          <span>Advanced: one-time private link</span>
          <ChevronDown className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180" aria-hidden />
        </summary>

        <div className="mt-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Create invite</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={createInvite}>
                <Button type="submit" disabled={isCreating} className="w-full">
                  {isCreating ? 'Creating…' : 'Generate invite link'}
                </Button>
              </form>
            </CardContent>
          </Card>

          {isLoading && (
            <div className="space-y-2">
              {[1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          )}

          {!isLoading && activeInvites.length === 0 && (
            <p className="text-text-muted font-sans text-sm text-center py-4">No active one-time links.</p>
          )}

          {activeInvites.length > 0 && (
            <div className="space-y-2">
              {activeInvites.map((invite) => (
                <Card key={invite.id}>
                  <CardContent className="pt-3 pb-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-mono truncate text-text-secondary">
                          {`${window.location.origin}/join/${invite.token}`}
                        </p>
                      </div>
                      <div className="flex gap-2 shrink-0">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => copyLink(invite.token)}
                        >
                          Copy
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-error hover:bg-error/10"
                          disabled={revokingId === invite.id}
                          onClick={() => revokeInvite(invite.id)}
                        >
                          Revoke
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
