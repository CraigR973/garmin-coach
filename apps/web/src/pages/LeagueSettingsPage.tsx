import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '@/lib/api';
import type { LeagueSummary } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/PageHeader';

export function LeagueSettingsPage() {
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: league } = useQuery<LeagueSummary>({
    queryKey: ['league', slug],
    queryFn: () => apiFetch<LeagueSummary>(`/api/v1/leagues/${slug}`),
  });

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [privacy, setPrivacy] = useState<'public_open' | 'public_request' | 'private'>('public_open');
  const [maxMembers, setMaxMembers] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');

  useEffect(() => {
    if (league) {
      setName(league.name);
      setDescription(league.description ?? '');
      setPrivacy(league.privacy);
      setMaxMembers(league.max_members?.toString() ?? '');
    }
  }, [league]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setIsSaving(true);
    try {
      const body: Record<string, unknown> = { name: name.trim(), privacy };
      if (description.trim()) body.description = description.trim();
      if (maxMembers) body.max_members = Number(maxMembers);
      await apiFetch(`/api/v1/leagues/${slug}`, { method: 'PATCH', body: JSON.stringify(body) });
      toast.success('League settings saved');
      queryClient.invalidateQueries({ queryKey: ['league', slug] });
      queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete() {
    if (deleteConfirm !== league?.name) {
      toast.error('Type the league name exactly to confirm deletion');
      return;
    }
    setIsDeleting(true);
    try {
      await apiFetch(`/api/v1/leagues/${slug}`, { method: 'DELETE' });
      toast.success('League deleted');
      queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] });
      navigate('/leagues', { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete');
      setIsDeleting(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <PageHeader title="League Settings" back={{ to: `/leagues/${slug}`, label: 'Back' }} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Details</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="name">League name</Label>
              <Input
                id="name"
                required
                maxLength={30}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="privacy">Privacy</Label>
              <select
                id="privacy"
                value={privacy}
                onChange={(e) => setPrivacy(e.target.value as typeof privacy)}
                className="flex h-10 w-full items-center rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary font-sans focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="public_open">Public — anyone can join instantly</option>
                <option value="public_request">Public · request — anyone can request to join</option>
                <option value="private">Private — invite only</option>
              </select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="maxMembers">Max members (blank = unlimited)</Label>
              <Input
                id="maxMembers"
                type="number"
                min={2}
                max={500}
                value={maxMembers}
                onChange={(e) => setMaxMembers(e.target.value)}
                placeholder="Unlimited"
              />
            </div>

            <Button type="submit" disabled={isSaving} className="w-full">
              {isSaving ? 'Saving…' : 'Save changes'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="border-error/30">
        <CardHeader>
          <CardTitle className="text-base text-error">Danger zone</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-text-secondary font-sans">
            To delete this league, type its name exactly: <strong>{league?.name}</strong>
          </p>
          <Input
            value={deleteConfirm}
            onChange={(e) => setDeleteConfirm(e.target.value)}
            placeholder="Type league name to confirm"
          />
          <Button
            variant="outline"
            className="w-full border-error/40 text-error hover:bg-error/10"
            disabled={isDeleting}
            onClick={handleDelete}
          >
            {isDeleting ? 'Deleting…' : 'Delete league'}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
