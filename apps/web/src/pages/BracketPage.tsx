import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';
import { shortPlaceholder } from '../lib/matchTeam';
import { useAuth } from '../contexts/AuthContext';
import { Skeleton } from '../components/ui/skeleton';
import { BracketTeaser } from '../components/BracketTeaser';
import { PageHeader } from '../components/PageHeader';
import type { MatchResponse, KnockoutPredictionResponse } from '../lib/types';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Same palette as LeaderboardHistoryPage — stable per-player colour
// assignment. Greens are reserved for brand/"correct" semantics, so the
// player chips skip them in favour of two slate neutrals.
const PALETTE = [
  '#94a3b8', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#f97316', '#cbd5e1', '#a855f7',
  '#84cc16', '#0ea5e9', '#fb923c', '#d946ef', '#64748b',
];

const ROUNDS = ['r32', 'r16', 'qf', 'sf', 'final'] as const;
type Round = (typeof ROUNDS)[number];

const ROUND_LABELS: Record<Round, string> = {
  r32: 'Round of 32',
  r16: 'Round of 16',
  qf: 'Quarter-Finals',
  sf: 'Semi-Finals',
  final: 'Final',
};

// Layout
const BOX_W = 168;
const BOX_H = 52;
const COL_GAP = 40;
const R32_GAP = 14;
const PADDING = 24;
const LABEL_H = 28;

// Derived heights
const R32_COUNT = 16;
const R32_SLOT_H = BOX_H + R32_GAP; // 66
const BRACKET_H = R32_COUNT * R32_SLOT_H - R32_GAP; // 16*52 + 15*14 = 1042 → 16*66 - 14 = 1042

