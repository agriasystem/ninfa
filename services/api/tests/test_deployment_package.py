"""Gate 27B: the pilot deployment package (`deploy/`, `scripts/*.sh`, `docs/operations/`).

Lightweight guards on the things that must never drift: the env templates hold no secret and the web
template can never carry API credentials, the units run as a non-root user with explicit
environment files, the proxy never touches cookies, the daily wrapper runs the three supported
commands and is honest about its exit codes, and the runbooks never recommend a disabled cookie
`Secure` flag, a schema downgrade, a fixed-UTC schedule or an authentication bypass. Prose is only
checked where a wrong sentence would be dangerous.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from app.core.config import Settings
from tests.support import alembic_config

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy"
OPERATIONS = ROOT / "docs" / "operations"
SCRIPTS = ROOT / "scripts"
WRAPPER = SCRIPTS / "run-daily-analysis.sh"
WITH_ENV = SCRIPTS / "with-env.sh"
BASH = shutil.which("bash")

_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assignments(path: Path) -> dict[str, str]:
    """The uncommented KEY=VALUE lines of an env template."""
    found: dict[str, str] = {}
    for line in _read(path).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        assert match, f"{path.name}: not KEY=VALUE: {line!r}"
        found[match.group(1)] = match.group(2)
    return found


def _package_files() -> list[Path]:
    return [
        path
        for base in (DEPLOY, OPERATIONS, SCRIPTS)
        for path in base.rglob("*")
        if path.is_file()
        and path.suffix in {".md", ".sh", ".service", ".example", ".conf"}
        or path.name.endswith((".env.example", ".conf.example"))
    ]


def _unit(name: str) -> str:
    return _read(DEPLOY / "systemd" / name)


def _directives(unit_text: str) -> list[str]:
    return [
        line.strip()
        for line in unit_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


# --- env templates ------------------------------------------------------------------------------


def test_01_env_templates_hold_no_secret_values() -> None:
    api = _assignments(DEPLOY / "env" / "api.env.example")
    web = _assignments(DEPLOY / "env" / "web.env.example")

    assert "<" in api["DATABASE_URL"] and ">" in api["DATABASE_URL"]  # explicit placeholders
    assert api["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert "sslmode=require" in api["DATABASE_URL"]
    assert "ANTHROPIC_API_KEY" not in api  # only ever a commented line, set at enablement time
    for text in (
        _read(DEPLOY / "env" / "api.env.example"),
        _read(DEPLOY / "env" / "web.env.example"),
    ):
        assert "sk-ant-" not in text
    assert web == {
        "NEXT_PUBLIC_API_BASE_URL": web["NEXT_PUBLIC_API_BASE_URL"],
        "WEB_HOST": "127.0.0.1",
        "WEB_PORT": web["WEB_PORT"],
    }


def test_02_api_template_is_production_and_same_origin() -> None:
    api = _assignments(DEPLOY / "env" / "api.env.example")

    assert api["APP_ENV"] == "production"
    assert api["DEBUG"] == "false"
    assert api["API_HOST"] == "127.0.0.1"  # loopback behind the reverse proxy
    assert api["CORS_ORIGINS"] == ""  # same-origin topology: no cross-origin access
    assert api["ASK_NINFA_PROVIDER"] == "unconfigured"  # enabled only by the documented policy
    assert "TEST_DATABASE_URL" not in api
    assert "SESSION_COOKIE_SECURE" not in api
    # Only variables the code actually reads.
    assert set(api) <= {name.upper() for name in Settings.model_fields}


def test_03_web_template_can_never_carry_api_credentials() -> None:
    web = _assignments(DEPLOY / "env" / "web.env.example")

    assert set(web) == {"NEXT_PUBLIC_API_BASE_URL", "WEB_HOST", "WEB_PORT"}
    origin = web["NEXT_PUBLIC_API_BASE_URL"]
    assert origin.startswith("https://") and not origin.endswith("/") and "/api" not in origin
    for forbidden in ("DATABASE_URL", "ANTHROPIC_API_KEY", "TEST_DATABASE_URL"):
        assert forbidden not in web


def test_04_templates_use_the_plain_format_both_loaders_read() -> None:
    for name in ("api.env.example", "web.env.example"):
        for key, value in _assignments(DEPLOY / "env" / name).items():
            assert not value.startswith(('"', "'")), f"{name}: {key} must be unquoted"
            assert " #" not in value, f"{name}: {key} has an inline comment"


# --- process definitions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "env_file", "command"),
    [
        ("ninfa-api.service", "/etc/ninfa/api.env", "-m app"),
        ("ninfa-worker.service", "/etc/ninfa/api.env", "-m worker run"),
        ("ninfa-web.service", "/etc/ninfa/web.env", "apps/web/scripts/run-next.mjs start"),
        ("ninfa-daily-analysis.service", "/etc/ninfa/api.env", "scripts/run-daily-analysis.sh"),
    ],
)
def test_05_units_are_non_root_with_an_explicit_environment_file(
    unit: str, env_file: str, command: str
) -> None:
    lines = _directives(_unit(unit))

    assert "User=ninfa" in lines and "Group=ninfa" in lines
    assert f"EnvironmentFile={env_file}" in lines
    assert any(line.startswith("WorkingDirectory=") for line in lines)
    assert any(line.startswith("ExecStart=") and command in line for line in lines)
    assert "StandardOutput=journal" in lines and "StandardError=journal" in lines
    # The root `.env` hazard: the unit refuses to start if the file exists.
    assert any(line.startswith("ExecStartPre=") and "test ! -e" in line for line in lines)
    # No secrets in a unit file.
    environment = [line for line in lines if line.startswith("Environment=")]
    assert all(
        not re.search(r"DATABASE|KEY|PASSWORD|SECRET|TOKEN", line, re.I) for line in environment
    )
    assert not any(line.startswith("User=root") for line in lines)


@pytest.mark.parametrize("unit", ["ninfa-api.service", "ninfa-worker.service", "ninfa-web.service"])
def test_06_long_running_units_restart_and_stop_gracefully(unit: str) -> None:
    lines = _directives(_unit(unit))

    assert "Restart=always" in lines
    assert "KillSignal=SIGTERM" in lines
    assert any(line.startswith("TimeoutStopSec=") for line in lines)


def test_07_web_unit_never_receives_the_api_environment_and_no_timer_is_shipped() -> None:
    web = _directives(_unit("ninfa-web.service"))

    assert not any("api.env" in line for line in web)
    assert not any("DATABASE_URL" in line or "ANTHROPIC" in line for line in web)
    assert not list(DEPLOY.rglob("*.timer"))  # the scheduler is external and not configured here
    assert "[Install]" not in _directives(_unit("ninfa-daily-analysis.service"))


# --- reverse proxy ------------------------------------------------------------------------------


def test_08_proxy_routes_one_origin_and_never_touches_cookies() -> None:
    text = _read(DEPLOY / "nginx" / "ninfa.conf.example")
    code = "\n".join(
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )

    assert "listen 443 ssl" in code and "return 301 https://$host$request_uri;" in code
    assert re.search(r"location /api/ \{[^}]*proxy_pass http://127\.0\.0\.1:8000;", code, re.S)
    assert re.search(r"location / \{[^}]*proxy_pass http://127\.0\.0\.1:3100;", code, re.S)
    targets = re.findall(r"proxy_pass\s+(\S+);", code)
    assert targets and all(t.startswith("http://127.0.0.1:") for t in targets)
    assert "proxy_cookie" not in code and "Set-Cookie" not in code and "Domain" not in code
    assert "/path/to/" in code  # placeholder certificate paths only
    assert (
        "Strict-Transport-Security" in text
    )  # documented, enabled by AGRIA after HTTPS is verified


# --- the daily wrapper --------------------------------------------------------------------------


def test_09_wrapper_runs_the_three_supported_commands_in_order_and_is_honest() -> None:
    text = _read(WRAPPER)

    assert "set -euo pipefail" in text
    order = [
        text.index("-m worker dispatch-analysis"),
        text.index("-m worker run --once"),
        text.index("-m worker analysis-status"),
    ]
    assert order == sorted(order)
    assert "does not prove" in text.lower() or "do not prove" in text.lower()
    assert "10:00" in text and "Europe/Rome" in text
    assert "postgresql" not in text and "sk-ant" not in text  # no embedded credentials


@pytest.mark.skipif(BASH is None, reason="bash is not available")
@pytest.mark.parametrize("script", [WRAPPER, WITH_ENV], ids=lambda p: p.name)
def test_10_scripts_are_valid_bash_with_lf_endings(script: Path) -> None:
    assert b"\r" not in script.read_bytes()
    assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
    assert subprocess.run([str(BASH), "-n", script.as_posix()], check=False).returncode == 0
    shellcheck = shutil.which("shellcheck")
    if shellcheck:  # only if already installed; never added as a dependency
        assert (
            subprocess.run([shellcheck, "-S", "warning", script.as_posix()], check=False).returncode
            == 0
        )


def _run_wrapper(
    tmp_path: Path, *, env: dict[str, str], stub_exit_codes: dict[str, int] | None = None
) -> tuple[int, list[str]]:
    """Run the real wrapper with a stub standing in for `python`: records every invocation."""
    log = tmp_path / "calls.txt"
    stub = tmp_path / "python-stub"
    stub.write_text(
        '#!/usr/bin/env bash\necho "$3" >> "$STUB_LOG"\n'
        'case "$3" in dispatch-analysis) exit "${STUB_RC_DISPATCH:-0}";;'
        ' run) exit "${STUB_RC_RUN:-0}";; analysis-status) exit "${STUB_RC_STATUS:-0}";; esac\n',
        encoding="utf-8",
        newline="\n",
    )
    stub.chmod(0o755)
    codes = stub_exit_codes or {}
    full_env = {
        "PATH": os.environ.get("PATH", ""),
        "NINFA_PYTHON": stub.as_posix(),
        "NINFA_APP_DIR": ROOT.as_posix(),
        "STUB_LOG": log.as_posix(),
        "STUB_RC_DISPATCH": str(codes.get("dispatch", 0)),
        "STUB_RC_RUN": str(codes.get("run", 0)),
        "STUB_RC_STATUS": str(codes.get("status", 0)),
        **env,
    }
    if sys.platform == "win32" and "SYSTEMROOT" in os.environ:
        full_env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    assert BASH is not None
    result = subprocess.run(
        [BASH, WRAPPER.as_posix()], env=full_env, capture_output=True, text=True, check=False
    )
    calls = log.read_text(encoding="utf-8").split() if log.exists() else []
    return result.returncode, calls


_PRODUCTION = {"DATABASE_URL": "postgresql+psycopg://placeholder", "APP_ENV": "production"}


@pytest.mark.skipif(BASH is None, reason="bash is not available")
def test_11_wrapper_exits_zero_when_all_three_commands_succeed(tmp_path: Path) -> None:
    code, calls = _run_wrapper(tmp_path, env=_PRODUCTION)

    assert code == 0
    assert calls == ["dispatch-analysis", "run", "analysis-status"]


@pytest.mark.skipif(BASH is None, reason="bash is not available")
@pytest.mark.parametrize("failing", ["dispatch", "run", "status"])
def test_12_wrapper_still_attempts_every_step_and_exits_one_when_one_fails(
    tmp_path: Path, failing: str
) -> None:
    code, calls = _run_wrapper(tmp_path, env=_PRODUCTION, stub_exit_codes={failing: 3})

    assert code == 1
    assert calls == ["dispatch-analysis", "run", "analysis-status"]


@pytest.mark.skipif(BASH is None, reason="bash is not available")
@pytest.mark.parametrize(
    "env",
    [
        {"APP_ENV": "production"},  # no DATABASE_URL
        {"DATABASE_URL": "postgresql+psycopg://x", "APP_ENV": "development"},
        {**_PRODUCTION, "TEST_DATABASE_URL": "postgresql+psycopg://test"},
    ],
    ids=["no-database-url", "not-production", "test-database-url-set"],
)
def test_13_wrapper_refuses_a_non_production_environment_and_runs_nothing(
    tmp_path: Path, env: dict[str, str]
) -> None:
    code, calls = _run_wrapper(tmp_path, env=env)

    assert code == 2
    assert calls == []


@pytest.mark.skipif(BASH is None, reason="bash is not available")
def test_14_env_loader_reads_values_literally_and_never_echoes_a_bad_line(tmp_path: Path) -> None:
    assert BASH is not None
    good = tmp_path / "good.env"
    good.write_text("# comment\n\nFOO=a&b;c?x=1\nEMPTY=\n", encoding="utf-8", newline="\n")
    bad = tmp_path / "bad.env"
    bad.write_text("not a valid line SECRET-VALUE\n", encoding="utf-8", newline="\n")
    probe = 'printf "%s|%s" "$FOO" "$EMPTY"'

    loaded = subprocess.run(
        [BASH, WITH_ENV.as_posix(), good.as_posix(), BASH, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    refused = subprocess.run(
        [BASH, WITH_ENV.as_posix(), bad.as_posix(), "true"],
        capture_output=True,
        text=True,
        check=False,
    )
    missing = subprocess.run(
        [BASH, WITH_ENV.as_posix(), (tmp_path / "none.env").as_posix(), "true"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (loaded.returncode, loaded.stdout) == (0, "a&b;c?x=1|")
    assert refused.returncode == 2 and "SECRET-VALUE" not in refused.stderr + refused.stdout
    assert missing.returncode == 2


# --- the runbooks -------------------------------------------------------------------------------


def test_15_the_documented_migration_head_is_the_real_head() -> None:
    [head] = ScriptDirectory.from_config(
        alembic_config("postgresql+psycopg://unused/unused")
    ).get_heads()

    assert head == "0013_property_analysis_policy"  # update the runbooks with every new migration
    for name in ("pilot-deployment-v1.md", "pilot-smoke-checklist-v1.md"):
        assert head in _read(OPERATIONS / name)


def test_16_the_scheduler_is_documented_as_ten_oclock_europe_rome_never_fixed_utc() -> None:
    for name in ("pilot-daily-operations-v1.md",):
        text = _read(OPERATIONS / name)
        assert "10:00" in text and "Europe/Rome" in text and "named timezone" in text
        assert "10:15" in text  # the mandatory operator check
    for path in _package_files():
        assert not re.search(r"\b0?[89]:00\s*UTC\b", _read(path)), f"{path.name}: fixed UTC time"


def test_17_nothing_in_the_package_recommends_a_schema_downgrade_or_a_disabled_secure_cookie() -> (
    None
):
    for path in _package_files():
        text = _read(path)
        assert not re.search(r"alembic\b[^\n]*\bdowngrade\b", text), (
            f"{path.name}: downgrade command"
        )
        assert not re.search(r"SESSION_COOKIE_SECURE\s*=\s*false", text, re.I), path.name
    deployment = _read(OPERATIONS / "pilot-deployment-v1.md")
    assert "Do not run an Alembic downgrade" in deployment


def test_18_no_authentication_bypass_or_stash_reference_in_the_package() -> None:
    for path in [*DEPLOY.rglob("*"), *SCRIPTS.glob("*.sh")]:
        if path.is_file():
            assert "bypass" not in _read(path).lower(), f"{path.name}: development bypass text"
    for path in _package_files():
        assert not re.search(r"stash@\{", _read(path)), f"{path.name}: encodes a local stash index"
    assert "must never be deployed" in _read(OPERATIONS / "pilot-deployment-v1.md")


def test_19_the_package_contains_no_real_looking_secret_and_no_scheduler_decorator() -> None:
    for path in _package_files():
        text = _read(path)
        assert "sk-ant-" not in text, path.name
        for password in re.findall(r"://[^:/\s@<]+:([^@\s<>]+)@", text):
            raise AssertionError(f"{path.name}: a URL with a literal password: {password!r}")
        assert "@app.periodic" not in text and "periodic(" not in text, path.name


def test_20_cold_start_and_ask_policy_are_stated_where_operators_will_read_them() -> None:
    for name in ("pilot-onboarding-v1.md", "pilot-expectations-v1.md"):
        text = _read(OPERATIONS / name)
        assert "DATA_QUALITY_LIMITED" in text and "five weeks" in text, name
        assert "Importing historical bookings does not by itself create" in text or (
            "does not by itself create that history" in text
        ), name
    deployment = _read(OPERATIONS / "pilot-deployment-v1.md")
    for condition in ("spending limit", "ASK_NINFA_PROVIDER=anthropic", "unconfigured"):
        assert condition in deployment
    assert "chmod 600" in _read(DEPLOY / "env" / "api.env.example")
    assert "0600" in deployment or "**0600**" in deployment
