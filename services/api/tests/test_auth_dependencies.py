"""Authentication & Session V1: dependency scope (review items 120-123)."""

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _backend_dependencies() -> set[str]:
    pyproject = tomllib.loads(
        (_REPO_ROOT / "services" / "api" / "pyproject.toml").read_text(encoding="utf-8")
    )
    return {
        entry.split()[0].split("[")[0].split(">=")[0].split("==")[0].split("~=")[0].lower()
        for entry in pyproject["project"]["dependencies"]
    }


# --- 120: only the justified Argon2 dependency was added -----------------------------------------


def test_only_argon2_cffi_was_added_to_backend_dependencies() -> None:
    known_before_gate_13 = {
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic-settings",
        "sqlalchemy",
        "alembic",
        "psycopg",
        "tzdata",
        "openpyxl",
    }
    dependencies = _backend_dependencies()
    unexpected = dependencies - known_before_gate_13 - {"argon2-cffi"}
    assert unexpected == set(), f"unexpected new dependency: {unexpected}"
    assert "argon2-cffi" in dependencies


# --- 121: frontend dependencies unchanged ---------------------------------------------------------


def test_frontend_package_files_mention_no_auth_related_package() -> None:
    for relative in ("package.json", "package-lock.json", "apps/web/package.json"):
        path = _REPO_ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in ("jsonwebtoken", "passport", "next-auth", "oauth", "argon2"):
            assert forbidden not in text, (relative, forbidden)


# --- 122-123: no JWT, no OAuth dependency --------------------------------------------------------


def test_no_jwt_dependency() -> None:
    dependencies = _backend_dependencies()
    for forbidden in ("pyjwt", "python-jose", "jwt", "authlib"):
        assert forbidden not in dependencies


def test_no_oauth_dependency() -> None:
    dependencies = _backend_dependencies()
    for forbidden in ("authlib", "oauthlib", "requests-oauthlib", "itsdangerous"):
        assert forbidden not in dependencies