// 3rd-place block (separate, below SF column)
const TP_BLOCK_TOP_OFFSET = 20;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function playerColor(playerId: string | undefined): string {
  if (!playerId) return PALETTE[0];
  let h = 0;
  for (let i = 0; i < playerId.length; i++) {
    h = (h * 31 + playerId.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(h) % PALETTE.length];
}

function actualWinnerId(m: MatchResponse): string | null {
  if (m.status !== 'completed') return null;
  if (m.actual_home_score === null || m.actual_away_score === null) return null;
  if (m.actual_home_score > m.actual_away_score) return m.home_team?.id ?? null;
  if (m.actual_away_score > m.actual_home_score) return m.away_team?.id ?? null;
  // Draw → penalty decides, but penalty_winner_id is not in MatchResponse.
  // Leave as null until result is unambiguous in the schema.
  return null;
}

function teamLabel(team: MatchResponse['home_team'], placeholder: string | null): string {
  if (team) return `${team.flag_emoji} ${team.name}`;
  return shortPlaceholder(placeholder);
}

// Returns the centre-Y of match index `i` in a round of `count` matches.
// Layout assumes adjacent match_number ordering pairs into the next round
// — a schematic visualisation, not a strict pairing graph
// (admin reshuffles per-arch-doc remain visually adjacent).
function matchCenterY(roundIndex: number, indexInRound: number): number {
  const spacing = R32_SLOT_H * Math.pow(2, roundIndex);
  return PADDING + LABEL_H + spacing / 2 + indexInRound * spacing - BOX_H / 2 + BOX_H / 2;
}

function matchTopY(roundIndex: number, indexInRound: number): number {
  return matchCenterY(roundIndex, indexInRound) - BOX_H / 2;
}

function columnX(roundIndex: number): number {
  return PADDING + roundIndex * (BOX_W + COL_GAP);
}

// ---------------------------------------------------------------------------
// Match node (rendered as foreignObject so we can use Tailwind)
// ---------------------------------------------------------------------------

function MatchBox({
  x,
  y,
  match,
  myWinnerId,
  myColor,
}: {
  x: number;
  y: number;
  match: MatchResponse;
  myWinnerId: string | null;
  myColor: string;
}) {
  const homeId = match.home_team?.id ?? null;
  const awayId = match.away_team?.id ?? null;
  const winnerId = actualWinnerId(match);
  const isCompleted = match.status === 'completed';

  const homeLabel = teamLabel(match.home_team, match.home_team_placeholder);
  const awayLabel = teamLabel(match.away_team, match.away_team_placeholder);

  const homePicked = myWinnerId !== null && myWinnerId === homeId;
  const awayPicked = myWinnerId !== null && myWinnerId === awayId;

  const homeCorrect = isCompleted && homePicked && winnerId !== null && winnerId === homeId;
  const awayCorrect = isCompleted && awayPicked && winnerId !== null && winnerId === awayId;
  const homeWrong = isCompleted && homePicked && winnerId !== null && winnerId !== homeId;
  const awayWrong = isCompleted && awayPicked && winnerId !== null && winnerId !== awayId;

  const homeIsActualWinner = isCompleted && winnerId !== null && winnerId === homeId;
  const awayIsActualWinner = isCompleted && winnerId !== null && winnerId === awayId;

  function rowClass(picked: boolean, correct: boolean, wrong: boolean, actualWinner: boolean): string {
    const base = 'flex items-center justify-between gap-1 px-1.5 py-0.5 leading-tight';
    if (correct) return `${base} font-semibold`;
    if (wrong) return `${base} text-text-muted line-through`;
    if (picked) return `${base} font-medium`;
    if (actualWinner) return `${base} font-medium`;
    return `${base} text-text-secondary`;
  }

  function rowStyle(picked: boolean, correct: boolean, wrong: boolean): React.CSSProperties {
    if (correct) return { backgroundColor: 'rgba(34,197,94,0.15)', color: '#22c55e' };
    if (wrong) return {};
    if (picked) return { backgroundColor: `${myColor}26`, color: myColor }; // 26 = 15% alpha
    return {};
  }

  return (
    <foreignObject x={x} y={y} width={BOX_W} height={BOX_H}>
      <div
        data-testid={`bracket-match-${match.id}`}
        data-match-id={match.id}
        className="h-full w-full rounded-md border bg-surface flex flex-col justify-between text-[11px] font-sans overflow-hidden"
        style={{
          borderColor: homePicked || awayPicked ? myColor : 'var(--color-border, #2a2a2a)',
        }}
      >
        <div
          className={rowClass(homePicked, homeCorrect, homeWrong, homeIsActualWinner)}
          style={rowStyle(homePicked, homeCorrect, homeWrong)}
          data-team-id={homeId ?? ''}
          data-picked={homePicked ? 'true' : 'false'}
          data-correct={homeCorrect ? 'true' : 'false'}
          data-wrong={homeWrong ? 'true' : 'false'}
        >
          <span className="truncate" title={match.home_team ? undefined : (match.home_team_placeholder ?? undefined)}>{homeLabel}</span>
          {isCompleted && match.actual_home_score !== null && (
            <span className="font-mono text-text-muted shrink-0">{match.actual_home_score}</span>
          )}
        </div>
        <div className="h-px bg-border" />
        <div
          className={rowClass(awayPicked, awayCorrect, awayWrong, awayIsActualWinner)}
          style={rowStyle(awayPicked, awayCorrect, awayWrong)}
          data-team-id={awayId ?? ''}
          data-picked={awayPicked ? 'true' : 'false'}
          data-correct={awayCorrect ? 'true' : 'false'}
          data-wrong={awayWrong ? 'true' : 'false'}
        >
          <span className="truncate" title={match.away_team ? undefined : (match.away_team_placeholder ?? undefined)}>{awayLabel}</span>
          {isCompleted && match.actual_away_score !== null && (
            <span className="font-mono text-text-muted shrink-0">{match.actual_away_score}</span>
          )}
        </div>
      </div>
    </foreignObject>
  );
}

// Connector path from two child matches into one parent match.
function ConnectorPath({
  childRoundIndex,
  childIndexA,
  childIndexB,
  parentIndex,
}: {
  childRoundIndex: number;
  childIndexA: number;
  childIndexB: number;
  parentIndex: number;
}) {
  const parentRoundIndex = childRoundIndex + 1;
  const childX = columnX(childRoundIndex) + BOX_W;
  const parentX = columnX(parentRoundIndex);
  const midX = (childX + parentX) / 2;
  const yA = matchCenterY(childRoundIndex, childIndexA);
  const yB = matchCenterY(childRoundIndex, childIndexB);
  const yParent = matchCenterY(parentRoundIndex, parentIndex);

  const d = [
    `M ${childX} ${yA}`,
    `H ${midX}`,
    `V ${yB}`,
    `M ${midX} ${yParent}`,
    `H ${parentX}`,
  ].join(' ');

  return <path d={d} fill="none" stroke="currentColor" strokeWidth={1.2} className="text-border" />;
}

// ---------------------------------------------------------------------------
// Bracket SVG
// ---------------------------------------------------------------------------

function BracketSvg({
  matchesByRound,
  thirdPlace,
  myPreds,
  myColor,
}: {
  matchesByRound: Record<Round, MatchResponse[]>;
  thirdPlace: MatchResponse | null;
  myPreds: Map<string, string | null>; // match_id → predicted_winner_id
  myColor: string;
}) {
  const totalRounds = ROUNDS.length;
  const svgWidth = PADDING * 2 + totalRounds * BOX_W + (totalRounds - 1) * COL_GAP;

  // Third-place block sits below the final, in the same X column as SF.
  const tpX = columnX(ROUNDS.indexOf('sf'));
  const tpY = PADDING + LABEL_H + BRACKET_H + TP_BLOCK_TOP_OFFSET + LABEL_H;
  const svgHeight =
    thirdPlace !== null ? tpY + BOX_H + PADDING : PADDING + LABEL_H + BRACKET_H + PADDING;

  return (
    <svg
      width={svgWidth}
      height={svgHeight}
      viewBox={`0 0 ${svgWidth} ${svgHeight}`}
      role="img"
      aria-label="Knockout bracket"
      className="block"
    >
      {/* Round headers */}
      {ROUNDS.map((round, i) => (
        <text
          key={round}
          x={columnX(i) + BOX_W / 2}
          y={PADDING + 14}
          textAnchor="middle"
          className="fill-text-muted font-sans"
          style={{ fontSize: 11, letterSpacing: 0.5 }}
        >
          {ROUND_LABELS[round].toUpperCase()}
        </text>
      ))}

      {/* Connectors between consecutive rounds */}
      {ROUNDS.slice(0, -1).map((round, ri) => {
        const children = matchesByRound[round];
        const parents = matchesByRound[ROUNDS[ri + 1]];
        if (children.length === 0 || parents.length === 0) return null;
        return parents.map((_p, pi) => {
          const ca = pi * 2;
          const cb = pi * 2 + 1;
          if (ca >= children.length || cb >= children.length) return null;
          return (
            <ConnectorPath
              key={`conn-${round}-${pi}`}
              childRoundIndex={ri}
              childIndexA={ca}
              childIndexB={cb}
              parentIndex={pi}
            />
          );
        });
      })}

      {/* Match boxes */}
      {ROUNDS.map((round, ri) =>
        matchesByRound[round].map((m, mi) => (
          <MatchBox
            key={m.id}
            x={columnX(ri)}
            y={matchTopY(ri, mi)}
            match={m}
            myWinnerId={myPreds.get(m.id) ?? null}
            myColor={myColor}
          />
        )),
      )}

      {/* Third-place playoff (separate block) */}
      {thirdPlace !== null && (
        <>
          <text
            x={tpX + BOX_W / 2}
            y={tpY - 10}
            textAnchor="middle"
            className="fill-text-muted font-sans"
            style={{ fontSize: 11, letterSpacing: 0.5 }}
          >
            THIRD PLACE
          </text>
          <MatchBox
            x={tpX}
            y={tpY}
            match={thirdPlace}
            myWinnerId={myPreds.get(thirdPlace.id) ?? null}
            myColor={myColor}
          />
        </>
      )}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function BracketPage() {
  const { player } = useAuth();
  const myColor = playerColor(player?.id);

  const { data: allMatches = [], isLoading: matchesLoading } = useQuery<MatchResponse[]>({
    queryKey: ['matches', 'all'],
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches'),
    staleTime: 30_000,
  });

  const { data: predictions = [], isLoading: predsLoading } = useQuery<KnockoutPredictionResponse[]>({
    queryKey: ['knockout-predictions', 'me'],
    queryFn: () => apiFetch<KnockoutPredictionResponse[]>('/api/v1/knockout-predictions/me'),
    staleTime: 30_000,
  });

  const isLoading = matchesLoading || predsLoading;

  const { matchesByRound, thirdPlace, hasAnyKnockoutMatches } = useMemo(() => {
    const byRound: Record<Round, MatchResponse[]> = {
      r32: [],
      r16: [],
      qf: [],
      sf: [],
      final: [],
    };
    let tp: MatchResponse | null = null;

    for (const m of allMatches) {
      if (m.stage === 'third_place') {
        tp = m;
        continue;
      }
      if ((ROUNDS as readonly string[]).includes(m.stage)) {
        byRound[m.stage as Round].push(m);
      }
    }
    for (const r of ROUNDS) {
      byRound[r].sort((a, b) => a.match_number - b.match_number);
    }
    const hasAny = ROUNDS.some((r) => byRound[r].length > 0) || tp !== null;
    return { matchesByRound: byRound, thirdPlace: tp, hasAnyKnockoutMatches: hasAny };
  }, [allMatches]);

  const myPreds = useMemo(() => {
    const m = new Map<string, string | null>();
    for (const p of predictions) m.set(p.match_id, p.predicted_winner_id);
    return m;
  }, [predictions]);

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Bracket" eyebrow="Knockouts" />
        <div className="space-y-4" aria-label="Loading bracket">
          <Skeleton className="h-96 w-full rounded-lg" />
        </div>
      </div>
    );
  }

  if (!hasAnyKnockoutMatches) {
    return (
      <div>
        <PageHeader title="Bracket" eyebrow="Knockouts" />
        <BracketTeaser
          title="The bracket arrives after group stage"
          ctaLabel="Make your group-stage picks →"
          ctaTo="/predictions"
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Bracket" eyebrow="Knockouts" />
      <div className="flex items-center gap-3 mb-5 font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded-sm"
            style={{ backgroundColor: `${myColor}40`, border: `1px solid ${myColor}` }}
            aria-hidden="true"
          />
          Your pick
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded-sm"
            style={{ backgroundColor: 'rgba(16,185,129,0.25)', border: '1px solid #10b981' }}
            aria-hidden="true"
          />
          Correct
        </span>
      </div>

      <div
        className="overflow-x-auto -mx-4 px-4 pb-2"
        data-testid="bracket-scroll-container"
      >
        <BracketSvg
          matchesByRound={matchesByRound}
          thirdPlace={thirdPlace}
          myPreds={myPreds}
          myColor={myColor}
        />
      </div>
    </div>
  );
}
