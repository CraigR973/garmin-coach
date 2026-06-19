import React, {
  createContext,
  useCallback,
  useContext,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';
import type { LeagueSummary } from '../lib/types';

interface LeagueContextValue {
  leagues: LeagueSummary[];
  isLoading: boolean;
  refetch: () => void;
}

const LeagueContext = createContext<LeagueContextValue | null>(null);

export function LeagueProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();

  const { data: leagues = [], isLoading } = useQuery<LeagueSummary[]>({
    queryKey: ['leagues', 'mine'],
    queryFn: () => apiFetch<LeagueSummary[]>('/api/v1/leagues/mine'),
    staleTime: 60_000,
  });

  const refetchLeagues = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['leagues', 'mine'] });
  }, [queryClient]);

  return (
    <LeagueContext.Provider
      value={{
        leagues,
        isLoading,
        refetch: refetchLeagues,
      }}
    >
      {children}
    </LeagueContext.Provider>
  );
}

export function useLeague(): LeagueContextValue {
  const ctx = useContext(LeagueContext);
  if (!ctx) throw new Error('useLeague must be used within LeagueProvider');
  return ctx;
}
