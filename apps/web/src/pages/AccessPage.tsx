import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brand } from '@/components/Brand';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { extractActivationCode } from '@/lib/activation';
import { brand } from '@/theme/tokens';

export function AccessPage() {
  const navigate = useNavigate();
  const { activateDevice, isLoading } = useAuth();
  const [value, setValue] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const code = extractActivationCode(value);
    if (!code) {
      setError('Paste the activation link or code Craig sent you.');
      return;
    }
    try {
      await activateDevice(code);
      navigate('/', { replace: true });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Activation failed. Ask Craig for a new link.',
      );
    }
  };

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <Brand variant="splash" size={96} />
          <p className="mt-4 font-sans text-lg font-semibold text-text-primary">{brand.tagline}</p>
          <p className="mt-1 font-sans text-sm italic text-text-secondary">{brand.taglineSub}</p>
        </div>

        <Card className="border-border-strong bg-surface shadow-md">
          <CardHeader>
            <CardTitle className="text-center text-text-primary">Set up this device</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="font-sans text-sm text-text-secondary text-center">
              Paste the one-time activation link Craig sent — or just the code from it — to set up
              this device. There is no PIN or password to remember.
            </p>

            <form className="space-y-3" onSubmit={(event) => void handleSubmit(event)}>
              <div className="space-y-1.5">
                <Label htmlFor="activation-code">Activation link or code</Label>
                <Input
                  id="activation-code"
                  name="activation-code"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  placeholder="https://…/activate?code=…"
                  autoComplete="off"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                />
              </div>

              {error && (
                <p role="alert" className="text-sm font-sans text-error">
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={isLoading || value.trim() === ''}>
                {isLoading ? 'Activating…' : 'Activate this device'}
              </Button>
            </form>

            <p className="font-sans text-xs text-text-muted text-center">
              On iPhone: add this page to your Home Screen first, then open it from the Home Screen
              and paste the link here — don't tap the link in Safari, as it can only be used once.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
