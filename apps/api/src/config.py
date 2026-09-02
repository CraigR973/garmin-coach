from enum import StrEnum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


# Batch 233.3. The two values that reach the Anthropic payload verbatim, kept
# here so the settings validator and the boundary's own type share one list.
# ``adaptive`` is the only on-mode on Sonnet 5 (``budget_tokens`` is rejected
# with a 400 on this model generation); ``disabled`` is the escape hatch back to
# Sonnet 4.6's behaviour.
ANTHROPIC_THINKING_MODES = frozenset({"adaptive", "disabled"})
ANTHROPIC_EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/garmin_coach"
    # Batch 232.3: production runs against Supabase's **session-mode** pooler
    # (``aws-1-eu-north-1.pooler.supabase.com:5432``), which grants this tenant a
    # hard ceiling of client connections. Supavisor refuses the one past it with
    # ``(EMAXCONNSESSION) max clients reached in session mode - max clients are
    # limited to pool_size: 15`` — logged eight times during the 2026-08-30
    # morning outage, while ten backends sat queued on a single advisory lock.
    # The API is not the only claim on that budget: the ``weekly-review`` cron
    # container runs the same code with its own engine, every deploy runs
    # ``alembic upgrade head`` at boot, the nightly ``pg_dump`` opens its own
    # connection, and ``railway run`` / ``railway ssh`` maintenance sessions add
    # more. So the app's own ceiling is the tenant limit minus a reserve for all
    # of those, and ``db_pool_size + db_max_overflow`` must fit inside it — an
    # invariant the validator below enforces rather than leaving to arithmetic in
    # a comment. Measured steady state on 2026-08-30 is **2** backends, so ten is
    # already about five times what the app uses.
    #
    # What the reserve is sized against, stated plainly because the arithmetic is
    # not "every client's maximum": the API container is the only one that fans
    # out concurrently, so it gets the pool. The cron container, Alembic and the
    # backup all run sequential single-connection work, and the reserve covers
    # their *observed* draw rather than the pool ceiling each would inherit from
    # sharing this engine. If a second concurrent fan-out service is ever added,
    # this reserve stops being enough and both numbers have to be revisited.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pooler_client_limit: int = 15
    db_pooler_reserved_connections: int = 5

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
    anthropic_model: str = "claude-sonnet-5"
    # Batch 233. Sonnet 5 moves both sides of this number and neither move is
    # optional, which is why the swap is not a one-line model change.
    #
    # 1. **The tokenizer.** Sonnet 5 uses the tokenizer introduced with Opus 4.7;
    #    Sonnet 4.6 and earlier use the previous one. Anthropic documents "~30%
    #    more tokens for the same text"; measured on this app's own brief prose
    #    with the token-count endpoint it is **1.305–1.343×** (three real v40
    #    days). So identical output re-prices in tokens: the 2026-08-30 brief's
    #    3,175 output tokens become **4,248** — past the old 4096 ceiling on
    #    prose alone, before a single thinking token.
    # 2. **Thinking is on by default, and it is what actually fills this budget.**
    #    Sonnet 4.6 with no ``thinking`` field ran thinking-off; on Sonnet 5 the
    #    same omission runs *adaptive at the default ``high`` effort*. Measured
    #    against the real 2026-08-31 packet, sending **no** thinking field still
    #    produced **9,236 output tokens** — so a bare model-string swap would not
    #    have degraded the brief, it would have failed it by 2.3× on the first
    #    morning. ``max_tokens`` caps thinking and text **together**.
    #
    # **The prose is not the problem, and the first version of this batch had that
    # backwards.** Sonnet 5 writes a *shorter* brief than 4.6 — 3.6–5.6k chars
    # against 8,482 — so text lands at ~1.5k tokens, *below* what 4.6 used. The
    # tokenizer inflates per character while the model writes fewer characters.
    # This number is therefore a **thinking budget**, sized from measured thinking
    # demand at ``high`` effort rather than from prose. Measured against the real
    # 2026-08-31 packet, with the provider's own ``output_tokens_details``:
    #
    #     effort=high    16,157 output tokens   171.6s   14,610 thinking / ~1,547 prose
    #     effort=medium   5,280                  61.1s   ~4.3k thinking
    #     effort=low      1,317                  18.9s   no thinking block at all
    #
    # ``anthropic_text.py`` raises on ``stop_reason == "max_tokens"``, so getting
    # this wrong is a hard failure showing Mark the Batch 141 failure card — not
    # degraded prose.
    #
    # **This stays sized for ``high`` even though the app ships ``medium``**, and
    # that is deliberate rather than left over. A ceiling costs nothing when it is
    # not reached — Anthropic bills output tokens actually generated, never the
    # cap — so the only thing a tighter number would buy is a lower runaway bound,
    # against the cost of making ``anthropic_effort`` unsafe to change on its own.
    # Sized for ``medium`` this would be ~12k, and flipping effort back to ``high``
    # would then fail on the first brief. Two numbers that must move together are
    # exactly what 233.6 and Batch 232 exist to stop, so the ceiling covers the
    # most expensive effort the app can be set to and ``anthropic_effort`` is a
    # genuinely independent dial. 24576 is ~1.5× the worst observed ``high`` run
    # and ~4.7× the ``medium`` runs shipped today; it is also close to the largest
    # value the derivation below can legally take — see the 600s wall.
    anthropic_max_tokens: int = 24576
    # Batch 233.2: the two paths that used to hardcode their own ceiling below the
    # boundary's. A 1024-token budget shared between adaptive thinking and a chat
    # reply truncates routinely, and no ``ANTHROPIC_MAX_TOKENS`` change could reach
    # it. Both are settings now so a retune moves every ceiling at once.
    #
    # **Unmeasured, and the one place ``anthropic_effort`` is not a free dial.**
    # Thinking demand was only ever measured on the morning path; a chat turn has a
    # much smaller prompt and should think proportionately less, but nobody has
    # checked. At ``medium`` — where the *morning* prompt thinks ~4.3k — that is a
    # comfortable fit. At ``high``, where the morning prompt thinks 14,610, 4096
    # could plausibly truncate a chat turn into a ``max_tokens`` failure. If effort
    # is ever raised, measure a real chat turn before assuming this ceiling holds.
    anthropic_chat_max_tokens: int = 4096
    anthropic_learning_max_tokens: int = 4096
    # Batch 233.3. ``adaptive`` lets the model decide how much to think, steered by
    # ``anthropic_effort``; ``disabled`` restores Sonnet 4.6's behaviour byte-for-byte
    # if a live morning ever regresses. This is a safe place to experiment because
    # the verdict is deterministic — ``morning_analysis.py`` reads it from
    # ``context_packet["verdict"]["status"]``, so the model narrates and never
    # decides, and a regression surfaces as worse prose rather than a wrong Red.
    #
    # **``medium``, and it is a deliberate departure from Sonnet 5's own default of
    # ``high``** — so it is set explicitly here and pinned by a test rather than
    # inherited. Effort is the steepest cost lever in this file: measured on one
    # real packet, ``high`` generates **3.1× the output tokens of ``medium``**
    # (16,157 vs 5,280) and takes 2.8× as long (171.6s vs 61.1s), which puts the
    # morning brief at ~$0.21/run against ~$0.11. That difference is
    # **+126% vs today's Sonnet 4.6 for ``high``, but only +11% for ``medium``** —
    # Sonnet 5's price cut very nearly absorbs the tokenizer at this setting, so
    # ``medium`` buys adaptive thinking for roughly what the app already pays.
    # ``high`` was not rejected on quality grounds; the prose comparison that would
    # justify it has not been run (Batch 233.8), so paying 2.3× for an unexamined
    # difference is the thing being declined. Raise it once that diff says it earns
    # its keep — the ceiling above already has room, deliberately.
    anthropic_thinking_mode: str = "adaptive"
    anthropic_effort: str = "medium"
    # How long to wait for a *complete* non-streamed Messages response. The morning
    # brief is the longest generation we make: on 2026-08-30 it measured 75.1s
    # (27.7k in / 2.8k out at ~38 output tok/s) against the previous hardcoded 60s,
    # so every attempt that day died on ``httpx.ReadTimeout`` after Anthropic had
    # already done — and billed — the work. The packet only grows, so the ceiling is
    # sized off the worst case instead of today's measurement. Env-tunable so a slow
    # spell can be ridden out without a deploy.
    #
    # **Batch 233.6 re-derives it, and re-bases the rate it is derived from.** The
    # old derivation was ``anthropic_max_tokens`` at ~15 tok/s — a ~2.5× pessimism
    # over the ~38 output tok/s Sonnet 4.6 measured in Batch 234. Sonnet 5 generates
    # far faster: the effort sweep above measured **87–99 output tok/s** across four
    # real runs, including 15,961 tokens in 161.9s at ``high``. Holding 15 tok/s
    # against a ceiling that now has to cover adaptive thinking would demand
    # 1,638s and is impossible under the wall below, so the constant moves to
    # **~45 tok/s — still a ~2× pessimism against measurement**, and the resulting
    # budget is 3.4× the slowest generation actually observed:
    #
    #     24576 / 45 tok/s ≈ 546s, rounded to 550.
    #
    # **There is a hard wall at 600s that is not a matter of taste.** Batch 232 made
    # the generation lease ``read + generation_lease_overhead_seconds`` and made
    # ``validate_timeout_ordering()`` fail startup unless the lease expires before
    # Batch 144's 720s stale-after guard. So ``read + 120 < 720`` — the API does not
    # boot at ``read >= 600``, which caps ``anthropic_max_tokens`` near 27,000 under
    # this derivation. That wall, not the throughput measurement, is what bounds the
    # ceiling; raising one without the other is what the startup check exists to stop.
    anthropic_read_timeout_seconds: float = 550.0
    # Batch 232.2: the generation lease is *derived* from the read budget above
    # rather than fixed, because the two must move together. The lease is the only
    # record that says "a worker is still legitimately generating this artifact";
    # if it expires while a compliant worker is still inside its paid call, the
    # request row lies, and the next attempt is entitled to reclaim work that is
    # still running. Batch 234 raised the read budget 60s → 300s and left the lease
    # at a hardcoded 180s, so the lie became reachable. This is the margin added on
    # top for packet assembly and the completed-state write: measured on 2026-08-30,
    # the lock was held 70–80s for a 75.1s Anthropic call, so non-generation work
    # inside a claim is seconds, and 120s is generous. See
    # ``services.generation_requests.timeout_ordering``.
    generation_lease_overhead_seconds: float = 120.0
    # Batch 141: operator profile that receives ops alerts (e.g. a billing/credit
    # generation failure). A profile UUID string; empty disables the admin *push*
    # (the structured error-log alert still fires regardless). Deliberately NOT the
    # app ``admin`` role — the primary user holds that role, and an ops alert must
    # never land on his phone. Set this to Craig's own seeded profile id in prod.
    admin_alert_user_id: str = ""
    # Batch 144: how long a brief-generation status row may sit at ``generating``
    # before the daily-loop envelope treats it as a ``failed``/``stale`` generation.
    # A task orphaned by a process restart or a hung Anthropic call never flips the
    # row to ready/failed, so without this it reads ``generating`` forever (the
    # 2026-07-21 90-minute-spinner class). Read-time derivation only — no writer, no
    # migration, no scheduler (Decision #223). Also mirrored by the web client's
    # max-wait cap. Normal generation completes in well under 2 minutes.
    brief_generation_stale_after_minutes: int = 12
    # Batch 159: the same orphan guard for activity-scoped post-session reads.
    post_activity_generation_stale_after_minutes: int = 12
    # Hosted read-aloud voice (Batch 116, opt-in; self-hosted via Piper as of
    # DECISIONS #190). A missing model file means the hosted path is
    # unavailable regardless of a user's consent flag — the frontend falls
    # back to on-device SpeechSynthesis (Batch 111, DECISIONS #184).
    piper_voice_model_path: str = "/app/voices/en_GB-northern_english_male-medium.onnx"
    piper_voice_config_path: str = "/app/voices/en_GB-northern_english_male-medium.onnx.json"
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
    # Optional disposable database used only by the backup restore drill. It must
    # not point at production: the drill runs pg_restore --clean into it.
    backup_restore_database_url: str = ""

    # Batch 247.2. `activity_timeseries` retention deletes per-second samples for
    # activities older than 90 days — measured 466,449 rows on 2026-09-02 — from a
    # table **excluded from every backup by design**, so there is no undo. The job
    # ships registered and **dry-run**: it measures and logs what it would remove
    # on every pass, and deletes nothing until this is deliberately set true. The
    # first execution is a decision with a row count attached, not something a
    # deploy performs on its own.
    activity_timeseries_retention_enabled: bool = False

    # Background scheduler (APScheduler) — disable in tests / one-off scripts.
    scheduler_enabled: bool = True

    @model_validator(mode="after")
    def _reject_weak_secrets_in_prod(self) -> "Settings":
        if self.environment == Environment.development:
            return self
        errors: list[str] = []
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

    @model_validator(mode="after")
    def _reject_pool_over_pooler_ceiling(self) -> "Settings":
        """Batch 232.3: the app may never provision above what the pooler grants.

        Unconditional rather than production-only: this is an arithmetic
        relationship between four values in this file, so a local `.env` that
        breaks it is a bug wherever it runs. The failure it prevents is silent
        until load — every connection under the ceiling works, and the one past
        it is refused by Supavisor with a FATAL the app surfaces as a generic
        error.
        """
        budget = self.db_pooler_client_limit - self.db_pooler_reserved_connections
        provisioned = self.db_pool_size + self.db_max_overflow
        if provisioned > budget:
            raise ValueError(
                f"Database pool provisions {provisioned} connections "
                f"(db_pool_size={self.db_pool_size} + db_max_overflow={self.db_max_overflow}) "
                f"but the pooler budget is {budget} "
                f"(db_pooler_client_limit={self.db_pooler_client_limit} − "
                f"db_pooler_reserved_connections={self.db_pooler_reserved_connections})"
            )
        return self

    @model_validator(mode="after")
    def _reject_unknown_thinking_or_effort(self) -> "Settings":
        """Batch 233.3: catch a bad thinking/effort value here, not on Mark's morning.

        Both reach the Anthropic payload verbatim. An unrecognised value is a 400
        from the provider on the *first* generation after a deploy, which reaches
        Mark as the Batch 141 failure card — the exact failure mode this batch
        exists to remove. Failing at construction turns a silent typo in a Railway
        variable into a boot error instead.
        """
        errors: list[str] = []
        if self.anthropic_thinking_mode not in ANTHROPIC_THINKING_MODES:
            errors.append(
                f"anthropic_thinking_mode={self.anthropic_thinking_mode!r} "
                f"is not one of {sorted(ANTHROPIC_THINKING_MODES)}"
            )
        if self.anthropic_effort not in ANTHROPIC_EFFORT_LEVELS:
            errors.append(
                f"anthropic_effort={self.anthropic_effort!r} "
                f"is not one of {sorted(ANTHROPIC_EFFORT_LEVELS)}"
            )
        if errors:
            raise ValueError("Invalid Anthropic generation settings: " + "; ".join(errors))
        return self


settings = Settings()


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
