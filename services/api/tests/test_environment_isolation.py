"""The ordinary suite is offline, whatever the developer's machine holds (`tests/offline_guard.py`).

The risk was real: with `OPENAI_API_KEY` and `SMART_IMPORT_AI_MODE=assist` in the machine's
environment, the `settings` fixture of an ordinary test built a REAL OpenAI provider. What is
pinned here:

* the two guards as functions (`isolate` / `restore`, the tripwire's refusals);
* the WIRING, end to end: a child pytest started with an environment that imitates a machine
  (a fake key, assist or shadow) sees no provider, a refused connection is recorded, and a test
  that made one fails even when the code under test swallowed the error;
* the exception: a test marked `live_openai` is skipped unless the machine asks for it, and when it
  runs it gets the machine's environment back and can build a provider (nothing is sent);
* the explicit script, `python -m tests.live_openai_acceptance`, is not pytest and is never touched.

No real request is made by any of it: the key is a made-up string, and the unroutable address of the
tripwire is refused before a packet leaves.
"""

import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests import offline_guard
from tests.offline_guard import ExternalNetworkError, NetworkGuard

_API = Path(__file__).resolve().parents[1]
_REPO = _API.parents[1]
_PROBE = Path(__file__).with_name("isolation_probe.py")
MACHINES_KEY = "sk-test-the-machines-key-0000000000"
# What a developer who is trying the layer has in the environment.
A_MACHINE_TRYING_THE_LAYER = {
    "OPENAI_API_KEY": MACHINES_KEY,
    "SMART_IMPORT_AI_VOCABULARY_CERTAINTY": "true",
    "OPENAI_BASE_URL": "https://gateway.invalid/v1",
}


# --- the environment -------------------------------------------------------------------------


