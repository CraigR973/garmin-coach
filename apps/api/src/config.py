from enum import StrEnum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"change-me-access", "change-me-refresh"}
_MIN_SECRET_LEN = 32


class Environment(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/garmin_coach"

    # Auth
    jwt_access_secret: str
    jwt_refresh_secret: str

    # External APIs
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    garmin_email: str = ""
    garmin_password: str = ""
    garmin_tokenstore: str = "~/.garminconnect"
    garmin_tokenstore_b64: str = ""
    hive_email: str = ""
    hive_password: str = ""
    # Hive uses AWS Cognito SMS_MFA, so a full password login cannot run headlessly.
    # Seed this base64 {username, refresh_token} blob once via a SMS-2FA login
    # (scripts/bootstrap_hive_tokenstore.py) so the poller can resume unattended.
    hive_tokenstore_b64: str = ""
    # Dreo bedroom-fan cloud control (Batch 27, DECISIONS #95). login() returns an
    # access token that can be cached as DREO_TOKEN="token:REGION" to skip the
    # password login; password stays the fallback. Region auto-detects from the
    # auth response (DREO_REGION optional); DREO_DEVICE_SN pins the target fan.
    dreo_username: str = ""
    dreo_password: str = ""
    dreo_token: str = ""
    dreo_region: str = ""
    dreo_device_sn: str = ""
    weather_latitude: float = 55.6045
    weather_longitude: float = -4.5249
    weather_timezone: str = "Europe/London"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_max_tokens: int = 4096
    intervals_api_key: str = ""
    intervals_athlete_id: str = "i618709"
    intervals_base_url: str = "https://intervals.icu/api/v1"

    # Web Push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_contact_email: str = "admin@example.com"

    # App
    frontend_origin: str = "http://localhost:5173"
    sentry_dsn_backend: str = ""
    log_level: str = "INFO"
    # Unknown strings are rejected by the enum (fail-closed).
    environment: Environment = Environment.development
    # Railway injects this into the deploy env so /health can expose the running SHA.
    railway_git_commit_sha: str | None = None

    # Backup
    backup_dir: str = "/tmp/garmin_coach_backups"

    # Background scheduler (APScheduler) — disable in tests / one-off scripts.
    scheduler_enabled: bool = True

    @model_validator(mode="after")
    def _reject_weak_secrets_in_prod(self) -> "Settings":
        if self.environment == Environment.development:
            return self
        errors: list[str] = []
        if self.jwt_access_secret in _PLACEHOLDER_SECRETS:
            errors.append("jwt_access_secret is a placeholder value")
        if self.jwt_refresh_secret in _PLACEHOLDER_SECRETS:
            errors.append("jwt_refresh_secret is a placeholder value")
        if len(self.jwt_access_secret) < _MIN_SECRET_LEN:
            errors.append(f"jwt_access_secret must be at least {_MIN_SECRET_LEN} characters")
        if len(self.jwt_refresh_secret) < _MIN_SECRET_LEN:
            errors.append(f"jwt_refresh_secret must be at least {_MIN_SECRET_LEN} characters")
        if self.jwt_access_secret == self.jwt_refresh_secret:
            errors.append("jwt_access_secret and jwt_refresh_secret must be different")
        if not self.vapid_private_key:
            errors.append("vapid_private_key is empty")
        if not self.supabase_service_key:
            errors.append("supabase_service_key is empty")
        if not self.anthropic_api_key:
            errors.append("anthropic_api_key is empty")
        if not self.database_url:
            errors.append("database_url is empty")
        if not self.frontend_origin or self.frontend_origin.startswith("http://localhost"):
            errors.append("frontend_origin must not be empty or localhost in production")
        if errors:
            raise ValueError("Refusing to start with weak/missing secrets: " + "; ".join(errors))
        return self


settings = Settings()  # type: ignore[call-arg]  # env vars supply required fields at runtime


def docs_urls(environment: Environment) -> dict[str, str | None]:
    """OpenAPI/Swagger/ReDoc URLs for the app — disabled (None) in production.

    A private, invite-only app shouldn't expose its full API schema to anonymous
    callers, so the three doc routes are turned off in production; dev/staging
    keep them for convenience. (Review finding P3-7.)
    """
    if environment == Environment.production:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {
        "docs_url": "/api/docs",
        "redoc_url": "/api/redoc",
        "openapi_url": "/api/openapi.json",
    }
