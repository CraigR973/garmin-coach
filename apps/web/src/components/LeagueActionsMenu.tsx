import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { LogOut, Settings, Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

interface LeagueActionsMenuProps {
  slug: string;
  leagueName: string;
  isAdmin: boolean;
  className?: string;
}

export function LeagueActionsMenu({
  slug,
  leagueName,
  isAdmin,
  className,
}: LeagueActionsMenuProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showLeaveDialog, setShowLeaveDialog] = useState(false);
  const [leaveConfirm, setLeaveConfirm] = useState('');
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [isLeaving, setIsLeaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  async function handleLeaveLeague() {
    setIsLeaving(true);
    try {
      await apiFetch(`/api/v1/leagues/${slug}/membership`, { method: 'DELETE' });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] }),
        queryClient.invalidateQueries({ queryKey: ['league', slug] }),
        queryClient.invalidateQueries({ queryKey: ['league-members', slug] }),
        queryClient.invalidateQueries({ queryKey: ['leaderboard', slug] }),
      ]);
      toast.success('Left the league');
      navigate('/leagues', { replace: true });
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      if (msg.includes('LAST_ADMIN')) {
        toast.error('You are the only admin — promote another member before leaving.');
      } else {
        toast.error(msg || 'Failed to leave');
      }
      setIsLeaving(false);
    }
  }

  async function handleDeleteLeague() {
    if (deleteConfirm !== leagueName) {
      toast.error('Type the league name exactly to confirm deletion');
      return;
    }

    setIsDeleting(true);
    try {
      await apiFetch(`/api/v1/leagues/${slug}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirm_name: deleteConfirm }),
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] }),
        queryClient.invalidateQueries({ queryKey: ['league', slug] }),
      ]);
      toast.success('League deleted');
      navigate('/leagues', { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete');
      setIsDeleting(false);
    }
  }

  return (
    <>
      <div className={cn('flex flex-wrap items-center gap-2', className)}>
        <Button asChild size="sm" variant="outline" className="gap-1.5">
          <Link to={`/leagues/${slug}/admin/members`}>
            <Users className="h-3.5 w-3.5" aria-hidden />
            Members
          </Link>
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          onClick={() => setShowLeaveDialog(true)}
        >
          <LogOut className="h-3.5 w-3.5" aria-hidden />
          Leave
        </Button>
        {isAdmin && (
          <>
            <Button asChild size="sm" variant="outline" className="gap-1.5">
              <Link to={`/leagues/${slug}/admin/settings`}>
                <Settings className="h-3.5 w-3.5" aria-hidden />
                Settings
              </Link>
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 border-error/40 text-error hover:bg-error/10"
              onClick={() => setShowDeleteDialog(true)}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Delete
            </Button>
          </>
        )}
      </div>

      <Dialog
        open={showLeaveDialog}
        onOpenChange={(open) => {
          if (!open) {
            setShowLeaveDialog(false);
            setLeaveConfirm('');
            setIsLeaving(false);
          }
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Leave league</DialogTitle>
            <DialogDescription>
              Type <strong>LEAVE</strong> to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-2 space-y-3">
            <Input
              value={leaveConfirm}
              onChange={(e) => setLeaveConfirm(e.target.value)}
              placeholder="Type LEAVE to confirm"
            />
            <DialogFooter>
              <Button
                variant="ghost"
                onClick={() => {
                  setShowLeaveDialog(false);
                  setLeaveConfirm('');
                  setIsLeaving(false);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="outline"
                className="border-error/40 text-error hover:bg-error/10"
                disabled={leaveConfirm !== 'LEAVE' || isLeaving}
                onClick={handleLeaveLeague}
              >
                {isLeaving ? 'Leaving…' : 'Leave'}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showDeleteDialog}
        onOpenChange={(open) => {
          if (!open) {
            setShowDeleteDialog(false);
            setDeleteConfirm('');
            setIsDeleting(false);
          }
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete league</DialogTitle>
            <DialogDescription>
              Type <strong>{leagueName}</strong> to confirm deletion.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-2 space-y-3">
            <Input
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
              placeholder="Type league name to confirm"
            />
            <DialogFooter>
              <Button
                variant="ghost"
                onClick={() => {
                  setShowDeleteDialog(false);
                  setDeleteConfirm('');
                  setIsDeleting(false);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={deleteConfirm !== leagueName || isDeleting}
                onClick={handleDeleteLeague}
              >
                {isDeleting ? 'Deleting…' : 'Delete league'}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
