"""Typed application settings, read from the environment (and the root `.env`)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Request
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# <repo>/services/api/app/core/config.py -> <repo>/.env
_ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"

_SQLALCHEMY_PREFIX = "postgresql+psycopg://"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also carries web-only variables
    )

    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    # Browser origins allowed by CORS. Empty = no cross-origin access.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # SQLAlchemy URL with the psycopg 3 driver. Kept secret so it never leaks in logs/repr.
    database_url: SecretStr

    # The session cookie's own `Secure` flag (Gate 13). Defaults to HTTPS-only everywhere; a
    # local plain-HTTP dev override must be explicit (`SESSION_COOKIE_SECURE=false` in `.env`),
    # never the default - see `_check_production_safety` below and ADR 0019.
    session_cookie_secure: bool = True

    # Ask NINFA's own language model provider (Gate 18/19). Defaults to `unconfigured` -
    # `AskNinfaService` answers `UNAVAILABLE` until a real provider is EXPLICITLY selected here;
    # an API key existing is never enough by itself (see `_check_ask_ninfa_provider_configuration`
    # below and ADR 0025, "why provider selection is explicit"). `anthropic_api_key` is `SecretStr`
    # for the same reason `database_url` is: it must never render in a `repr()`, a log line or an
    # exception message.
    ask_ninfa_provider: Literal["unconfigured", "anthropic"] = "unconfigured"
    anthropic_api_key: SecretStr | None = None
    # The OPTIONAL assistant of Smart Import V3 (it suggests what a column means when the rules
    # found nothing). Off by default, selected explicitly like the provider above, and never
    # needed: Smart Import reads files completely without it.
    import_understanding_provider: Literal["unconfigured", "anthropic"] = "unconfigured"

    # Smart Import's semantic layer (OpenAI Responses API). `SMART_IMPORT_AI_MODE` says what NINFA
    # does with a model's reading: `off` (the default: no model is ever asked, no network library is
    # touched), `shadow` (the model is asked and MEASURED, nothing is applied) or `assist` (its
    # reading is applied as suggestions, and where the file's own values prove it, as a confirmed
    # column - after every check, never instead of one). A mode other than `off` with no
    # `OPENAI_API_KEY` is NOT an error: Smart Import reads files exactly as it does with `off`
    # (the app says so once, at startup). The key is a `SecretStr`: it never renders in a repr, a
    # log line or an exception message.
    smart_import_ai_mode: Literal["off", "shadow", "assist"] = "off"
    openai_api_key: SecretStr | None = None
    smart_import_openai_model: str = Field(default="gpt-6.1-sol", min_length=1, max_length=100)
    # `none` sends no reasoning parameter at all (a model that has none).
    # `gpt-6.1-sol` accepts low / medium / high / xhigh / max (NOT none or minimal: it refuses them,
    # and the answer falls back to the rules). `low` reads as well as `medium` and takes about 40%
    # less time (V1.1: p50 4.9 s against 8.3 s, no timeout in 50 calls against 1).
    smart_import_openai_reasoning: Literal["none", "minimal", "low", "medium", "high"] = "low"
    smart_import_openai_timeout_seconds: float = Field(default=25.0, ge=1.0, le=120.0)
    # May a column a model named, whose VALUES NINFA's own vocabulary recognises, become certain
    # (no question)? OFF: a model's reading is only ever a MEDIUM suggestion a person confirms. It
    # is off because the live benchmark with the real model found three unsafe READY with it on
    # (files carrying a sentence of orders, read correctly and not flagged by the model): ADR 0052.
    smart_import_ai_vocabulary_certainty: bool = False
    # A custom endpoint (a proxy, an Azure-style gateway) OR a regional one OpenAI itself offers
    # (`eu`...), never both - the SDK refuses the pair. Nothing is hard-coded: a regional one is
    # used only when the OpenAI project is set up for it.
    openai_base_url: str | None = None
    openai_data_residency: Literal["global", "us", "eu", "ae", "au", "in", "jp"] | None = None

    # Mia, the assistant of NINFA (Mia OpenAI Intelligence V1, ADR 0055): the OpenAI Responses API
    # with a closed catalog of read-only NINFA tools. SEPARATE from Smart Import's layer above: its
    # own switch, its own model setting, no shared behaviour - only the key, the endpoint and the
    # data residency are shared, because they describe the account, not a feature. `unconfigured`
    # (the default) means Mia answers "unavailable" and NINFA works exactly as before; an API key
    # alone never turns Mia on (the same rule as every provider here, ADR 0025). Selecting `openai`
    # with no key is NOT a startup error: Mia stays unavailable and the app says so once (a failure
    # of Mia must never stop NINFA).
    mia_provider: Literal["unconfigured", "openai"] = "unconfigured"
    mia_openai_model: str = Field(default="gpt-6.1-sol", min_length=1, max_length=100)
    # Per model call. A whole turn has its own, longer deadline
    # (`ai.mia.types.TURN_DEADLINE_SECONDS`).
    mia_openai_timeout_seconds: float = Field(default=40.0, ge=1.0, le=120.0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(_SQLALCHEMY_PREFIX):
            raise ValueError(f"DATABASE_URL must start with '{_SQLALCHEMY_PREFIX}'")
        return value

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if self.app_env == "production":
            if self.debug:
                raise ValueError("DEBUG must be false when APP_ENV=production")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS must not contain '*' when APP_ENV=production")
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE must be true when APP_ENV=production")
        return self

    @model_validator(mode="after")
    def _check_ask_ninfa_provider_configuration(self) -> "Settings":
        """FAIL CLOSED at startup, not at the first request: selecting `anthropic` without a real
        key is a configuration error, never a silent fallback to `unconfigured` (see ADR 0025).
        Local development is never broken by this - `ask_ninfa_provider` simply defaults to
        `unconfigured`, which needs no key at all."""
        if self.ask_ninfa_provider == "anthropic":
            key = self.anthropic_api_key
            if key is None or not key.get_secret_value().strip():
                raise ValueError("ANTHROPIC_API_KEY is required when ASK_NINFA_PROVIDER=anthropic")
        if self.import_understanding_provider == "anthropic":
            key = self.anthropic_api_key
            if key is None or not key.get_secret_value().strip():
                raise ValueError(
                    "ANTHROPIC_API_KEY is required when IMPORT_UNDERSTANDING_PROVIDER=anthropic"
                )
        return self

    @model_validator(mode="after")
    def _check_smart_import_ai_configuration(self) -> "Settings":
        """Two selections of a model for the same job are a mistake, not a precedence rule; and a
        custom endpoint receives the document the model is shown, so it must be a deliberate one."""
        if (
            self.smart_import_ai_mode != "off"
            and self.import_understanding_provider != "unconfigured"
        ):
            raise ValueError(
                "SMART_IMPORT_AI_MODE and IMPORT_UNDERSTANDING_PROVIDER both select a model for "
                "Smart Import: set only one of them"
            )
        if self.openai_base_url is not None:
            if self.openai_data_residency is not None:
                raise ValueError("OPENAI_BASE_URL and OPENAI_DATA_RESIDENCY are mutually exclusive")
            url = self.openai_base_url.strip().lower()
            loopback = url.startswith(("http://127.0.0.1", "http://localhost"))
            if not (url.startswith("https://") or loopback):
                raise ValueError("OPENAI_BASE_URL must be an https:// URL")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sqlalchemy_url(self) -> str:
        """URL for SQLAlchemy / Alembic."""
        return self.database_url.get_secret_value()

    @property
    def libpq_conninfo(self) -> str:
        """Same database as a plain libpq URL (used by psycopg-native code, e.g. the worker)."""
        return "postgresql://" + self.sqlalchemy_url.removeprefix(_SQLALCHEMY_PREFIX)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_request_settings(request: Request) -> Settings:
    """FastAPI dependency: the `Settings` THIS app was actually built with (`app.state.settings`,
    set by `create_app()`) - not necessarily `get_settings()`'s own process-wide cached instance.
    Anything a route needs to honour per-app (the session cookie's `Secure` flag, in particular)
    reads it through here, so a test that builds its own `Settings` override
    (`tests/conftest.py`'s own `settings` fixture) is actually respected end to end.
    """
    settings: Settings = request.app.state.settings
    return settings
