/** Mark-facing errors never repeat an API response or a schema issue list. */
export function friendlyError(
  error: unknown,
  action: 'load' | 'save' = 'load',
  trustedPlanRefusal = false,
): string {
  // Plan-change 422 responses are authored as fixed, human-facing safety words.
  if (trustedPlanRefusal && action === 'save' && error instanceof Error &&
      'status' in error && (error.status === 409 || error.status === 422) &&
      'humanDetail' in error && error.humanDetail === true &&
      !error.message.startsWith('API error ')) return error.message;
  return action === 'save'
    ? "We couldn't confirm that change. Refresh before trying again."
    : "We couldn't load this right now. Your saved data is safe. Try again.";
}
