import { useAuth } from '../contexts/AuthContext';

export function DashboardPage() {
  const { player } = useAuth();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight text-text-primary">
        Good morning{player ? `, ${player.displayName}` : ''}
      </h1>
      <p className="text-text-secondary">
        Your daily coaching brief will appear here once Phase 1 is complete.
      </p>
    </div>
  );
}
