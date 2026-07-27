/**
 * Pull the activation code out of whatever the user pastes into the device
 * setup screen: a full `https://…/activate?code=XXX` (or `#code=XXX`) link, a
 * bare `?code=XXX` fragment, or the raw opaque code on its own. Returns null
 * when there's nothing usable so the caller can show a hint instead of posting
 * junk.
 *
 * This entry point exists because on iOS the installed home-screen app has its
 * own storage, isolated from the Safari tab the link opened in, so the only way
 * to authenticate the standalone app is to enter the code inside it
 * (DECISIONS #242).
 */
export function extractActivationCode(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  // Full URL: let the browser parse query + hash for us.
  try {
    const url = new URL(trimmed);
    const fromQuery = url.searchParams.get('code');
    if (fromQuery) return fromQuery;
    const fromHash = new URLSearchParams(url.hash.replace(/^#/, '')).get('code');
    if (fromHash) return fromHash;
  } catch {
    // Not a full URL — fall through to the fragment/bare-code cases.
  }

  // A pasted `code=XXX` / `?code=XXX` / `#code=XXX` fragment without an origin.
  const paramMatch = trimmed.match(/(?:^code=|[?&#]code=)([^&\s]+)/i);
  if (paramMatch) return decodeURIComponent(paramMatch[1]);

  // Otherwise treat the whole thing as a bare opaque code (no whitespace).
  if (/\s/.test(trimmed)) return null;
  return trimmed;
}
