import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '@/contexts/AuthContext';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface AdminPlayer {
  id: string;
  display_name: string;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  timezone: string;
  is_deleted: boolean;
  created_at: string;
  failed_login_count: number;
  locked_until: string | null;
}

export function AdminPlayersPage() {
  const { player: currentPlayer } = useAuth();
  const [players, setPlayers] = useState<AdminPlayer[]>([]);
  const [showDeleted, setShowDeleted] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  // Delete confirm dialog
  const [deleteTarget, setDeleteTarget] = useState<AdminPlayer | null>(null);
  const [deleteConfirmInput, setDeleteConfirmInput] = useState('');

  // Reset PIN dialog
  const [resetTarget, setResetTarget] = useState<AdminPlayer | null>(null);
  const [tempPin, setTempPin] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [pinCopied, setPinCopied] = useState(false);

  async function load(includeDeleted: boolean) {
    setIsLoading(true);
    setError('');
    try {
      const data = await apiFetch<AdminPlayer[]>(
        `/api/v1/admin/players?include_deleted=${includeDeleted}`,
      );
      setPlayers(data);
    } catch {
      setError('Failed to load players.');
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    load(showDeleted);
  }, [showDeleted]);

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await apiFetch(`/api/v1/admin/players/${deleteTarget.id}`, { method: 'DELETE' });
      setPlayers((prev) =>
        showDeleted
          ? prev.map((pl) => (pl.id === deleteTarget.id ? { ...pl, is_deleted: true } : pl))
          : prev.filter((pl) => pl.id !== deleteTarget.id),
      );
      setDeleteTarget(null);
      setDeleteConfirmInput('');
    } catch {
      toast.error('Failed to remove player.');
    }
  }

  async function handleUnlock(p: AdminPlayer) {
    try {
      await apiFetch(`/api/v1/admin/players/${p.id}/unlock`, { method: 'POST' });
      setPlayers((prev) => prev.map((pl) => pl.id === p.id ? { ...pl, failed_login_count: 0, locked_until: null } : pl));
      toast.success(`${p.display_name} unlocked.`);
    } catch {
      toast.error('Failed to unlock account.');
    }
  }

  async function handleResetPin() {
    if (!resetTarget) return;
    setResetting(true);
    try {
      const data = await apiFetch<{ temp_pin: string }>(
        `/api/v1/admin/players/${resetTarget.id}/reset-pin`,
        { method: 'POST' },
      );
      setTempPin(data.temp_pin);
    } catch {
      alert('Failed to reset PIN.');
      setResetting(false);
    }
  }

  function copyPin() {
    if (!tempPin) return;
    navigator.clipboard.writeText(tempPin);
    setPinCopied(true);
    setTimeout(() => setPinCopied(false), 2000);
  }

  function closeResetDialog() {
    setResetTarget(null);
    setTempPin(null);
    setResetting(false);
    setPinCopied(false);
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Players"
        eyebrow="Admin"
        back={{ to: '/admin', label: 'Admin' }}
        action={
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs font-sans text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={showDeleted}
                onChange={(e) => setShowDeleted(e.target.checked)}
                className="accent-primary"
              />
              Show removed
            </label>
            <Link
              to="/admin/invites"
              className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium font-sans bg-surface text-text-secondary hover:bg-surface-elevated border border-border transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow"
            >
              Invites →
            </Link>
          </div>
        }
      />

        {isLoading && (
          <div className="space-y-3" aria-label="Loading players">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[80px]" />
            ))}
          </div>
        )}
        {error && (
          <EmptyState title="Couldn't load players" description={error} />
        )}

        <div className="space-y-3">
          {players.map((p) => (
            <Card key={p.id} className={p.is_deleted ? 'opacity-50' : ''}>
              <CardContent className="pt-4 pb-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-text-primary font-sans">
                        {p.first_name} {p.last_name}
                      </span>
                      {p.display_name !== `${p.first_name} ${p.last_name}` && (
                        <span className="text-xs text-text-muted font-sans">({p.display_name})</span>
                      )}
                      {p.role === 'admin' && <Badge variant="accent">admin</Badge>}
                      {p.is_deleted && <Badge variant="error">removed</Badge>}
                      {p.locked_until && new Date(p.locked_until + 'Z') > new Date() && (
                        <Badge variant="warning">locked</Badge>
                      )}
                    </div>
                    <p className="text-xs text-text-muted font-sans mt-0.5">
                      {p.email}
                    </p>
                    <p className="text-xs text-text-muted font-sans mt-0.5">
                      {p.timezone} · joined {new Date(p.created_at + 'Z').toLocaleDateString()}
                    </p>
                  </div>
                  {!p.is_deleted && p.id !== currentPlayer?.id && (
                    <div className="flex items-center gap-2 shrink-0">
                      {p.locked_until && new Date(p.locked_until + 'Z') > new Date() && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleUnlock(p)}
                        >
                          Unlock
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setResetTarget(p)}
                      >
                        Reset PIN
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => { setDeleteTarget(p); setDeleteConfirmInput(''); }}
                      >
                        Remove
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
          {!isLoading && players.length === 0 && (
            <EmptyState
              title="No players"
              description={showDeleted ? 'No players match this filter.' : 'No active players yet — share an invite to add the first one.'}
            />
          )}
        </div>

      {/* Delete confirm dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) { setDeleteTarget(null); setDeleteConfirmInput(''); } }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove player</DialogTitle>
            <DialogDescription>
              Type <strong>{deleteTarget?.display_name}</strong> to confirm removal.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 mt-2">
            <Input
              value={deleteConfirmInput}
              onChange={(e) => setDeleteConfirmInput(e.target.value)}
              placeholder="Type name to confirm"
            />
            <DialogFooter>
              <Button variant="ghost" onClick={() => { setDeleteTarget(null); setDeleteConfirmInput(''); }}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={deleteConfirmInput !== deleteTarget?.display_name}
                onClick={confirmDelete}
              >
                Remove
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      {/* Reset PIN dialog */}
      <Dialog open={!!resetTarget} onOpenChange={(open) => !open && closeResetDialog()}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Reset PIN</DialogTitle>
            <DialogDescription>
              {tempPin
                ? `New temporary PIN for ${resetTarget?.display_name}. Share it securely — it will only be shown once.`
                : `Generate a temporary PIN for ${resetTarget?.display_name}?`}
            </DialogDescription>
          </DialogHeader>

          {tempPin ? (
            <div className="space-y-4 mt-2">
              <div className="flex items-center justify-between rounded-lg border border-border bg-surface p-4">
                <span className="font-mono text-2xl text-text-primary tracking-widest">
                  {tempPin}
                </span>
                <Button variant="outline" size="sm" onClick={copyPin}>
                  {pinCopied ? 'Copied!' : 'Copy'}
                </Button>
              </div>
              <DialogFooter>
                <Button onClick={closeResetDialog}>Done</Button>
              </DialogFooter>
            </div>
          ) : (
            <DialogFooter className="mt-4">
              <Button variant="ghost" onClick={closeResetDialog}>
                Cancel
              </Button>
              <Button onClick={handleResetPin} disabled={resetting}>
                {resetting ? 'Resetting…' : 'Reset PIN'}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
