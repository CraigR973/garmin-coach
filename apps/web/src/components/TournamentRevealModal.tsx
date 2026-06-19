/**
 * TournamentRevealModal — shown once on first app open after the opening
 * match kicks off and specials lock.
 *
 * Trigger: `mySpecials.is_locked === true` and the localStorage flag
 * `tournament_reveal_seen` has not been set.
 *
 * The user dismisses it (setting the flag) or taps the CTA to navigate to
 * the global leaderboard (which also dismisses it).
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { MySpecialsResponse } from '../lib/types';
import { Button } from './ui/button';
import { cn } from '../lib/utils';

const SEEN_KEY = 'tournament_reveal_seen';

export function TournamentRevealModal() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const { data: mySpecials } = useQuery<MySpecialsResponse>({
    queryKey: ['specials', 'me'],
    queryFn: () => apiFetch<MySpecialsResponse>('/api/v1/specials'),
    // Don't refetch aggressively — we just need to know if it's locked
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (!mySpecials?.is_locked) return;
    const alreadySeen = localStorage.getItem(SEEN_KEY) === 'true';
    if (!alreadySeen) setOpen(true);
  }, [mySpecials?.is_locked]);

  function dismiss() {
    localStorage.setItem(SEEN_KEY, 'true');
    setOpen(false);
  }

  function goToGlobal() {
    dismiss();
    navigate('/leaderboard/global');
  }

  if (!open) return null;

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={dismiss}
      role="dialog"
      aria-modal="true"
      aria-label="Tournament has started"
    >
      {/* Card — stop click propagation so tapping the card doesn't dismiss */}
      <div
        className="relative w-full max-w-sm rounded-2xl overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Hero graphic */}
        <div
          className={cn(
            'relative flex flex-col items-center justify-center px-6 pt-12 pb-8',
            'bg-gradient-to-br from-[#1a472a] via-[#1e3a5f] to-[#0f1923]',
          )}
        >
          {/* Dismiss button */}
          <button
            onClick={dismiss}
            className="absolute top-3 right-3 rounded-full p-1.5 text-white/60 hover:text-white hover:bg-white/10 transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>

          {/* Ball icon */}
          <div className="text-6xl mb-4 select-none" aria-hidden>⚽</div>

          <p className="font-mono text-[10px] uppercase tracking-[0.3em] text-white/50 mb-2">
            World Cup 2026
          </p>
          <h2 className="font-sans text-2xl font-bold text-white text-center leading-tight mb-1">
            The tournament<br />has kicked off!
          </h2>
          <p className="font-sans text-sm text-white/60 text-center mt-2">
            Specials are now locked — find out who everyone picked.
          </p>
        </div>

        {/* Actions */}
        <div className="bg-surface px-6 py-5 flex flex-col gap-3">
          <Button
            onClick={goToGlobal}
            className="w-full"
            size="lg"
          >
            See global standings →
          </Button>
          <button
            onClick={dismiss}
            className="w-full text-center font-sans text-sm text-text-muted hover:text-text-primary transition-colors py-1"
          >
            Maybe later
          </button>
        </div>
      </div>
    </div>
  );
}
