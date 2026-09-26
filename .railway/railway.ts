// Railway's configuration for garmin-coach, as code (Batch 287).
//
// Railway stops reading railway.toml on 1 Dec 2026. All three services carry
// RAILPACK in their own settings; the repo-root Dockerfile is used today only
// because railway.toml overrides it, and the API's health check and restart
// policy come only from that file. This states them here instead.
//
// Imported with `railway config pull`, so every variable is preserve(): the
// value stays in Railway and none enters the repo. Railway does not read this
// file during deploys; it takes effect when `railway config apply` runs.
import { defineRailway, github, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const garminCoach = github("CraigR973/garmin-coach", { checkSuites: false });

  // Every service builds the repo-root Dockerfile: the API's CMD runs
  // `alembic upgrade head` before uvicorn, and the cron services run
  // `python -m src.run_scheduled <job>` on the same image.
  const dockerfile = { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" } as const;

  // The only backups this app has (the nightly pg_dump lands here).
  const apiVolume = volume("api-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "ams", sizeMB: 5000 });

  const trendNarratives = service("trend-narratives", {
    source: garminCoach,
    build: dockerfile,
    start: "if [ \"$(TZ=Europe/London date +%H%M)\" = 1230 ]; then python -m src.run_scheduled trend-narratives; else echo trend-narratives-skipped-outside-1230-Europe-London; fi",
    replicas: { "ams": 1 },
    // A run-to-completion cron: never restarted, no health check.
    deploy: { cronSchedule: "30 11,12 * * *", restartPolicyType: "NEVER" },
    env: { ANTHROPIC_API_KEY: preserve(), DATABASE_URL: preserve(), ENVIRONMENT: preserve(), SCHEDULED_JOB: preserve(), SCHEDULED_LONDON_HHMM: preserve(), SENTRY_DSN_BACKEND: preserve(), VAPID_CONTACT_EMAIL: preserve(), VAPID_PRIVATE_KEY: preserve(), VAPID_PUBLIC_KEY: preserve() },
  });

  const weeklyReview = service("weekly-review", {
    source: garminCoach,
    build: dockerfile,
    start: "if [ \"$(TZ=Europe/London date +%H)\" = 18 ]; then python -m src.run_scheduled weekly-review; else echo weekly-review-skipped-outside-18-Europe-London; fi",
    replicas: { "ams": 1 },
    // A run-to-completion cron: never restarted, no health check.
    deploy: { cronSchedule: "0 17,18 * * 0", restartPolicyType: "NEVER" },
    env: { ANTHROPIC_API_KEY: preserve(), DATABASE_URL: preserve(), ENVIRONMENT: preserve(), FRONTEND_ORIGIN: preserve(), SENTRY_DSN_BACKEND: preserve(), SUPABASE_SERVICE_KEY: preserve(), VAPID_CONTACT_EMAIL: preserve(), VAPID_PRIVATE_KEY: preserve(), VAPID_PUBLIC_KEY: preserve() },
  });

  const api = service("api", {
    source: garminCoach,
    build: dockerfile,
    replicas: { "ams": 1 },
    deploy: {
      // A new deploy takes traffic only once it answers here, so a failed
      // migration never cuts over.
      healthcheckPath: "/api/v1/health",
      healthcheckTimeout: 300,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 3,
      // Stated, not inherited: the API runs the in-process scheduler, so it
      // must never sleep. The pull reported true; Batch 237 recorded false.
      sleepApplication: false,
    },
    networking: { serviceDomains: { "api-production-e2bc7.up.railway.app": {} } },
    volumeMounts: { "/data/backups": apiVolume },
    env: { ACTIVITY_TIMESERIES_RETENTION_ENABLED: preserve(), ANTHROPIC_API_KEY: preserve(), BACKUP_DIR: preserve(), DATABASE_URL: preserve(), DREO_PASSWORD: preserve(), DREO_USERNAME: preserve(), ENVIRONMENT: preserve(), FRONTEND_ORIGIN: preserve(), GARMIN_TOKENSTORE: preserve(), GARMIN_TOKENSTORE_B64: preserve(), HIVE_EMAIL: preserve(), HIVE_PASSWORD: preserve(), HIVE_TOKENSTORE_B64: preserve(), INTERVALS_API_KEY: preserve(), INTERVALS_ATHLETE_ID: preserve(), INTERVALS_BASE_URL: preserve(), PORT: preserve(), SENTRY_DSN_BACKEND: preserve(), SUPABASE_SERVICE_KEY: preserve(), VAPID_CONTACT_EMAIL: preserve(), VAPID_PRIVATE_KEY: preserve(), VAPID_PUBLIC_KEY: preserve() },
  });

  return project("garmin-coach", {
    resources: [trendNarratives, weeklyReview, api, apiVolume],
  });
});
