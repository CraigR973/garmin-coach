import * as Sentry from '@sentry/react';

const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;

if (dsn) {
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: 0.1,
    sendDefaultPii: false,
    beforeSend(event) {
      // Strip player display names so they never appear in Sentry reports.
      if (event.user) {
        delete event.user.username;
        const user = event.user as Record<string, unknown>;
        delete user['display_name'];
      }
      return event;
    },
  });
}

export { Sentry };
