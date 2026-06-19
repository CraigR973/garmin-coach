import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Brand } from '@/components/Brand';
import { PinInput } from '@/components/PinInput';
import { brand } from '@/theme/tokens';
import { useAuth } from '@/contexts/AuthContext';
import { getAccessToken } from '@/lib/tokens';
import { useInstallPrompt } from '@/hooks/useInstallPrompt';
import { BrowserOnboarding } from '@/components/BrowserOnboarding';

const BASE = import.meta.env.VITE_API_URL ?? '';

const TIMEZONES = [
  'Europe/London',
  'Europe/Dublin',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Madrid',
  'Europe/Rome',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Toronto',
  'America/Vancouver',
  'America/Mexico_City',
  'Australia/Sydney',
  'Australia/Melbourne',
  'Pacific/Auckland',
  'UTC',
];

type InviteState = 'loading' | 'valid' | 'error';

const JOIN_CODE_RE = /^[A-Z0-9]{6}$/;
function isJoinCode(token: string): boolean {
  return JOIN_CODE_RE.test(token.toUpperCase());
}

interface LeaguePreview {
  name: string;
  member_count: number;
  max_members: number;
  privacy: string;
}

interface JoinAuthResponse {
  access_token: string;
  refresh_token: string;
  player: {
    id: string;
    display_name: string;
    email?: string | null;
    role: 'player' | 'admin';
    timezone: string;
    avatar_url?: string | null;
  };
}

// Browser onboarding is handled by the shared BrowserOnboarding component.

// ─── Installed PWA join flow ──────────────────────────────────────────────────
// Full functional join — shown only when running inside the installed app.

