"""Event-loop policy for the worker.

psycopg's async API cannot run on Windows' default ProactorEventLoop; it needs a
SelectorEventLoop. Passing `loop_factory` to `asyncio.run` selects it explicitly on every
platform, without touching the global (and deprecated) event-loop policy.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any


def run[T](main: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(main, loop_factory=asyncio.SelectorEventLoop)
