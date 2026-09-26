"""The one seam every time-dependent module reads "now" through (Gate 13's own need: session
expiry, lockout windows, password-changed timestamps). Never `datetime.now()`/`datetime.utcnow()`
scattered across modules - a single injectable `Clock` callable, defaulting to the real UTC clock,
swappable in tests for exact control over expiry/lockout-window assertions.
"""

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    """FastAPI dependency: the real clock in production, overridable per-test via
    `app.dependency_overrides[get_clock]` for the lockout-expiry/session-expiry scenarios that
    need to advance time deterministically through a real HTTP call (see `tests/auth_support.py`'s
    `MutableClock`)."""
    return utcnow


__all__ = ["Clock", "get_clock", "utcnow"]
