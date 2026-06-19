import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PinInput } from '@/components/PinInput';
import { Brand } from '@/components/Brand';

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export function PinResetPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();

  const [pin, setPin] = useState('');
  const [confirmPin, setConfirmPin] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [tokenError, setTokenError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (pin.length !== 4) {
      setError('Please enter a 4-digit PIN.');
      return;
    }
    if (pin !== confirmPin) {
      setError('PINs do not match.');
      return;
    }

    setIsLoading(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/auth/pin/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_pin: pin }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const detail: string = err.detail ?? 'Reset failed';
        if (detail.toLowerCase().includes('expired')) {
          setTokenError('expired');
        } else {
          setTokenError('invalid');
        }
        return;
      }
      navigate('/login', { replace: true, state: { pinReset: true } });
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }

  if (tokenError) {
    return (
      <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
        <div className="w-full max-w-sm">
          <div className="mb-10">
            <Brand variant="splash" />
          </div>
          <Card>
            <CardHeader>
              <CardTitle className="text-center text-text-primary">Link {tokenError === 'expired' ? 'Expired' : 'Invalid'}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-center">
              <p className="text-sm font-sans text-text-secondary">
                {tokenError === 'expired'
                  ? 'This reset link has expired. Reset links are valid for a short time — please request a new one.'
                  : 'This reset link is invalid or has already been used.'}
              </p>
              <Link
                to="/forgot-pin"
                className="block text-xs font-sans text-primary hover:underline underline-offset-2"
              >
                Request a new reset link
              </Link>
              <Link
                to="/login"
                className="block text-xs font-sans text-text-muted hover:text-text-primary transition-colors"
              >
                Back to sign in
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-10">
          <Brand variant="splash" />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-center text-text-primary">Choose a new PIN</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <p className="text-xs font-mono uppercase tracking-widest text-text-muted">New PIN</p>
                <PinInput
                  value={pin}
                  onChange={setPin}
                  maxLength={4}
                  autoComplete="new-password"
                  label="New PIN"
                />
              </div>

              <div className="space-y-2">
                <p className="text-xs font-mono uppercase tracking-widest text-text-muted">Confirm PIN</p>
                <PinInput
                  value={confirmPin}
                  onChange={setConfirmPin}
                  maxLength={4}
                  autoComplete="new-password"
                  label="Confirm PIN"
                />
              </div>

              {error && (
                <p role="alert" className="text-xs text-error font-sans">
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={isLoading || pin.length !== 4 || confirmPin.length !== 4}>
                {isLoading ? 'Saving…' : 'Set new PIN'}
              </Button>

              <div className="text-center">
                <Link
                  to="/login"
                  className="text-xs font-sans text-text-muted hover:text-text-primary transition-colors"
                >
                  Back to sign in
                </Link>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
