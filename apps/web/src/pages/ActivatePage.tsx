import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brand } from '@/components/Brand';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { storeDeviceToken, type StoredPlayer } from '@/lib/tokens';
import { brand } from '@/theme/tokens';

if (import.meta.env.PROD && import.meta.env.VITE_API_URL === undefined) {
  throw new Error('VITE_API_URL is required in production builds');
}

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

type ActivateState = 'activating' | 'error';

function playerFromApiResponse(data: {
  player: { id: string; display_name: string; role: string; timezone: string };
}): StoredPlayer {
  return {
    id: data.player.id,
    displayName: data.player.display_name,
    role: data.player.role as 'player' | 'admin',
    timezone: data.player.timezone,
  };
}

export function ActivatePage() {
  const navigate = useNavigate();
  const [state, setState] = useState<ActivateState>('activating');
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function activate() {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const code = params.get('code');
      if (!code) {
        setState('error');
        setError('This activation link is missing its code. Ask Craig for a new link.');
        return;
      }

      try {
        const resp = await fetch(`${BASE}/api/v1/auth/activate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(
            (body as { detail?: string }).detail ?? 'Activation failed. Ask Craig for a new link.',
          );
        }

        const data = await resp.json();
        if (cancelled) return;

        const player = playerFromApiResponse(data);
        storeDeviceToken(data.device_token, player);
        window.history.replaceState(null, '', '/activate');
        navigate('/', { replace: true });
      } catch (err) {
        if (cancelled) return;
        setState('error');
        setError(
          err instanceof Error ? err.message : 'Activation failed. Ask Craig for a new link.',
        );
      }
    }

    void activate();

    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <Brand variant="splash" />
          <p className="mt-6 font-sans text-lg font-semibold text-text-primary">{brand.tagline}</p>
          <p className="mt-1 font-sans text-sm italic text-text-secondary">{brand.taglineSub}</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-center text-text-primary">
              {state === 'activating' ? 'Activating this device' : 'Activation failed'}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-center">
            {state === 'activating' ? (
              <p className="text-sm font-sans text-text-secondary">
                Setting this phone up for Garmin Coach. This should only take a moment.
              </p>
            ) : (
              <>
                <p role="alert" className="text-sm font-sans text-error">
                  {error}
                </p>
                <Button type="button" variant="outline" className="w-full" onClick={() => navigate('/login', { replace: true })}>
                  Back to sign in
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
