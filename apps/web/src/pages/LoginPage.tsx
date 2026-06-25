import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PinInput } from '@/components/PinInput';
import { Brand } from '@/components/Brand';
import { brand } from '@/theme/tokens';

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  // Default to the invite screen — device-token activation is the primary path.
  // The PIN form is kept as a reversible fallback behind a toggle (auth Phase 2;
  // the PIN path is removed entirely in Phase 3).
  const [showPin, setShowPin] = useState(false);
  const [displayName, setDisplayName] = useState('');
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      await login(displayName.trim(), pin);
      navigate('/', { replace: true });
    } catch {
      setError('Invalid name or PIN.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <Brand variant="splash" />
          <p className="mt-6 font-sans text-lg font-semibold text-text-primary">{brand.tagline}</p>
          <p className="mt-1 font-sans text-sm italic text-text-secondary">{brand.taglineSub}</p>
        </div>

        {!showPin ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-center text-text-primary">Invite only</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="font-sans text-sm text-text-secondary text-center">
                To use CheckMark on this device, ask Craig for an activation link and open it
                here. The link signs you in once — there's no password to remember.
              </p>
              <div className="text-center">
                <button
                  type="button"
                  onClick={() => setShowPin(true)}
                  className="text-xs font-sans text-text-muted hover:text-text-primary transition-colors underline-offset-2 hover:underline"
                >
                  Use a PIN instead
                </button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="text-center text-text-primary">Sign in with PIN</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1">
                  <Label htmlFor="display-name">Name</Label>
                  <Input
                    id="display-name"
                    type="text"
                    autoComplete="username"
                    required
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Your name"
                  />
                </div>

                <div className="space-y-1">
                  <Label>PIN</Label>
                  <PinInput value={pin} onChange={setPin} maxLength={4} />
                </div>

                {error && (
                  <p role="alert" className="text-xs text-error font-sans">
                    {error}
                  </p>
                )}

                <Button type="submit" className="w-full" disabled={isLoading}>
                  {isLoading ? 'Signing in…' : 'Sign in'}
                </Button>

                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => setShowPin(false)}
                    className="text-xs font-sans text-text-muted hover:text-text-primary transition-colors"
                  >
                    ← Back
                  </button>
                  <Link
                    to="/forgot-pin"
                    className="text-xs font-sans text-text-muted hover:text-text-primary transition-colors"
                  >
                    Forgot PIN?
                  </Link>
                </div>
              </form>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
