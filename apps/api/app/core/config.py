"""Phase 7 Module 3 — the single place environment config enters the app.

No other module reads `os.environ`. Fields declared without a default are
required, so a misconfigured deployment fails loudly at import time instead
of at the first request that happens to need the value.
"""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# asyncpg is the production driver; aiosqlite is what the test suite uses.
# Anything else (psycopg2, plain postgresql://) is sync and would block the
# event loop on every query. Module-level, not a class attribute: pydantic
# treats leading-underscore class attributes as private attrs.
ASYNC_DB_DRIVERS = ("postgresql+asyncpg://", "sqlite+aiosqlite://")


class Settings(BaseSettings):
    # `extra="ignore"` matters: docker-compose reads the repo-root .env, which
    # also carries POSTGRES_* vars meant for the db container. Without this,
    # those unknown keys would raise a ValidationError and block startup.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application identity ------------------------------------------------

    APP_NAME: str = "AI Marketing & Sales Teammate"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    """Mount point for every router. Bumping to /api/v2 must be a new prefix
    alongside this one, never an edit — existing clients keep working."""

    # --- Required: no default, absence is a startup failure ------------------

    DATABASE_URL: str
    SECRET_KEY: str

    # --- Connection pool -----------------------------------------------------
    # Sized per process, and the API and each Celery worker are separate
    # processes — total Postgres connections is roughly
    # (POOL_SIZE + MAX_OVERFLOW) x process count. Raise Postgres'
    # max_connections before raising these.

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800
    """Retire a pooled connection after this long. Keep it under any upstream
    idle timeout (pgbouncer, cloud Postgres) so we close first."""
    DB_ECHO: bool = False
    """Logs every emitted statement. Debugging only — query text includes
    lead PII and would land in the aggregator."""

    # --- Auth ----------------------------------------------------------------

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    """Must stay in step with the refresh cookie's max_age in routers/auth.py,
    otherwise the session expires while the browser still holds the cookie."""

    # --- Background jobs -----------------------------------------------------

    REDIS_URL: str = "redis://localhost:6379/0"
    """Celery broker/result backend for background AI jobs (Module 9)."""

    # --- Integrations --------------------------------------------------------

    ENCRYPTION_KEY: str = ""
    """Fernet key for encrypting integration OAuth tokens at rest. Generate
    with `Fernet.generate_key()` — required before any Integration with
    credentials is created."""

    # --- Optional third parties: empty means the feature stays inert ---------

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-5"

    LLM_PROVIDER: Literal["auto", "anthropic", "openai"] = "auto"
    """Which provider the Outreach Agent uses. `auto` takes whichever has a key
    (Anthropic first), which is right for the common case of a workspace that
    only ever set one. Naming a provider explicitly makes an unconfigured one
    fail loudly rather than silently falling through to the other vendor and
    billing the wrong account."""

    # --- Live web sourcing for the Research Agent (TinyFish) -----------------

    TINYFISH_API_KEY: str = ""
    """Empty means the Research Agent stays offline and reasons over lead data
    and CRM notes only — a thinner report, not a broken one, and its coverage
    confidence drops accordingly rather than silently claiming the same
    certainty."""
    TINYFISH_SEARCH_URL: str = "https://api.search.tinyfish.ai"
    TINYFISH_FETCH_URL: str = "https://api.fetch.tinyfish.ai"
    TINYFISH_TIMEOUT_SECONDS: int = 20
    """Bounded so a slow third party cannot pin a Celery worker on a job a rep
    is waiting on."""

    # --- Google Calendar API Key ----------------------------------------------
    GOOGLE_CALENDAR_API_KEY: str = ""

    # --- HubSpot CRM API Key --------------------------------------------------
    HUBSPOT_API_KEY: str = ""

    # --- SerpApi Google Search API Key ---------------------------------------
    SERPAPI_KEY: str = ""


    # --- Email delivery (Mailjet over SMTP) ----------------------------------
    #
    # Mailjet's SMTP relay takes the API key as the username and the secret key
    # as the password, so no provider-specific client is needed — `smtplib` and
    # the existing settings do it. A REST adapter would only be worth adding for
    # delivery/bounce webhooks.

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    """Mailjet API key."""
    SMTP_PASSWORD: str = ""
    """Mailjet secret key."""

    EMAIL_SEND_ENABLED: bool = False
    """**Default false, deliberately.** Credentials being present is not consent
    to email real prospects: a test run against a seeded contact would reach a
    real inbox, and there is no recall. With this off, `send_draft` still runs
    the whole Gate 2 state machine and writes `SentEmail` + the timeline entry —
    it just records `delivery_status="dry_run"` instead of handing the message
    to Mailjet. Flip it when you actually want mail to leave."""

    EMAIL_FROM_ADDRESS: str = ""
    """Must be a sender Mailjet has validated. An unvalidated From is rejected
    at send time, so this is checked before a draft is marked sent rather than
    discovered after."""
    EMAIL_FROM_NAME: str = ""
    EMAIL_TIMEOUT_SECONDS: int = 15
    """Bounded so a hanging SMTP connection cannot pin a Celery worker."""

    # --- Observability -------------------------------------------------------

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console", "auto"] = "auto"
    """"auto" resolves to console in development, json elsewhere — see
    `resolved_log_format`. Override only to force one or the other."""

    # --- CORS ----------------------------------------------------------------

    CORS_ORIGINS: str = "http://localhost:3000"
    """Comma-separated. Kept a plain string rather than list[str] because
    pydantic-settings parses list fields as JSON, so a comma-separated value
    would crash at startup instead of being split."""

    @field_validator("DATABASE_URL")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        # core/database.py builds an async engine; a sync URL fails later with
        # a much less obvious error, so reject it here.
        if not v.startswith(ASYNC_DB_DRIVERS):
            raise ValueError(
                f"DATABASE_URL must use an async driver {ASYNC_DB_DRIVERS}, got {v.split('://')[0]}://"
            )
        return v

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_placeholder_secret(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("SECRET_KEY must not be empty")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def resolved_log_format(self) -> str:
        if self.LOG_FORMAT != "auto":
            return self.LOG_FORMAT
        return "console" if self.ENVIRONMENT == "development" else "json"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    def check_production_readiness(self) -> list[str]:
        """Settings that are tolerable in dev but dangerous in production.

        Returned as warnings rather than raised, so a staging box missing an
        optional integration key still boots — main.py logs them at startup.
        """
        problems: list[str] = []
        if not self.is_production:
            return problems
        if self.SECRET_KEY == "change-me-to-a-long-random-string" or len(self.SECRET_KEY) < 32:
            problems.append("SECRET_KEY is a placeholder or shorter than 32 characters")
        if not self.ENCRYPTION_KEY:
            problems.append("ENCRYPTION_KEY is unset — integration OAuth tokens cannot be encrypted")
        if any(o.startswith("http://localhost") for o in self.cors_origins):
            problems.append(f"CORS_ORIGINS still allows localhost: {self.CORS_ORIGINS}")
        return problems


settings = Settings()
