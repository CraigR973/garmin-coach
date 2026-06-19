/**
 * Shared league helpers — privacy labels, etc.
 * Single source of truth: update here, both pages stay in sync.
 */

/** The real enum values the API serialises on league.privacy. */
export type LeaguePrivacy = 'public_open' | 'public_request' | 'private';

/**
 * Human-readable label for a league privacy value.
 * Returns an empty string for any unrecognised value so callers can
 * detect a missing label rather than showing "undefined".
 */
export const PRIVACY_LABELS: Record<LeaguePrivacy, string> = {
  public_open: 'Public',
  public_request: 'Public · request to join',
  private: 'Private',
};

/** Convenience helper — returns '' for unknown values. */
export function privacyLabel(privacy: string): string {
  return PRIVACY_LABELS[privacy as LeaguePrivacy] ?? '';
}
