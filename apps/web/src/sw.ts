/// <reference lib="WebWorker" />
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching';
import { clientsClaim } from 'workbox-core';
import { NavigationRoute, registerRoute } from 'workbox-routing';
import { NetworkFirst, StaleWhileRevalidate } from 'workbox-strategies';
import { ExpirationPlugin } from 'workbox-expiration';
import { CacheableResponsePlugin } from 'workbox-cacheable-response';

// vite-plugin-pwa replaces self.__WB_MANIFEST with the precache manifest at build time
declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null } | string>;
};

// Skip waiting unconditionally so the new SW activates immediately on install.
// Previously we used registerType:'prompt' and required the user to tap "Refresh"
// on the UpdateBanner — but the IosSafariOverlay (z-70) blocked the banner on iOS,
// creating a deadlock where the old overlay-showing SW could never be replaced.
// The UpdateBanner still shows after activation to prompt a page reload so users
// get the latest JS, but the SW itself no longer waits for their action.
self.skipWaiting();
clientsClaim();

cleanupOutdatedCaches();
precacheAndRoute(self.__WB_MANIFEST);

// SPA navigation fallback — serve cached index.html for all non-API navigations
registerRoute(
  new NavigationRoute(
    new NetworkFirst({
      cacheName: 'navigation',
      networkTimeoutSeconds: 3,
    }),
    { denylist: [/^\/api/] },
  ),
);

// ─── API caching (Phase 11.2 — offline support) ───────────────────────────────
// Group data (group-stage assignments) is shared and essentially static →
// stale-while-revalidate. Match data carries live status/score and must not
// serve a stale cycle while online → network-first with a 3s timeout (U59).
// Per-player data (predictions, leaderboard, stats) is dynamic → network-first with
// a 3s timeout so cached data is used when offline. All restrict cached responses
// to GET 200s; auth-rejected (401/403) and mutating verbs are never cached.

registerRoute(
  ({ url, request }) =>
    request.method === 'GET' && /^\/api\/v1\/groups(\/|$|\?)/.test(url.pathname),
  new StaleWhileRevalidate({
    cacheName: 'api-groups',
    plugins: [
      new ExpirationPlugin({ maxEntries: 80, maxAgeSeconds: 60 * 60 * 24 }),
      new CacheableResponsePlugin({ statuses: [200] }),
    ],
  }),
);

registerRoute(
  ({ url, request }) =>
    request.method === 'GET' && /^\/api\/v1\/matches(\/|$|\?)/.test(url.pathname),
  new NetworkFirst({
    cacheName: 'api-matches',
    networkTimeoutSeconds: 3,
    plugins: [
      new ExpirationPlugin({ maxEntries: 80, maxAgeSeconds: 60 * 60 * 24 }),
      new CacheableResponsePlugin({ statuses: [200] }),
    ],
  }),
);

registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    /^\/api\/v1\/(predictions|leaderboard|players|stats|specials|knockout-predictions)(\/|$|\?)/.test(
      url.pathname,
    ),
  new NetworkFirst({
    cacheName: 'api-user-data',
    networkTimeoutSeconds: 3,
    plugins: [
      new ExpirationPlugin({ maxEntries: 80, maxAgeSeconds: 60 * 60 }),
      new CacheableResponsePlugin({ statuses: [200] }),
    ],
  }),
);

// Fonts are self-hosted in /fonts/ and included in the precache manifest via
// vite.config.ts VitePWA.includeAssets — no Google Fonts runtime routes needed.

// ─── Push notifications ───────────────────────────────────────────────────────

interface PushPayload {
  title: string;
  body: string;
  data?: { url?: string; [key: string]: unknown };
  // When set, a newer notification with the same tag replaces an older one in
  // the tray rather than stacking (e.g. reminders for one match, the daily
  // digest, or a result superseded by the reader's leaderboard move).
  tag?: string;
}

self.addEventListener('push', (event) => {
  if (!event.data) return;

  let payload: PushPayload;
  try {
    payload = event.data.json() as PushPayload;
  } catch {
    return;
  }

  const { title, body, data, tag } = payload;
  const options: NotificationOptions = {
    body,
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data,
    requireInteraction: false,
  };
  if (tag) options.tag = tag;
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url: string = (event.notification.data as { url?: string } | undefined)?.url ?? '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if ('focus' in client) {
          void client.focus();
          if ('navigate' in client) void (client as WindowClient).navigate(url);
          return;
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
