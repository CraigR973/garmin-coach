import type { Stage } from './types';

export interface MatchResult {
  homeScore: number;
  awayScore: number;
}

export interface ScoreBreakdown {
  totalGoals: number;
  correctResult: number;
  exactScore: number;
  total: number;
  noPrediction: boolean;
}

export type KnockoutAdvancementStatus = 'not_applicable' | 'undecided' | 'determined';

export interface KnockoutAdvancementProjection {
  status: KnockoutAdvancementStatus;
  advancerId: string | null;
  points: number;
  availablePoints: number;
  noPrediction: boolean;
}

export interface LiveProvisionalBreakdown {
  match: ScoreBreakdown;
  advancement: KnockoutAdvancementProjection;
  total: number;
}

const KNOCKOUT_WINNER_POINTS: Partial<Record<Stage, number>> = {
  r32: 5,
  r16: 10,
  qf: 15,
  sf: 20,
  third_place: 10,
  final: 25,
};

export function knockoutWinnerPointsForStage(stage: Stage): number {
  return KNOCKOUT_WINNER_POINTS[stage] ?? 0;
}

export function isKnockoutStage(stage: Stage): boolean {
  return knockoutWinnerPointsForStage(stage) > 0;
}

export function scoreMatchPrediction(
  prediction: MatchResult | null,
  actual: MatchResult,
  // stage is kept for API compatibility; scoring is now identical across all stages
  _stage: Stage,
): ScoreBreakdown {
  if (!prediction) {
    return { totalGoals: 0, correctResult: 0, exactScore: 0, total: 0, noPrediction: true };
  }

  const actualTotal = actual.homeScore + actual.awayScore;
  const predTotal = prediction.homeScore + prediction.awayScore;

  const totalGoals = predTotal === actualTotal ? 2 : 0;

  const actualResult = Math.sign(actual.homeScore - actual.awayScore);
  const predResult = Math.sign(prediction.homeScore - prediction.awayScore);
  const correctResult = predResult === actualResult ? 3 : 0;

  const exactScore =
    prediction.homeScore === actual.homeScore && prediction.awayScore === actual.awayScore ? 5 : 0;

  return {
    totalGoals,
    correctResult,
    exactScore,
    total: totalGoals + correctResult + exactScore,
    noPrediction: false,
  };
}

export function projectKnockoutAdvancement({
  stage,
  homeTeamId,
  awayTeamId,
  actual,
  predictedWinnerId,
}: {
  stage: Stage;
  homeTeamId: string | null | undefined;
  awayTeamId: string | null | undefined;
  actual: MatchResult;
  predictedWinnerId: string | null | undefined;
}): KnockoutAdvancementProjection {
  const availablePoints = knockoutWinnerPointsForStage(stage);
  const noPrediction = predictedWinnerId == null;

  if (availablePoints === 0) {
    return {
      status: 'not_applicable',
      advancerId: null,
      points: 0,
      availablePoints: 0,
      noPrediction,
    };
  }

  if (actual.homeScore === actual.awayScore) {
    return {
      status: 'undecided',
      advancerId: null,
      points: 0,
      availablePoints,
      noPrediction,
    };
  }

  const advancerId = actual.homeScore > actual.awayScore ? homeTeamId : awayTeamId;
  if (advancerId == null) {
    return {
      status: 'undecided',
      advancerId: null,
      points: 0,
      availablePoints,
      noPrediction,
    };
  }

  return {
    status: 'determined',
    advancerId,
    points: predictedWinnerId === advancerId ? availablePoints : 0,
    availablePoints,
    noPrediction,
  };
}

export function scoreLiveProvisionalPrediction({
  prediction,
  actual,
  stage,
  homeTeamId,
  awayTeamId,
  predictedWinnerId,
}: {
  prediction: MatchResult | null;
  actual: MatchResult;
  stage: Stage;
  homeTeamId: string | null | undefined;
  awayTeamId: string | null | undefined;
  predictedWinnerId: string | null | undefined;
}): LiveProvisionalBreakdown {
  const match = scoreMatchPrediction(prediction, actual, stage);
  const advancement = projectKnockoutAdvancement({
    stage,
    homeTeamId,
    awayTeamId,
    actual,
    predictedWinnerId,
  });

  return {
    match,
    advancement,
    total: match.total + (advancement.status === 'determined' ? advancement.points : 0),
  };
}