function AppJoinFlow() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { player } = useAuth();

  const useCode = !!token && isJoinCode(token);

  const [inviteState, setInviteState] = useState<InviteState>('loading');
  const [inviteError, setInviteError] = useState('');
  const [leagueHint, setLeagueHint] = useState('');
  const [leaguePreview, setLeaguePreview] = useState<LeaguePreview | null>(null);

  const [displayName, setDisplayName] = useState('');
  const [pin, setPin] = useState('');
  const [pinConfirm, setPinConfirm] = useState('');
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  );
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!token) {
      setInviteState('error');
      setInviteError('No invite token provided.');
      return;
    }

    if (useCode) {
      fetch(`${BASE}/api/v1/leagues/by-code/${encodeURIComponent(token.toUpperCase())}`)
        .then(async (r) => {
          if (!r.ok) throw new Error('Invalid join code');
          return r.json() as Promise<LeaguePreview>;
        })
        .then((data) => {
          setLeaguePreview(data);
          setLeagueHint(data.name);
          setInviteState('valid');
        })
        .catch(() => {
          setInviteState('error');
          setInviteError('This join code is invalid or the league no longer exists.');
        });
      return;
    }

    fetch(`${BASE}/api/v1/auth/invite/${token}`)
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail ?? 'Invalid invite');
        }
        return r.json();
      })
      .then((data: { display_name_hint: string | null }) => {
        if (data.display_name_hint) setDisplayName(data.display_name_hint);
        setInviteState('valid');
      })
      .catch((err: Error) => {
        setInviteState('error');
        setInviteError(err.message);
      });
  }, [token, useCode]);

  async function handleAuthenticatedClaim() {
    setError('');
    setIsSubmitting(true);
    try {
      const accessToken = getAccessToken();

      if (useCode) {
        const resp = await fetch(`${BASE}/api/v1/leagues/join-by-code`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
          body: JSON.stringify({ code: token!.toUpperCase() }),
        });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          const detail = body.detail ?? 'Failed to join league';
          if (detail === 'ALREADY_MEMBER') throw new Error('You are already a member of this league.');
          if (detail === 'LEAGUE_FULL') throw new Error('This league is full.');
          throw new Error(detail);
        }
        const data = await resp.json() as { league_slug: string; league_name: string };
        navigate(`/leagues/${data.league_slug}`, { replace: true });
        return;
      }

      const resp = await fetch(`${BASE}/api/v1/leagues/claim-invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ token }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        const detail = body.detail ?? 'Failed to join league';
        if (detail === 'ALREADY_MEMBER') throw new Error('You are already a member of this league.');
        if (detail === 'LEAGUE_FULL') throw new Error('This league is full.');
        throw new Error(detail);
      }
      const data = await resp.json() as { league_slug: string; league_name: string };
      setLeagueHint(data.league_name);
      navigate(`/leagues/${data.league_slug}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join league');
      setIsSubmitting(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (pin.length !== 4) {
      setError('PIN must be exactly 4 digits.');
      return;
    }
    if (pin !== pinConfirm) {
      setError('PINs do not match.');
      return;
    }

    setIsSubmitting(true);
    try {
      const endpoint = useCode ? `${BASE}/api/v1/auth/join-by-code` : `${BASE}/api/v1/auth/join`;
      const payload = useCode
        ? { code: token!.toUpperCase(), display_name: displayName.trim(), pin, timezone }
        : { token, display_name: displayName.trim(), pin, timezone };

      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail ?? 'Join failed');
      }
      const data = await resp.json() as JoinAuthResponse;
      const { clearApiCaches, storeTokens } = await import('@/lib/tokens');
      await clearApiCaches();
      storeTokens(data.access_token, data.refresh_token, {
        id: data.player.id,
        displayName: data.player.display_name,
        email: data.player.email ?? null,
        role: data.player.role,
        timezone: data.player.timezone,
        avatarUrl: data.player.avatar_url ?? null,
      });
      window.location.href = '/';
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Join failed');
      setIsSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm space-y-6">
        <div>
          <Brand variant="splash" />
          <p className="text-center text-text-primary mt-6 font-sans text-base sm:text-lg italic">
            {brand.tagline}
          </p>
        </div>

        {inviteState === 'loading' && (
          <p className="text-center text-text-secondary font-sans text-sm">Checking invite…</p>
        )}

        {inviteState === 'error' && (
          <Card>
            <CardContent className="pt-6">
              <p role="alert" className="text-center text-error font-sans text-sm">{inviteError}</p>
              <p className="text-center text-text-muted font-sans text-xs mt-2">
                Ask the league admin to share a new join code or invite link.
              </p>
            </CardContent>
          </Card>
        )}

        {inviteState === 'valid' && player && (
          <Card>
            <CardHeader>
              <CardTitle className="text-center text-text-primary">
                {leagueHint ? `Join ${leagueHint}?` : 'Join the league'}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {leaguePreview && (
                <p className="text-sm text-text-muted font-sans text-center">
                  {leaguePreview.member_count} / {leaguePreview.max_members} members
                </p>
              )}
              <p className="text-sm text-text-secondary font-sans text-center">
                You&apos;re signed in as <strong>{player.displayName}</strong>.
              </p>
              {error && <p role="alert" className="text-xs text-error font-sans">{error}</p>}
              <Button className="w-full" onClick={handleAuthenticatedClaim} disabled={isSubmitting}>
                {isSubmitting ? 'Joining…' : 'Join league'}
              </Button>
            </CardContent>
          </Card>
        )}

        {inviteState === 'valid' && !player && (
          <Card>
            <CardHeader>
              <CardTitle className="text-center text-text-primary">
                {leagueHint ? `Join ${leagueHint}` : 'Join the league'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {leaguePreview && (
                <p className="text-sm text-text-muted font-sans text-center mb-4">
                  {leaguePreview.member_count} / {leaguePreview.max_members} members
                </p>
              )}
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1">
                  <Label htmlFor="displayName">Display name</Label>
                  <Input
                    id="displayName"
                    type="text"
                    autoComplete="username"
                    required
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Your name"
                  />
                </div>

                <div className="space-y-1">
                  <Label>Choose a 4-digit PIN</Label>
                  <PinInput value={pin} onChange={setPin} maxLength={4} autoComplete="new-password" />
                </div>

                <div className="space-y-1">
                  <Label>Confirm PIN</Label>
                  <PinInput value={pinConfirm} onChange={setPinConfirm} maxLength={4} autoComplete="new-password" label="Confirm PIN" />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="timezone">Your timezone</Label>
                  <select
                    id="timezone"
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    className="flex h-10 w-full items-center rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary font-sans focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    {TIMEZONES.map((tz) => (
                      <option key={tz} value={tz}>
                        {tz.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </div>

                {error && <p role="alert" className="text-xs text-error font-sans">{error}</p>}

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? 'Joining…' : 'Join league'}
                </Button>
              </form>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

// ─── Route entry point ────────────────────────────────────────────────────────

export function JoinPage() {
  const { isInstalled, isMobile } = useInstallPrompt();

  // Mobile browser (not the installed PWA): show the shared onboarding page.
  // All joining happens inside the app — nothing to do in the browser.
  if (isMobile && !isInstalled) {
    return <BrowserOnboarding />;
  }

  // Desktop browser or installed PWA: show the functional join flow.
  return <AppJoinFlow />;
}
