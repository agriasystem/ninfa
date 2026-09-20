import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

VALID_URL = "postgresql+psycopg://user:pw@db.example:5432/ninfa"


def make_settings(**overrides: object) -> Settings:
    # _env_file=None: ignore any developer .env, only the given values count.
    return Settings(_env_file=None, database_url=VALID_URL, **overrides)  # type: ignore[arg-type]


def test_defaults_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "DEBUG", "LOG_LEVEL", "API_HOST", "API_PORT", "CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)

    settings = make_settings()

    assert settings.app_env == "development"
    assert settings.debug is False
    assert settings.cors_origins == []
    assert settings.api_port == 8000


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "9123")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DATABASE_URL", VALID_URL)

    settings = Settings(_env_file=None)

    assert settings.api_port == 9123
    assert settings.log_level == "DEBUG"


def test_cors_origins_parsed_from_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example ,")
    monkeypatch.setenv("DATABASE_URL", VALID_URL)

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_must_use_psycopg_driver() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        Settings(_env_file=None, database_url="postgresql://user:pw@db/ninfa")


def test_database_url_is_never_exposed_in_repr() -> None:
    settings = make_settings()

    assert "pw@" not in repr(settings)
    assert settings.libpq_conninfo == "postgresql://user:pw@db.example:5432/ninfa"


def test_production_rejects_debug() -> None:
    with pytest.raises(ValidationError, match="DEBUG"):
        make_settings(app_env="production", debug=True)


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(app_env="production", cors_origins=["*"])


def test_production_disables_interactive_docs() -> None:
    client = TestClient(create_app(make_settings(app_env="production")))

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_cors_allows_only_configured_origin() -> None:
    settings = make_settings(cors_origins=["https://web.example"])
    client = TestClient(create_app(settings))

    allowed = client.get("/api/v1/health", headers={"Origin": "https://web.example"})
    denied = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "https://web.example"
    assert "access-control-allow-origin" not in denied.headers
