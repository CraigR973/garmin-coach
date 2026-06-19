import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';
import { useCountdown } from '../hooks/useCountdown';
import type { MatchResponse } from '../lib/types';

// ---------------------------------------------------------------------------
// SVG silhouette — 16 greyscale R32 placeholder boxes, split into two halves
// with a faint accent divider between them.
// ---------------------------------------------------------------------------

const BOX_W = 80;
const BOX_H = 14;
const BOX_GAP = 4;
const HALF_GAP = 16;
const SLOT = BOX_H + BOX_GAP;
const SVG_H = 8 * SLOT + HALF_GAP + 8 * SLOT - BOX_GAP;
const SVG_W = BOX_W;

function R32Silhouette() {
  const boxes = Array.from({ length: 16 }, (_, i) => {
    const half = i < 8 ? 0 : 1;
    const idx = i < 8 ? i : i - 8;
    const y = half === 0
      ? idx * SLOT
      : 8 * SLOT + HALF_GAP + idx * SLOT;
    return { i, y };
  });

  const dividerY = 8 * SLOT + HALF_GAP / 2;

  return (
    <svg
      width={SVG_W}
      height={SVG_H}
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      aria-hidden="true"
      className="block opacity-40"
    >
      {boxes.map(({ i, y }) => (
        <rect
          key={i}
          x={0}
          y={y}
          width={BOX_W}
          height={BOX_H}
          rx={3}
          className="fill-text-muted/30"
        />
      ))}
      {/* Brass/accent divider hint between halves */}
      <line
        x1={0}
        y1={dividerY}
        x2={BOX_W}
        y2={dividerY}
        className="stroke-accent/50"
        strokeWidth={1}
        strokeDasharray="4 3"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Countdown display
// ---------------------------------------------------------------------------

function KickoffCountdown({ kickoffUtc }: { kickoffUtc: string }) {
  const { days, hours, minutes, seconds, expired } = useCountdown(kickoffUtc);
  if (expired) return null;
  const label =
    days > 0
      ? `${days}d ${hours}h`
      : hours > 0
        ? `${hours}h ${minutes}m`
        : `${minutes}m ${seconds}s`;
  return (
    <span className="font-mono text-sm tabular-nums text-text-secondary" aria-live="off">
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// BracketTeaser
// ---------------------------------------------------------------------------

interface BracketTeaserProps {
  /** Main heading inside the teaser */
  title: string;
  /** Label on the CTA button */
  ctaLabel: string;
  /** Route the CTA links to */
  ctaTo: string;
}

export function BracketTeaser({ title, ctaLabel, ctaTo }: BracketTeaserProps) {
  const { data: matches = [] } = useQuery<MatchResponse[]>({
    queryKey: ['matches', 'r32-first'],
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches?stage=r32&limit=1'),
    staleTime: 5 * 60_000,
  });

  const firstKickoff = matches[0]?.kickoff_utc ?? null;

  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center text-center py-10 px-4 rounded-lg border border-dashed border-border bg-surface/30"
    >
      <R32Silhouette />

      <p className="mt-5 text-base font-semibold text-text-primary font-sans tracking-tight">
        {title}
      </p>

      {firstKickoff ? (
        <div className="mt-2 flex flex-col items-center gap-0.5">
          <span className="text-xs font-mono text-text-muted uppercase tracking-widest">
            Kicks off in
          </span>
          <KickoffCountdown kickoffUtc={firstKickoff} />
        </div>
      ) : (
        <p className="mt-2 text-sm text-text-muted font-sans">—</p>
      )}

      <Link
        to={ctaTo}
        className="mt-5 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline font-sans"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}
