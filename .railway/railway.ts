// Railway's configuration for garmin-coach, as code (Batch 287).
//
// Railway stops reading railway.toml on 1 Dec 2026, so the Dockerfile builder,
// the API's health check and its restart policy, which only that file used to
// supply, are stated here. Applied on 27 Sep 2026, when railway.toml was removed.
//
// Imported with `railway config pull`, so every variable is preserve(): the
// value stays in Railway and none enters the repo. Railway does not read this
// file during deploys; it takes effect when `railway config apply` runs.
import { defineRailway, github, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const garminCoach = github("CraigR973/garmin-coach", { checkSuites: false });

  // The API builds the repo-root Dockerfile and runs migrations before uvicorn.
  // Batch 371 removes both retired cron resources; the in-process jobs remain.
  const dockerfile = { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" } as const;

  // Retained encrypted nightly archives; weekly copies also go to the private offsite bucket.
  const apiVolume = volume("api-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "ams", sizeMB: 5000 });

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
    env: { ACTIVITY_TIMESERIES_RETENTION_ENABLED: preserve(), ANTHROPIC_API_KEY: preserve(), BACKUP_DIR: preserve(), BACKUP_AGE_RECIPIENT: preserve(), BACKUP_B2_BUCKET_ID: preserve(), BACKUP_B2_KEY_ID: preserve(), BACKUP_B2_APPLICATION_KEY: preserve(), DATABASE_URL: preserve(), DREO_PASSWORD: preserve(), DREO_USERNAME: preserve(), ENVIRONMENT: preserve(), FRONTEND_ORIGIN: preserve(), GARMIN_TOKENSTORE: preserve(), GARMIN_TOKENSTORE_B64: preserve(), HIVE_TOKENSTORE_B64: preserve(), INTERVALS_API_KEY: preserve(), INTERVALS_ATHLETE_ID: preserve(), INTERVALS_BASE_URL: preserve(), PORT: preserve(), SENTRY_DSN_BACKEND: preserve(), SUPABASE_SERVICE_KEY: preserve(), VAPID_CONTACT_EMAIL: preserve(), VAPID_PRIVATE_KEY: preserve(), VAPID_PUBLIC_KEY: preserve() },
  });

  return project("garmin-coach", {
    resources: [api, apiVolume],
  });
});
