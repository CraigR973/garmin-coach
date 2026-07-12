export const PUSH_NAVIGATION_MESSAGE_TYPE = 'coach:navigate';

export interface PushNavigationMessage {
  type: typeof PUSH_NAVIGATION_MESSAGE_TYPE;
  url: string;
}

interface PushWindowClient {
  focus?: () => Promise<unknown> | unknown;
  postMessage?: (message: PushNavigationMessage) => void;
}

interface FocusOrOpenPushTargetArgs {
  windowClients: readonly PushWindowClient[];
  rawUrl: unknown;
  origin: string;
  openWindow: (url: string) => Promise<unknown> | unknown;
}

export function normalizePushNavigationUrl(rawUrl: unknown, origin: string): string {
  if (typeof rawUrl !== 'string' || rawUrl.trim() === '') return '/';

  try {
    const base = new URL(origin);
    const url = new URL(rawUrl, base);
    if (url.origin !== base.origin) return '/';
    return `${url.pathname}${url.search}${url.hash}` || '/';
  } catch {
    return '/';
  }
}

export function buildPushNavigationMessage(rawUrl: unknown, origin: string): PushNavigationMessage {
  return {
    type: PUSH_NAVIGATION_MESSAGE_TYPE,
    url: normalizePushNavigationUrl(rawUrl, origin),
  };
}

export function isPushNavigationMessage(value: unknown): value is PushNavigationMessage {
  if (typeof value !== 'object' || value === null) return false;
  const message = value as Partial<PushNavigationMessage>;
  return message.type === PUSH_NAVIGATION_MESSAGE_TYPE && typeof message.url === 'string';
}

export async function focusOrOpenPushTarget({
  windowClients,
  rawUrl,
  origin,
  openWindow,
}: FocusOrOpenPushTargetArgs): Promise<void> {
  const message = buildPushNavigationMessage(rawUrl, origin);

  for (const client of windowClients) {
    if (typeof client.focus === 'function' && typeof client.postMessage === 'function') {
      await client.focus();
      client.postMessage(message);
      return;
    }
  }

  await openWindow(message.url);
}
