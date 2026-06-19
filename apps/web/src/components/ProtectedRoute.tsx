import { Navigate, Outlet, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { PinInput } from './PinInput';

interface Props {
  requireAdmin?: boolean;
}

export function ProtectedRoute({ requireAdmin = false }: Props) {
  const { player, sessionUnlockRequired } = useAuth();

  if (sessionUnlockRequired) {
    return <PinUnlockGate />;
  }

  if (!player) {
    return <Navigate to="/login" replace />;
  }

  if (requireAdmin && player.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}

function PinUnlockGate() {
  const { isLoading, logout, player, sessionUnlockError, unlockStoredSession } = useAuth();
  const navigate = useNavigate();
  const [pin, setPin] = useState('');

  const handleUnlock = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await unlockStoredSession(pin);
    } catch {
      setPin('');
    }
  };

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4 pt-safe pb-safe">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-center text-text-primary">Unlock Garmin Coach</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-text-secondary font-sans text-center">
            Re-enter your PIN to reopen this saved session.
          </p>

          {player && (
            <p className="text-xs text-text-muted font-sans text-center">
              Signed in as <span className="font-semibold text-text-primary">{player.displayName}</span> — not you?{' '}
              <button
                type="button"
                className="text-primary underline-offset-2 hover:underline"
                onClick={() => void logout()}
              >
                Log out
              </button>
            </p>
          )}

          {sessionUnlockError && (
            <p role="alert" className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning font-sans">
              {sessionUnlockError}
            </p>
          )}

          <form className="space-y-4" onSubmit={(event) => void handleUnlock(event)}>
            <PinInput value={pin} onChange={setPin} autoComplete="current-password" />
            <Button type="submit" className="w-full" disabled={isLoading || pin.length !== 4}>
              {isLoading ? 'Checking…' : 'Unlock with PIN'}
            </Button>
          </form>

          <Button type="button" variant="outline" className="w-full" onClick={() => navigate('/login', { replace: true })}>
            Sign in another way
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
