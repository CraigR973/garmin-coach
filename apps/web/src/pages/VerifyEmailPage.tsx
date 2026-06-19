import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Brand } from '@/components/Brand';

const BASE = import.meta.env.VITE_API_URL ?? '';

type State = 'verifying' | 'success' | 'error';

export function VerifyEmailPage() {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<State>('verifying');
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    if (!token) {
      setState('error');
      setErrorMsg('No verification token provided.');
      return;
    }
    fetch(`${BASE}/api/v1/auth/verify-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail ?? 'Verification failed');
        }
        setState('success');
      })
      .catch((err: Error) => {
        setState('error');
        setErrorMsg(err.message);
      });
  }, [token]);

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-10">
          <Brand variant="splash" />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-center text-text-primary">
              {state === 'verifying' && 'Verifying email…'}
              {state === 'success' && 'Email verified!'}
              {state === 'error' && 'Verification failed'}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {state === 'verifying' && (
              <p className="text-center text-text-secondary font-sans text-sm">
                Just a moment…
              </p>
            )}

            {state === 'success' && (
              <>
                <p className="text-center text-text-secondary font-sans text-sm">
                  Your email has been confirmed. PIN reset is now available if you ever need it.
                </p>
                <Button asChild className="w-full">
                  <Link to="/">Go to home</Link>
                </Button>
              </>
            )}

            {state === 'error' && (
              <>
                <p role="alert" className="text-center text-error font-sans text-sm">
                  {errorMsg}
                </p>
                <p className="text-center text-text-muted font-sans text-xs">
                  The link may have expired. Sign in and request a new one from Settings.
                </p>
                <Button asChild variant="outline" className="w-full">
                  <Link to="/login">Back to login</Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
