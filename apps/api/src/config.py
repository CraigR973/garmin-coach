from enum import StrEnum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"change-me-access", "change-me-refresh"}


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
    resend_api_key: str = ""
    email_from: str = "Garmin Coach <noreply@example.com>"
    garmin_email: str = ""
    garmin_password: str = ""
    garmin_tokenstore: str = "~/.garminconnect"
    hive_email: str = ""
    hive_password: str = ""
    weather_latitude: float = 55.6045
    weather_longitude: float = -4.5249
    weather_timezone: str = "Europe/London"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_max_tokens: int = 1600

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
        if not self.vapid_private_key:
            errors.append("vapid_private_key is empty")
        if not self.supabase_service_key:
            errors.append("supabase_service_key is empty")
        if not self.database_url:
            errors.append("database_url is empty")
        if not self.frontend_origin or self.frontend_origin.startswith("http://localhost"):
            errors.append("frontend_origin must not be empty or localhost in production")
        if errors:
            raise ValueError("Refusing to start with weak/missing secrets: " + "; ".join(errors))
        return self


settings = Settings()  # type: ignore[call-arg]  # env vars supply required fields at runtime