def test_isolate_forces_the_switches_off_and_drops_the_rest_and_restore_puts_them_back() -> None:
    machine = {
        "SMART_IMPORT_AI_MODE": "assist",
        "IMPORT_UNDERSTANDING_PROVIDER": "anthropic",
        "ASK_NINFA_PROVIDER": "anthropic",
        "OPENAI_API_KEY": MACHINES_KEY,
        "ANTHROPIC_API_KEY": "sk-ant-made-up",
        "SMART_IMPORT_AI_VOCABULARY_CERTAINTY": "true",
        "OPENAI_DATA_RESIDENCY": "eu",
        "UNRELATED": "kept",
    }
    environ = dict(machine)

    saved = offline_guard.isolate(environ)

    assert environ["SMART_IMPORT_AI_MODE"] == "off"
    assert environ["IMPORT_UNDERSTANDING_PROVIDER"] == "unconfigured"
    assert environ["ASK_NINFA_PROVIDER"] == "unconfigured"
    assert not {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_DATA_RESIDENCY"} & environ.keys()
    assert "SMART_IMPORT_AI_VOCABULARY_CERTAINTY" not in environ
    assert environ["UNRELATED"] == "kept"

    offline_guard.restore(environ, saved)

    assert environ == machine


def test_the_variables_of_this_very_run_are_isolated() -> None:
    """Ground truth for the suite that is running: whatever the machine holds, this is what the
    application reads."""
    assert os.environ["SMART_IMPORT_AI_MODE"] == "off"
    assert os.environ["IMPORT_UNDERSTANDING_PROVIDER"] == "unconfigured"
    assert "OPENAI_API_KEY" not in os.environ
    assert offline_guard.GUARD.active is True


# --- the tripwire ----------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "[::1]", "localhost", "0.0.0.0"])
def test_this_machine_is_never_refused(host: str) -> None:
    assert offline_guard.is_local(host) is True


@pytest.mark.parametrize(
    "host", ["203.0.113.1", "api.openai.com", "192.168.1.5", "10.0.0.2", "8.8.8.8", ""]
)
def test_anything_else_is_refused(host: str) -> None:
    assert offline_guard.is_local(host) is False


def test_the_test_database_host_is_the_one_exception() -> None:
    hosts = offline_guard.hosts_of("postgresql+psycopg://user:pw@db.internal:5432/ninfa_test", None)

    assert hosts == {"db.internal"}
    assert offline_guard.is_local("db.internal", hosts) is True
    assert offline_guard.is_local("db.internal") is False


def test_the_guard_refuses_and_records_an_external_connection_and_is_removed_exactly() -> None:
    guard = NetworkGuard()
    before = (socket.socket.connect, socket.socket.connect_ex)
    guard.install()
    try:
        with pytest.raises(ExternalNetworkError, match=r"203\.0\.113\.1:443"):
            socket.create_connection(("203.0.113.1", 443), timeout=0.2)
    finally:
        guard.uninstall()

    assert guard.attempts == ["203.0.113.1:443"]
    assert (socket.socket.connect, socket.socket.connect_ex) == before  # exactly as it was
    assert guard.active is False


def test_connect_ex_is_guarded_too_and_a_local_address_reaches_the_real_socket() -> None:
    guard = NetworkGuard()
    guard.install()
    try:
        with socket.socket(socket.AF_INET) as outside, pytest.raises(ExternalNetworkError):
            outside.connect_ex(("203.0.113.9", 80))
        # port 1 on this machine: the REAL connect ran (and was refused by the OS, not by us)
        with socket.socket(socket.AF_INET) as inside:
            inside.settimeout(0.5)
            refused_by_the_os = inside.connect_ex(("127.0.0.1", 1))
    finally:
        guard.uninstall()

    assert refused_by_the_os != 0
    assert guard.attempts == ["203.0.113.9:80"]


def test_a_lifted_guard_comes_back() -> None:
    guard = NetworkGuard()
    guard.install()
    try:
        with guard.lifted():
            assert guard.active is False
        assert guard.active is True
    finally:
        guard.uninstall()


# --- the wiring, end to end (a child pytest under a machine that selects the layer) ---------------


def _child(
    selector: str, machine: dict[str, str], *, live: bool = False
) -> subprocess.CompletedProcess[str]:
    """The probe, in a pytest of its own, under an environment that imitates a machine."""
    environment = {k: v for k, v in os.environ.items() if k != "RUN_LIVE_OPENAI"}
    environment.update(machine)
    if live:
        environment["RUN_LIVE_OPENAI"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_PROBE),
            "-k",
            selector,
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=_REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


@pytest.mark.parametrize("mode", ["assist", "shadow"])
def test_a_machine_that_selects_the_layer_gets_no_provider_in_the_ordinary_suite(
    mode: str,
) -> None:
    machine = {**A_MACHINE_TRYING_THE_LAYER, "SMART_IMPORT_AI_MODE": mode}

    run = _child("ordinary and not after", machine)

    assert run.returncode == 0, run.stdout[-2500:] + run.stderr[-800:]
    assert "2 passed" in run.stdout


def test_a_swallowed_connection_attempt_still_fails_the_test() -> None:
    machine = {**A_MACHINE_TRYING_THE_LAYER, "SMART_IMPORT_AI_MODE": "assist"}

    run = _child("swallowed", machine)

    assert run.returncode != 0
    assert "tried to leave this machine" in run.stdout + run.stderr
    assert "203.0.113.1:443" in run.stdout + run.stderr
    assert MACHINES_KEY not in run.stdout + run.stderr


def test_a_live_marked_test_is_skipped_unless_the_machine_asks_for_it() -> None:
    machine = {**A_MACHINE_TRYING_THE_LAYER, "SMART_IMPORT_AI_MODE": "assist"}

    run = _child("live", machine)

    assert run.returncode == 0, run.stdout[-1500:] + run.stderr[-500:]
    assert "1 skipped" in run.stdout
    assert "RUN_LIVE_OPENAI=1" in run.stdout


def test_a_live_marked_test_gets_the_machine_back_and_can_build_a_provider() -> None:
    machine = {**A_MACHINE_TRYING_THE_LAYER, "SMART_IMPORT_AI_MODE": "assist"}
    machine.pop("OPENAI_BASE_URL")  # a custom endpoint is not what is being shown here

    run = _child("live or ordinary", machine, live=True)

    assert run.returncode == 0, run.stdout[-2500:] + run.stderr[-800:]
    assert "4 passed" in run.stdout  # the two ordinary ones, the live one, and the one after it


# --- the explicit script ---------------------------------------------------------------------


def test_the_explicit_live_acceptance_is_not_pytest_and_still_sees_the_machines_key() -> None:
    """`python -m tests.live_openai_acceptance` runs outside pytest: no conftest, no isolation.
    Its `main` is run here in a plain interpreter with the machine's key and a stub in place of the
    real round trip, so only the thing under test happens: the key arrives, nothing is
    neutralised."""
    program = textwrap.dedent(
        """
        import os

        from tests.live_openai_acceptance import Report, main

        seen = []

        def stub(key, **_):
            seen.append(key)
            report = Report()
            report.add("stub", True)
            return report

        code = main(run=stub)
        print("exit", code, "key_arrived", seen == [os.environ["OPENAI_API_KEY"]])
        """
    )
    environment = {**os.environ, "OPENAI_API_KEY": MACHINES_KEY, "SMART_IMPORT_AI_MODE": "assist"}

    run = subprocess.run(
        [sys.executable, "-c", program],
        cwd=_API,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert run.returncode == 0, run.stderr[-1200:]
    assert "exit 0 key_arrived True" in run.stdout
    assert MACHINES_KEY not in run.stdout + run.stderr  # and the key is never printed
