import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

// Per-league invite shape (POST/GET /api/v1/leagues/{slug}/invites). The
// admin-create route under /api/v1/admin/invites was removed in M8 (per-league
// invites only), so this page targets the per-league endpoints — a site
// superadmin bypasses the league-admin check, so any league slug works.
interface Invite {
  id: string;
  token: string;
  display_name_hint: string | null;
  created_by: string;
  claimed_by: string | null;
  claimed_at: string | null;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
}

interface AdminLeague {
  slug: string;
  name: string;
}

function inviteLink(token: string) {
  return `${window.location.origin}/join/${token}`;
}

function statusBadge(invite: Invite) {
  if (invite.claimed_by) return <Badge variant="muted">Claimed</Badge>;
  if (!invite.is_active) return <Badge variant="error">Revoked</Badge>;
  if (invite.expires_at && new Date(invite.expires_at + 'Z') < new Date())
    return <Badge variant="error">Expired</Badge>;
  return <Badge variant="success">Active</Badge>;
}

export function AdminInvitesPage() {
  const [leagues, setLeagues] = useState<AdminLeague[]>([]);
  const [slug, setSlug] = useState('');
  const [leaguesLoaded, setLeaguesLoaded] = useState(false);

  const [invites, setInvites] = useState<Invite[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  // New invite form state
  const [showCreate, setShowCreate] = useState(false);
  const [hint, setHint] = useState('');
  const [expiryDays, setExpiryDays] = useState('7');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  // Revoke confirm dialog
  const [revokeTarget, setRevokeTarget] = useState<Invite | null>(null);
  const [revokeConfirm, setRevokeConfirm] = useState('');

  // Copy feedback
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Resolve which league to manage invites for. Invites are per-league since
  // M8; pick the canonical league by default, fall back to the first.
  useEffect(() => {
    async function loadLeagues() {
      try {
        const all = await apiFetch<AdminLeague[]>('/api/v1/admin/leagues');
        setLeagues(all);
        if (all.length > 0) {
          const preferred = all.find((l) => l.slug === DEFAULT_LEAGUE_SLUG);
          setSlug(preferred?.slug ?? all[0].slug);
        } else {
          setIsLoading(false);
        }
      } catch {
        setError('Failed to load leagues.');
        setIsLoading(false);
      } finally {
        setLeaguesLoaded(true);
      }
    }
    loadLeagues();
  }, []);

  async function load(targetSlug: string) {
    setIsLoading(true);
    setError('');
    try {
      const data = await apiFetch<Invite[]>(`/api/v1/leagues/${targetSlug}/invites`);
      setInvites(data);
    } catch {
      setError('Failed to load invites.');
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (slug) load(slug);
  }, [slug]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!slug) return;
    setCreateError('');
    setCreating(true);
    try {
      const body: Record<string, unknown> = {};
      if (hint.trim()) body.display_name_hint = hint.trim();
      body.expires_in_days = expiryDays === '' ? null : parseInt(expiryDays);
      const invite = await apiFetch<Invite>(`/api/v1/leagues/${slug}/invites`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setInvites((prev) => [invite, ...prev]);
      setShowCreate(false);
      setHint('');
      setExpiryDays('7');
    } catch {
      setCreateError('Failed to create invite.');
    } finally {
      setCreating(false);
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget || !slug) return;
    try {
      await apiFetch(`/api/v1/leagues/${slug}/invites/${revokeTarget.id}`, { method: 'DELETE' });
      setInvites((prev) =>
        prev.map((i) => (i.id === revokeTarget.id ? { ...i, is_active: false } : i)),
      );
      setRevokeTarget(null);
      setRevokeConfirm('');
    } catch {
      alert('Failed to revoke invite.');
    }
  }

  function copyLink(invite: Invite) {
    navigator.clipboard.writeText(inviteLink(invite.token));
    setCopiedId(invite.id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Invites"
        eyebrow="Admin"
        action={
          <div className="flex items-center gap-2">
            <Link
              to="/admin/players"
              className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium font-sans bg-surface text-text-secondary hover:bg-surface-elevated border border-border transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow"
            >
              Players →
            </Link>
            <Button size="sm" onClick={() => setShowCreate(true)} disabled={!slug}>
              New invite
            </Button>
          </div>
        }
      />
        {/* League selector — invites are per-league; show a picker when the
            admin manages more than one league. */}
        {leagues.length > 1 && (
          <div className="mb-4 flex items-center gap-2">
            <Label htmlFor="league" className="text-xs text-text-muted shrink-0">
              League
            </Label>
            <select
              id="league"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-sans text-text-primary focus-visible:outline-none focus-visible:shadow-glow"
            >
              {leagues.map((l) => (
                <option key={l.slug} value={l.slug}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {isLoading && (
          <div className="space-y-3" aria-label="Loading invites">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-[100px]" />
            ))}
          </div>
        )}
        {error && (
          <EmptyState title="Couldn't load invites" description={error} />
        )}
        {leaguesLoaded && leagues.length === 0 && !error && (
          <EmptyState
            title="No leagues yet"
            description="Create a league before generating invites."
          />
        )}

        <div className="space-y-3">
          {invites.map((invite) => (
            <Card key={invite.id}>
              <CardContent className="pt-4 pb-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      {statusBadge(invite)}
                      {invite.display_name_hint && (
                        <span className="text-sm text-text-primary font-sans font-medium">
                          {invite.display_name_hint}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-text-muted font-mono truncate">
                      {inviteLink(invite.token)}
                    </p>
                    <p className="text-xs text-text-muted font-sans mt-1">
                      Created {new Date(invite.created_at + 'Z').toLocaleDateString()}
                      {invite.expires_at &&
                        ` · Expires ${new Date(invite.expires_at + 'Z').toLocaleDateString()}`}
                      {invite.claimed_at &&
                        ` · Claimed ${new Date(invite.claimed_at + 'Z').toLocaleDateString()}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {invite.is_active && !invite.claimed_by && (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => copyLink(invite)}
                        >
                          {copiedId === invite.id ? 'Copied!' : 'Copy link'}
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => { setRevokeTarget(invite); setRevokeConfirm(''); }}
                        >
                          Revoke
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
          {!isLoading && !error && slug && invites.length === 0 && (
            <EmptyState
              title="No invites yet"
              description="Create an invite to let a new player join."
            />
          )}
        </div>

      {/* Revoke confirm dialog */}
      <Dialog
        open={!!revokeTarget}
        onOpenChange={(open) => { if (!open) { setRevokeTarget(null); setRevokeConfirm(''); } }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Revoke invite</DialogTitle>
            <DialogDescription>
              Type <strong>REVOKE</strong> to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 mt-2">
            <Input
              value={revokeConfirm}
              onChange={(e) => setRevokeConfirm(e.target.value)}
              placeholder="Type REVOKE to confirm"
            />
            <DialogFooter>
              <Button variant="ghost" onClick={() => { setRevokeTarget(null); setRevokeConfirm(''); }}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={revokeConfirm !== 'REVOKE'}
                onClick={confirmRevoke}
              >
                Revoke
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Create invite</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4 mt-2">
            <div className="space-y-1">
              <Label htmlFor="hint">Name hint (optional)</Label>
              <Input
                id="hint"
                value={hint}
                onChange={(e) => setHint(e.target.value)}
                placeholder="e.g. Craig"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="expiry">Expires in (days, 1–30, blank = no expiry)</Label>
              <Input
                id="expiry"
                type="number"
                min="1"
                max="30"
                value={expiryDays}
                onChange={(e) => setExpiryDays(e.target.value)}
                placeholder="7"
              />
            </div>
            {createError && <p className="text-xs text-error font-sans">{createError}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={creating}>
                {creating ? 'Creating…' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
