import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { ArrowRight } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { usePredictionEditor } from '../hooks/usePredictionEditor';
import { PredictionCard } from './PredictionCard';
import { Skeleton } from './ui/skeleton';
import type { MatchResponse, PredictionResponse } from '../lib/types';

// Cap on how many upcoming cards the carousel shows before the "see full
// schedule" affordance. The full list lives at /schedule.
const MAX_CARDS = 8;

// Statuses the carousel surfaces: scheduled only (open to predict).
// Locked matches have closed prediction windows and would imply you can still
// act; live moves to the U27 hub; completed/knockout excluded.
const CAROUSEL_STATUSES = new Set<MatchResponse['status']>([
  'scheduled',
]);

// Shared section-title styling — real bold titles, sentence case (U20 v2).
const SECTION_LABEL_CLS =
  'mb-2 px-0.5 text-lg font-bold tracking-tight text-text-primary';

function teamName(
  team: MatchResponse['home_team'],
  placeholder: string | null,
): string {
  return team?.name ?? placeholder ?? 'TBD';
}

// ---------------------------------------------------------------------------
// UpcomingMatchesCarousel (U19.3/U19.4)
//
// A scroll-snapped, keyboard-accessible row of the next few *scheduled,
// not-locked* group-stage matches, each an inline-editable PredictionCard
// backed by the shared usePredictionEditor (debounced, offline-safe). Knockout
// matches are excluded in v1. Ends with a "See full schedule →" card.
//
// Reads the same query keys as the Predictions page, so the two screens share
// one set of requests rather than refetching per card.
// ---------------------------------------------------------------------------

export function UpcomingMatchesCarousel() {
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';

  const { data: matches = [], isLoading: matchesLoading } = useQuery<MatchResponse[]>({
    queryKey: ['matches', 'group'],
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches?stage=group'),
    staleTime: 30_000,
  });

  const { data: predictions = [], isLoading: predsLoading } = useQuery<PredictionResponse[]>({
    queryKey: ['predictions', 'me'],
    queryFn: () => apiFetch<PredictionResponse[]>('/api/v1/predictions/me'),
    staleTime: 30_000,
  });

  const { local, highlightedMatchIds, handleHomeChange, handleAwayChange } =
    usePredictionEditor({ predictions, matches });

  const predByMatch = useMemo(
    () => Object.fromEntries(predictions.map((p) => [p.match_id, p])),
    [predictions],
  );

  // Next N scheduled / locked / live group-stage matches, soonest first.
  const upcoming = useMemo(
    () =>
      matches
        .filter((m) => m.stage === 'group' && CAROUSEL_STATUSES.has(m.status))
        .sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc))
        .slice(0, MAX_CARDS),
    [matches],
  );

  const isLoading = matchesLoading || predsLoading;

  if (isLoading) {
    return (
      <section aria-labelledby="home-upcoming-label">
        <h2 id="home-upcoming-label" className={SECTION_LABEL_CLS}>
          Upcoming
        </h2>
        <div className="flex gap-3 overflow-hidden">
          <Skeleton className="h-[132px] w-[280px] shrink-0 rounded-lg" />
          <Skeleton className="h-[132px] w-[280px] shrink-0 rounded-lg" />
        </div>
      </section>
    );
  }

  // Nothing open to predict — self-hide (consistent with the other home zones).
  if (upcoming.length === 0) return null;

  return (
    <section aria-labelledby="home-upcoming-label">
      <h2 id="home-upcoming-label" className={SECTION_LABEL_CLS}>
        Upcoming Matches
      </h2>

      <ul
        role="list"
        aria-label="Upcoming matches"
        tabIndex={0}
        className="flex snap-x snap-mandatory gap-3 overflow-x-auto overscroll-x-contain pb-2 focus-visible:outline-none focus-visible:shadow-glow motion-safe:scroll-smooth"
      >
        {upcoming.map((m) => {
          const label = `${teamName(m.home_team, m.home_team_placeholder)} versus ${teamName(
            m.away_team,
            m.away_team_placeholder,
          )}, ${formatInTimeZone(new Date(m.kickoff_utc), timezone, 'EEE d MMM, HH:mm')}`;
          return (
            <li key={m.id} className="w-[300px] shrink-0 snap-start">
              <div role="group" aria-label={label} className="h-full">
                <PredictionCard
                  match={m}
                  prediction={predByMatch[m.id]}
                  local={local[m.id]}
                  timezone={timezone}
                  highlighted={highlightedMatchIds.has(m.id)}
                  onHomeChange={handleHomeChange}
                  onAwayChange={handleAwayChange}
                  compact
                />
              </div>
            </li>
          );
        })}

        {/* Terminal card — jump to the full schedule */}
        <li className="w-[160px] shrink-0 snap-start">
          <Link
            to="/schedule"
            data-testid="carousel-see-all"
            className="group flex h-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface p-4 text-center transition-colors hover:border-primary/50 hover:bg-surface-elevated focus-visible:outline-none focus-visible:shadow-glow"
          >
            <span className="font-sans text-sm font-medium text-text-primary">
              See full schedule
            </span>
            <ArrowRight
              className="h-4 w-4 text-text-muted transition-transform group-hover:translate-x-0.5"
              aria-hidden
            />
          </Link>
        </li>
      </ul>
    </section>
  );
}
