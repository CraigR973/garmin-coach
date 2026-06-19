import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { LeagueSummary } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/PageHeader';

export function CreateLeaguePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [privacy, setPrivacy] = useState<'public_open' | 'public_request' | 'private'>('public_open');
  const [maxMembers, setMaxMembers] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const body: Record<string, unknown> = { name: name.trim(), privacy };
      if (description.trim()) body.description = description.trim();
      if (maxMembers) body.max_members = Number(maxMembers);

      const league = await apiFetch<LeagueSummary>('/api/v1/leagues', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] });
      navigate(`/leagues/${league.slug}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create league');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <PageHeader title="Create a League" />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">League details</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="name">League name</Label>
              <Input
                id="name"
                required
                maxLength={30}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Calcio"
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="description">Description (optional)</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="A quick tagline for your league"
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
                <option value="public_open">Open — anyone can join instantly</option>
                <option value="public_request">Request — anyone can request to join</option>
                <option value="private">Private — invite only</option>
              </select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="maxMembers">Max members (optional, 2–50)</Label>
              <Input
                id="maxMembers"
                type="number"
                min={2}
                max={50}
                value={maxMembers}
                onChange={(e) => setMaxMembers(e.target.value)}
                placeholder="Leave blank for default (15)"
              />
            </div>

            {error && <p role="alert" className="text-xs text-error font-sans">{error}</p>}

            <div className="flex gap-3 pt-2">
              <Button type="button" variant="outline" onClick={() => navigate(-1)} className="flex-1">
                Cancel
              </Button>
              <Button type="submit" disabled={isLoading} className="flex-1">
                {isLoading ? 'Creating…' : 'Create league'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
