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
