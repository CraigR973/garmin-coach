import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/PageHeader';

const BASE = import.meta.env.VITE_API_URL ?? '';

interface LeaguePreview {
  name: string;
  member_count: number;
  max_members: number;
  privacy: string;
}

type Step = 'input' | 'confirm' | 'done';

export function JoinByCodePage() {
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('input');
  const [code, setCode] = useState('');
  const [preview, setPreview] = useState<LeaguePreview | null>(null);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function handleLookup(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    const trimmed = code.trim().toUpperCase();
    if (!trimmed) return;
    setIsLoading(true);
    try {
      const data = await apiFetch<LeaguePreview>(
        `/api/v1/leagues/by-code/${encodeURIComponent(trimmed)}`,
      );
      setPreview(data);
      setStep('confirm');
    } catch {
      setError('No league found for that code. Check the code and try again.');
    } finally {
      setIsLoading(false);
    }
  }

  async function handleJoin() {
    if (!preview) return;
    setError('');
    setIsLoading(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/leagues/join-by-code`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${(await import('@/lib/tokens')).getAccessToken()}`,
        },
        body: JSON.stringify({ code: code.trim().toUpperCase() }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        const detail = body.detail ?? 'Failed to join';
        if (detail === 'ALREADY_MEMBER') throw new Error('You are already in this league.');
        if (detail === 'LEAGUE_FULL') throw new Error('This league is full.');
        throw new Error(detail);
      }
      const data = await resp.json() as { league_slug: string; league_name: string };
      navigate(`/leagues/${data.league_slug}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join league');
      setIsLoading(false);
    }
  }

  return (
    <div className="space-y-6 max-w-sm mx-auto">
      <PageHeader title="Join a league" back={{ to: '/leagues', label: 'Leagues' }} />

      {step === 'input' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Enter join code</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleLookup} className="space-y-4">
              <div className="space-y-1">
                <Label htmlFor="join-code">League code</Label>
                <Input
                  id="join-code"
                  type="text"
                  inputMode="text"
                  autoCapitalize="characters"
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                  placeholder="e.g. ABCD23"
                  maxLength={8}
                  value={code}
                  onChange={(e) => setCode(e.target.value.toUpperCase())}
                  className="font-mono tracking-widest text-center text-lg"
                />
                <p className="text-xs text-text-muted font-sans">
                  Ask the league admin for their share link or 6-character code.
                </p>
              </div>
              {error && <p role="alert" className="text-xs text-error font-sans">{error}</p>}
              <Button type="submit" className="w-full" disabled={isLoading || !code.trim()}>
                {isLoading ? 'Looking up…' : 'Find league'}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {step === 'confirm' && preview && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="text-base text-center">Join this league?</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-center space-y-1">
              <p className="text-lg font-semibold text-text-primary">{preview.name}</p>
              <p className="text-sm text-text-secondary font-sans">
                {preview.member_count} / {preview.max_members} members
              </p>
            </div>
            {error && <p role="alert" className="text-xs text-error font-sans">{error}</p>}
            <div className="flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => { setStep('input'); setError(''); }}
                disabled={isLoading}
              >
                Back
              </Button>
              <Button className="flex-1" onClick={handleJoin} disabled={isLoading}>
                {isLoading ? 'Joining…' : `Join ${preview.name}`}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
