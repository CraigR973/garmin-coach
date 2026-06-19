import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Brand } from '@/components/Brand';

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export function ForgotPinPage() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/auth/pin/reset-request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail ?? 'Request failed');
      }
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-10">
          <Brand variant="splash" />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-center text-text-primary">Reset PIN</CardTitle>
          </CardHeader>
          <CardContent>
            {submitted ? (
              <div className="space-y-4 text-center">
                <p className="text-sm font-sans text-text-secondary">
                  If that email is registered and verified, you'll receive a reset link shortly.
                  Check your inbox (and spam folder).
                </p>
                <Link
                  to="/login"
                  className="block text-xs font-sans text-primary hover:underline underline-offset-2"
                >
                  Back to sign in
                </Link>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <p className="text-sm font-sans text-text-secondary">
                  Enter your email address and we'll send you a link to reset your PIN.
                </p>

                <div className="space-y-1">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                  />
                </div>

                {error && (
                  <p role="alert" className="text-xs text-error font-sans">
                    {error}
                  </p>
                )}

                <Button type="submit" className="w-full" disabled={isLoading}>
                  {isLoading ? 'Sending…' : 'Send reset link'}
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
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
