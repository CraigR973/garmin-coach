import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '@/lib/api';
import type { LeagueMember } from '@/lib/types';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { PageHeader } from '@/components/PageHeader';
import { Avatar } from '@/components/ui/avatar';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export function LeagueMembersPage() {
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  const { player } = useAuth();
  const queryClient = useQueryClient();
  const [actingOn, setActingOn] = useState<string | null>(null);

  const [removeTarget, setRemoveTarget] = useState<LeagueMember | null>(null);
  const [removeConfirm, setRemoveConfirm] = useState('');
  const [showLeaveDialog, setShowLeaveDialog] = useState(false);
  const [leaveConfirm, setLeaveConfirm] = useState('');

  const { data: members, isLoading } = useQuery<LeagueMember[]>({
    queryKey: ['league-members', slug],
    queryFn: () => apiFetch<LeagueMember[]>(`/api/v1/leagues/${slug}/members`),
  });

  const myMembership = members?.find((m) => m.player_id === player?.id);
  const isAdmin = myMembership?.role === 'admin';

  async function promote(playerId: string) {
    setActingOn(playerId);
    try {
      await apiFetch(`/api/v1/leagues/${slug}/members/${playerId}/promote`, { method: 'POST' });
      toast.success('Member promoted to admin');
      queryClient.invalidateQueries({ queryKey: ['league-members', slug] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to promote');
    } finally {
      setActingOn(null);
    }
  }

  async function demote(playerId: string) {
    setActingOn(playerId);
    try {
      await apiFetch(`/api/v1/leagues/${slug}/members/${playerId}/demote`, { method: 'POST' });
      toast.success('Admin demoted to player');
      queryClient.invalidateQueries({ queryKey: ['league-members', slug] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to demote');
    } finally {
      setActingOn(null);
    }
  }

  async function confirmRemoveMember() {
    if (!removeTarget) return;
    setActingOn(removeTarget.player_id);
    const name = removeTarget.display_name;
    try {
      await apiFetch(`/api/v1/leagues/${slug}/members/${removeTarget.player_id}`, { method: 'DELETE' });
      toast.success(`${name} removed`);
      setRemoveTarget(null);
      setRemoveConfirm('');
      queryClient.invalidateQueries({ queryKey: ['league-members', slug] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to remove member');
    } finally {
      setActingOn(null);
    }
  }

  async function confirmLeaveLeague() {
    try {
      await apiFetch(`/api/v1/leagues/${slug}/membership`, { method: 'DELETE' });
      toast.success('Left the league');
      setShowLeaveDialog(false);
      setLeaveConfirm('');
      queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] });
      window.location.href = '/leagues';
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      if (msg.includes('LAST_ADMIN')) {
        toast.error('You are the only admin — promote another member before leaving.');
      } else {
        toast.error(msg || 'Failed to leave');
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0 flex-1">
          <PageHeader title="Members" back={{ to: `/leagues/${slug}`, label: 'Back' }} />
        </div>
        {myMembership && (
          <Button size="sm" variant="outline" className="shrink-0 text-error border-error/40 hover:bg-error/10" onClick={() => setShowLeaveDialog(true)}>
            Leave league
          </Button>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
        </div>
      )}

      {!isLoading && members && (
        <div className="space-y-2">
          {members.map((m) => (
            <Card key={m.player_id}>
              <CardContent className="pt-3 pb-3">
                <div className="flex items-center gap-3">
                  <Avatar name={m.league_display_name ?? m.display_name} size="sm" src={m.avatar_url} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-sans font-medium truncate">
                      {m.league_display_name ?? m.display_name}
                    </p>
                    {m.league_display_name && (
                      <p className="text-xs text-text-muted font-sans">{m.display_name}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {m.role === 'admin' && (
                      <Badge variant="muted" className="text-xs text-accent border-accent/40">
                        Admin
                      </Badge>
                    )}
                    {m.player_id === player?.id && (
                      <Badge variant="muted" className="text-xs">You</Badge>
                    )}
                    {isAdmin && m.player_id !== player?.id && (
                      <div className="flex gap-1">
                        {m.role === 'player' ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-xs h-7 px-2"
                            disabled={actingOn === m.player_id}
                            onClick={() => promote(m.player_id)}
                          >
                            Promote
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-xs h-7 px-2"
                            disabled={actingOn === m.player_id}
                            onClick={() => demote(m.player_id)}
                          >
                            Demote
                          </Button>
                        )}
                        {m.role === 'player' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-xs h-7 px-2 text-error hover:bg-error/10"
                            disabled={actingOn === m.player_id}
                            onClick={() => { setRemoveTarget(m); setRemoveConfirm(''); }}
                          >
                            Remove
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={!!removeTarget}
        onOpenChange={(open) => { if (!open) { setRemoveTarget(null); setRemoveConfirm(''); } }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove member</DialogTitle>
            <DialogDescription>
              Type <strong>{removeTarget?.league_display_name ?? removeTarget?.display_name}</strong> to confirm removal.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 mt-2">
            <Input
              value={removeConfirm}
              onChange={(e) => setRemoveConfirm(e.target.value)}
              placeholder="Type name to confirm"
            />
            <DialogFooter>
              <Button variant="ghost" onClick={() => { setRemoveTarget(null); setRemoveConfirm(''); }}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={
                  removeConfirm !== (removeTarget?.league_display_name ?? removeTarget?.display_name) ||
                  actingOn === removeTarget?.player_id
                }
                onClick={confirmRemoveMember}
              >
                {actingOn === removeTarget?.player_id ? 'Removing…' : 'Remove'}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showLeaveDialog}
        onOpenChange={(open) => { if (!open) { setShowLeaveDialog(false); setLeaveConfirm(''); } }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Leave league</DialogTitle>
            <DialogDescription>
              Type <strong>LEAVE</strong> to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 mt-2">
            <Input
              value={leaveConfirm}
              onChange={(e) => setLeaveConfirm(e.target.value)}
              placeholder="Type LEAVE to confirm"
            />
            <DialogFooter>
              <Button variant="ghost" onClick={() => { setShowLeaveDialog(false); setLeaveConfirm(''); }}>
                Cancel
              </Button>
              <Button
                variant="outline"
                className="border-error/40 text-error hover:bg-error/10"
                disabled={leaveConfirm !== 'LEAVE'}
                onClick={confirmLeaveLeague}
              >
                Leave
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
