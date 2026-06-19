import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiFetch } from '@/lib/api';
import { privacyLabel } from '@/lib/leagues';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { PageHeader } from '@/components/PageHeader';

interface DiscoverLeague {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  max_members: number;
  member_count: number;
  privacy: string;
}

interface DiscoverResponse {
  leagues: DiscoverLeague[];
  total: number;
  page: number;
  page_size: number;
}

export function DiscoverLeaguesPage() {
  const queryClient = useQueryClient();
  const [joiningSlug, setJoiningSlug] = useState<string | null>(null);

  const { data, isLoading } = useQuery<DiscoverResponse>({
    queryKey: ['leagues', 'discover'],
    queryFn: () => apiFetch<DiscoverResponse>('/api/v1/leagues/discover'),
  });

  const leagues = data?.leagues ?? [];

  async function handleJoin(slug: string, privacy: string) {
    setJoiningSlug(slug);
    try {
      await apiFetch(`/api/v1/leagues/${slug}/join`, { method: 'POST' });
      if (privacy === 'public_open') {
        toast.success('Joined league!');
        queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] });
        queryClient.invalidateQueries({ queryKey: ['leagues', 'discover'] });
      } else {
        toast.success('Join request sent — waiting for admin approval.');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to join');
    } finally {
      setJoiningSlug(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PageHeader title="Discover Leagues" back={{ to: '/leagues', label: 'Leagues' }} />
        <Button asChild size="sm" variant="outline">
          <Link to="/leagues">My leagues</Link>
        </Button>
      </div>

      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      )}

      {!isLoading && leagues.length === 0 && (
        <Card>
          <CardContent className="pt-8 pb-8 text-center">
            <p className="text-text-secondary font-sans text-sm">
              No public leagues to discover right now.
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && leagues.length > 0 && (
        <div className="space-y-3">
          {leagues.map((league) => (
            <Card key={league.slug}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base">{league.name}</CardTitle>
                  <Badge variant="muted" className="text-xs shrink-0">
                    {privacyLabel(league.privacy)}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                {league.description && (
                  <p className="text-sm text-text-secondary font-sans mb-3 line-clamp-2">
                    {league.description}
                  </p>
                )}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-text-muted font-sans">
                    {league.member_count}
                    {league.max_members ? ` / ${league.max_members}` : ''} members
                  </span>
                  <Button
                    size="sm"
                    disabled={joiningSlug === league.slug}
                    onClick={() => handleJoin(league.slug, league.privacy)}
                  >
                    {joiningSlug === league.slug
                      ? 'Joining…'
                      : league.privacy === 'public_open'
                      ? 'Join'
                      : 'Request to join'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
