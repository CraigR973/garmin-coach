import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';
import { enqueuePrediction } from '../lib/offlineQueue';
import { supabase } from '../lib/supabase';
import { canEdit } from '../lib/matchStatus';
import type { MatchResponse, PredictionResponse } from '../lib/types';

// ---------------------------------------------------------------------------
// Local editing state
// ---------------------------------------------------------------------------

export interface LocalPrediction {
  home: string;
  away: string;
  dirty: boolean;
  saving: boolean;
}

export type LocalPredictions = Record<string, LocalPrediction>;

function initLocal(predictions: PredictionResponse[]): LocalPredictions {
  const result: LocalPredictions = {};
  for (const p of predictions) {
    result[p.match_id] = {
      home: p.predicted_home !== null ? String(p.predicted_home) : '',
      away: p.predicted_away !== null ? String(p.predicted_away) : '',
      dirty: false,
      saving: false,
    };
  }
  return result;
}

const DEBOUNCE_MS = 800;

// ---------------------------------------------------------------------------
// usePredictionEditor — the shared prediction-editing stack.
//
// Owns: optimistic local score state, debounced autosave (PUT
// /predictions/{matchId}), an offline write-queue fallback, error rollback to
// last server-confirmed values, and the realtime result-flash subscription.
//
// Data fetching stays with the caller (the Predictions page and the home
// carousel both read the `['matches','group']` + `['predictions','me']` query
// keys, so React Query dedupes the two screens onto one set of requests).
// ---------------------------------------------------------------------------

export interface PredictionEditor {
  local: LocalPredictions;
  highlightedMatchIds: Set<string>;
  handleHomeChange: (matchId: string, value: string) => void;
  handleAwayChange: (matchId: string, value: string) => void;
  /** Flush every dirty, editable, fully-filled match in the list immediately. */
  handleSaveAll: (groupMatches: MatchResponse[]) => void;
}

