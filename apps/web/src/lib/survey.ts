import { apiFetch } from './api';

/** Survey key for the "one week in" pulse. Mirrors WEEK1_PULSE_KEY on the API. */
export const WEEK1_SURVEY_KEY = 'week1_pulse';

export interface SurveyStatus {
  completed: boolean;
}

export interface Week1Answers {
  q2_overall: number; // 1–5
  q3_frequency: 'several_daily' | 'daily' | 'few_days' | 'barely';
  q4_notifications: 'too_many' | 'about_right' | 'too_few' | 'turned_off' | 'none_received';
  q5_missed_deadline: 'no' | 'forgot' | 'time_confused' | 'other';
  q6_biggest_annoyance:
    | 'leaderboard'
    | 'league_switching'
    | 'live_scores'
    | 'predictions'
    | 'notifications'
    | 'nothing'
    | 'other';
  q6_other?: string | null;
  q7_open?: string | null;
  q9_scotland?: string | null;
}

/** Whether the current player has already completed the given survey. */
export function fetchSurveyStatus(surveyKey: string): Promise<SurveyStatus> {
  return apiFetch<SurveyStatus>(`/api/v1/surveys/${surveyKey}/status`);
}

/**
 * Submit a survey response. When `contactOk` is true the player's identity is
 * attached to this one response (hybrid model); otherwise it is anonymous.
 */
export function submitSurvey(
  surveyKey: string,
  answers: Week1Answers,
  contactOk: boolean,
): Promise<SurveyStatus> {
  return apiFetch<SurveyStatus>(`/api/v1/surveys/${surveyKey}/response`, {
    method: 'POST',
    body: JSON.stringify({ answers, contact_ok: contactOk }),
  });
}
