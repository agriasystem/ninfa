"""The ordinary test suite is OFFLINE, whatever the developer's machine holds.

A workstation can carry `OPENAI_API_KEY` and a `SMART_IMPORT_AI_MODE` of `shadow` or `assist` (in
the User or Machine environment, or in the root `.env`) because its owner is trying the layer. The
application reads exactly those variables, so an ordinary test that builds the app would build a
REAL provider and send a REAL request. Two guards, both for the test PROCESS only (nothing of the
machine is changed, and `restore` puts the process back):

1. `isolate` - the AI switches are forced to off / unconfigured and every other AI variable is
   dropped from this process' environment, before any `app` module is imported
   (`services/conftest.py`). `.env` loses too: a process variable outranks it.
2. `NetworkGuard` - a tripwire under that: any connection that is not to this machine (or to the
   test database) is refused AND RECORDED, and the test that made it fails at its end. The record
   is what matters: the adapter swallows every provider failure by design (Smart Import must never
   break), so a refused connection alone would pass unnoticed as "the model was down".

A test that is meant to reach the real API says so with `@pytest.mark.live_openai`: it is skipped
unless the machine says `RUN_LIVE_OPENAI=1`, and while it runs the machine environment is back and
the tripwire is off. The explicit script (`python -m tests.live_openai_acceptance`) is not pytest
at all and is never touched by any of this.

Stdlib only: it is imported before the application is.
"""

import ipaddress
import socket
from collections.abc import Callable, Iterable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

# Forced, not removed: a value in `.env` must lose to the process environment.
FORCED = {
    "SMART_IMPORT_AI_MODE": "off",
    "IMPORT_UNDERSTANDING_PROVIDER": "unconfigured",
    "ASK_NINFA_PROVIDER": "unconfigured",
}
# Dropped: with the switches off they do nothing, and a test of a default must see the default.
REMOVED = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_DATA_RESIDENCY",
    "SMART_IMPORT_OPENAI_MODEL",
    "SMART_IMPORT_OPENAI_REASONING",
    "SMART_IMPORT_OPENAI_TIMEOUT_SECONDS",
    "SMART_IMPORT_AI_VOCABULARY_CERTAINTY",
    "ANTHROPIC_API_KEY",
)

Saved = dict[str, str | None]


def isolate(environ: MutableMapping[str, str]) -> Saved:
    """Makes `environ` (the process' own copy) offline; returns what it held, for `restore`."""
    saved: Saved = {name: environ.get(name) for name in (*FORCED, *REMOVED)}
    for name in REMOVED:
        environ.pop(name, None)
    environ.update(FORCED)
    return saved


def restore(environ: MutableMapping[str, str], saved: Saved) -> None:
    for name, value in saved.items():
        if value is None:
            environ.pop(name, None)
        else:
            environ[name] = value


def hosts_of(*urls: str | None) -> frozenset[str]:
    """The hosts a test is allowed to reach besides this machine: the test database's."""
    found: set[str] = set()
    for url in urls:
        host = urlsplit(url or "").hostname
        if host:
            found.add(host.lower())
    return frozenset(found)


class ExternalNetworkError(ConnectionError):
    """An ordinary test tried to leave this machine.

    A `ConnectionError` on purpose, not a bare exception: the standard library closes the socket it
    opened when `connect` raises an `OSError` (otherwise the socket leaks), and an HTTP client turns
    it into an ordinary "could not connect". What makes the test FAIL is the record, not this."""


def is_local(host: str, allowed: Iterable[str] = ()) -> bool:
    name = host.strip("[]").lower()
    if name == "localhost" or name in set(allowed):
        return True
    try:
        address = ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:  # a name that was not resolved yet: it is leaving, whatever it is
        return False
    return address.is_loopback or address.is_unspecified


class NetworkGuard:
    """Refuses, and records, every connection that is not local. Installed over `socket.socket`."""

    def __init__(self, allowed: Iterable[str] = ()) -> None:
        self.allowed: frozenset[str] = frozenset(allowed)
        self.attempts: list[str] = []
        # what to put back: the method as it was, and whether `socket.socket` defined it itself
        self._installed: dict[str, tuple[Callable[..., Any], bool]] | None = None

    @property
    def active(self) -> bool:
        return self._installed is not None

    def install(self) -> None:
        if self._installed is not None:
            return
        names = ("connect", "connect_ex")
        before = {n: (getattr(socket.socket, n), n in vars(socket.socket)) for n in names}
        connect, connect_ex = before["connect"][0], before["connect_ex"][0]

        def refuse(address: Any) -> bool:
            """True (after recording) when `address` is not this machine's."""
            if not isinstance(address, tuple) or not address or not isinstance(address[0], str):
                return False  # a Unix socket, or something that is not an internet address
            if is_local(address[0], self.allowed):
                return False
            self.attempts.append(f"{address[0]}:{address[1] if len(address) > 1 else '?'}")
            return True

        def guarded_connect(sock: socket.socket, address: Any) -> Any:
            if refuse(address):
                raise ExternalNetworkError(
                    f"an ordinary test tried to connect to {self.attempts[-1]}: "
                    "the suite is offline"
                )
            return connect(sock, address)

        def guarded_connect_ex(sock: socket.socket, address: Any) -> Any:
            if refuse(address):
                raise ExternalNetworkError(
                    f"an ordinary test tried to connect to {self.attempts[-1]}: "
                    "the suite is offline"
                )
            return connect_ex(sock, address)

        self._installed = before
        socket.socket.connect = guarded_connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign,assignment]

    def uninstall(self) -> None:
        if self._installed is None:
            return
        for name, (method, defined_here) in self._installed.items():
            if defined_here:
                setattr(socket.socket, name, method)
            else:
                delattr(socket.socket, name)  # back to the C base class' own
        self._installed = None

    @contextmanager
    def lifted(self) -> Iterator[None]:
        """The tripwire off for a while (a test that is explicitly live)."""
        was_on = self.active
        self.uninstall()
        try:
            yield
        finally:
            if was_on:
                self.install()


# The one the whole suite shares (`services/conftest.py` installs it; tests read its record).
GUARD = NetworkGuard()

__all__ = [
    "FORCED",
    "GUARD",
    "REMOVED",
    "ExternalNetworkError",
    "NetworkGuard",
    "hosts_of",
    "is_local",
    "isolate",
    "restore",
]