export function usePredictionEditor({
  predictions,
  matches,
  matchesQueryKey = ['matches', 'group'],
}: {
  predictions: PredictionResponse[];
  matches: MatchResponse[];
  matchesQueryKey?: QueryKey;
}): PredictionEditor {
  const queryClient = useQueryClient();

  const [local, setLocal] = useState<LocalPredictions>({});
  const [highlightedMatchIds, setHighlightedMatchIds] = useState<Set<string>>(new Set());
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  // Track which match IDs had a null score before the last Realtime update.
  const prevScoresRef = useRef<Record<string, boolean>>({});

  // Init local state from server predictions (once loaded), preserving any
  // dirty/saving local edits the user has already typed.
  useEffect(() => {
    if (predictions.length > 0) {
      setLocal((prev) => {
        const next = initLocal(predictions);
        for (const matchId of Object.keys(prev)) {
          if (prev[matchId].dirty || prev[matchId].saving) {
            next[matchId] = prev[matchId];
          }
        }
        return next;
      });
    }
  }, [predictions]);

  // Keep a shadow of which matches had null scores so we can detect result arrival.
  useEffect(() => {
    for (const m of matches) {
      prevScoresRef.current[m.id] = m.actual_home_score === null;
    }
  }, [matches]);

  useEffect(
    () => () => {
      for (const timer of Object.values(debounceTimers.current)) {
        clearTimeout(timer);
      }
    },
    [],
  );

  // Realtime: subscribe to matches table — when a result is set, refetch and animate.
  useEffect(() => {
    const channel = supabase
      .channel('predictions-match-results')
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'matches' },
        async (payload) => {
          const updated = payload.new as {
            id: string;
            actual_home_score: number | null;
            actual_away_score: number | null;
          };
          const wasNull = prevScoresRef.current[updated.id] ?? true;
          const nowSet = updated.actual_home_score !== null && updated.actual_away_score !== null;

          // Invalidate matches so the card shows the new score.
          await queryClient.invalidateQueries({ queryKey: matchesQueryKey });

          if (wasNull && nowSet) {
            // Result just arrived — refetch predictions to get updated points, then toast.
            const fresh = await queryClient.fetchQuery<PredictionResponse[]>({
              queryKey: ['predictions', 'me'],
              queryFn: () => apiFetch<PredictionResponse[]>('/api/v1/predictions/me'),
            });
            const pred = fresh.find((p) => p.match_id === updated.id);
            const pts = pred?.points_awarded ?? null;

            if (pts !== null) {
              toast.success(
                `Result: ${updated.actual_home_score}–${updated.actual_away_score} · You scored ${pts} pt${pts !== 1 ? 's' : ''}`,
                { duration: 6000 },
              );
            }

            // Flash the card for 2.5 s.
            setHighlightedMatchIds((prev) => new Set([...prev, updated.id]));
            setTimeout(() => {
              setHighlightedMatchIds((prev) => {
                const next = new Set(prev);
                next.delete(updated.id);
                return next;
              });
            }, 2500);
          }
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [matchesQueryKey, queryClient]);

  const savePrediction = useCallback(
    async (matchId: string, home: string, away: string) => {
      if (home === '' || away === '') return;
      setLocal((prev) => ({
        ...prev,
        [matchId]: { ...prev[matchId], saving: true },
      }));

      // Offline: persist to the write queue, keep the optimistic local value,
      // and let `useOfflineQueue` replay on the next `online` event.
      if (!navigator.onLine) {
        enqueuePrediction({ matchId, home: Number(home), away: Number(away) });
        setLocal((prev) => ({
          ...prev,
          [matchId]: { ...prev[matchId], dirty: false, saving: false },
        }));
        toast.success('Saved offline — will sync when you’re back online');
        return;
      }

      try {
        await apiFetch(`/api/v1/predictions/${matchId}`, {
          method: 'PUT',
          body: JSON.stringify({ predicted_home: Number(home), predicted_away: Number(away) }),
        });
        setLocal((prev) => ({
          ...prev,
          [matchId]: { ...prev[matchId], dirty: false, saving: false },
        }));
      } catch {
        // If the fetch failed because we went offline mid-request, enqueue rather
        // than roll back. Otherwise (server error while online) roll back to last
        // server-confirmed values and notify the user to retry.
        if (!navigator.onLine) {
          enqueuePrediction({ matchId, home: Number(home), away: Number(away) });
          setLocal((prev) => ({
            ...prev,
            [matchId]: { ...prev[matchId], dirty: false, saving: false },
          }));
          toast.success('Saved offline — will sync when you’re back online');
          return;
        }
        const serverPreds =
          queryClient.getQueryData<PredictionResponse[]>(['predictions', 'me']) ?? [];
        const sp = serverPreds.find((p) => p.match_id === matchId);
        setLocal((prev) => ({
          ...prev,
          [matchId]: {
            home: sp?.predicted_home != null ? String(sp.predicted_home) : '',
            away: sp?.predicted_away != null ? String(sp.predicted_away) : '',
            dirty: false,
            saving: false,
          },
        }));
        toast.error('Prediction not saved — check your connection and try again');
      }
    },
    [queryClient],
  );

  const scheduleDebounce = useCallback(
    (matchId: string, home: string, away: string) => {
      clearTimeout(debounceTimers.current[matchId]);
      debounceTimers.current[matchId] = setTimeout(() => {
        savePrediction(matchId, home, away);
      }, DEBOUNCE_MS);
    },
    [savePrediction],
  );

  const handleHomeChange = useCallback(
    (matchId: string, value: string) => {
      setLocal((prev) => {
        const cur = prev[matchId] ?? { home: '', away: '', dirty: false, saving: false };
        const next = { ...cur, home: value, dirty: true };
        scheduleDebounce(matchId, value, cur.away);
        return { ...prev, [matchId]: next };
      });
    },
    [scheduleDebounce],
  );

  const handleAwayChange = useCallback(
    (matchId: string, value: string) => {
      setLocal((prev) => {
        const cur = prev[matchId] ?? { home: '', away: '', dirty: false, saving: false };
        const next = { ...cur, away: value, dirty: true };
        scheduleDebounce(matchId, cur.home, value);
        return { ...prev, [matchId]: next };
      });
    },
    [scheduleDebounce],
  );

  const handleSaveAll = useCallback(
    (groupMatches: MatchResponse[]) => {
      for (const match of groupMatches) {
        if (!canEdit(match.status)) continue;
        const l = local[match.id];
        if (!l || l.home === '' || l.away === '') continue;
        clearTimeout(debounceTimers.current[match.id]);
        savePrediction(match.id, l.home, l.away);
      }
    },
    [local, savePrediction],
  );

  return { local, highlightedMatchIds, handleHomeChange, handleAwayChange, handleSaveAll };
}
