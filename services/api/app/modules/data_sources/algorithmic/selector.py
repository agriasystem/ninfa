"""Which selection engine reads the columns: V3's greedy one, or V4's algorithmic one.

`SMART_IMPORT_UNDERSTANDING_ENGINE` says (`v3` is the default and the way back: ROLLBACK IS ONE
SETTING, no data to migrate - a mapping the person confirmed is stored as columns and fields, never
as what the engine thought). The app reads the setting once when it starts (`configure`). A test or
a benchmark picks an engine for the code inside a `with use_engine(...)` block, whatever the
process says, and no thread outside the block is affected (it is a context variable).

The server verifies a confirmed decision by reading the file AGAIN with the same engine, so the
understanding and the check can never disagree about which engine was in charge.
"""

import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache

from app.modules.data_sources.algorithmic.engine import CONFIGS, AlgorithmicEngine
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.proposal import Proposal, SelectionEngine
from app.modules.data_sources.proposal import propose as v3_propose
from app.modules.data_sources.semantics import DomainSem

ENV_NAME = "SMART_IMPORT_UNDERSTANDING_ENGINE"
V3 = "v3"
ENGINES = (V3, *CONFIGS)

_override: ContextVar[str | None] = ContextVar("smart_import_engine_override", default=None)
_configured: list[str] = []


def configure(name: str) -> None:
    """What the process runs (set by the app from its settings when it starts)."""
    _check(name)
    _configured[:] = [name]


def _check(name: str) -> str:
    if name not in ENGINES:
        raise ValueError(f"unknown understanding engine {name!r}: one of {', '.join(ENGINES)}")
    return name


def current_name() -> str:
    override = _override.get()
    if override is not None:
        return override
    if _configured:
        return _configured[0]
    return _check(os.environ.get(ENV_NAME, V3).strip().lower() or V3)


_instance: ContextVar[SelectionEngine | None] = ContextVar(
    "smart_import_engine_instance", default=None
)


@contextmanager
def use_engine_instance(engine: SelectionEngine) -> Iterator[None]:
    """Run the code inside the block with THIS engine object (to hand it a trace hook)."""
    token = _instance.set(engine)
    try:
        yield
    finally:
        _instance.reset(token)


@contextmanager
def use_engine(name: str) -> Iterator[None]:
    """Run the code inside the block with this engine (`v3`, `v4`, or the ablation `v4-header`)."""
    token = _override.set(_check(name))
    try:
        yield
    finally:
        _override.reset(token)


@cache
def _engine(name: str) -> SelectionEngine | None:
    return None if name == V3 else AlgorithmicEngine(CONFIGS[name])


def propose(
    sem: DomainSem,
    samples: Sequence[ColumnSample],
    *,
    excluded_reason: Callable[[str], str | None] = lambda _header: None,
) -> Proposal:
    """`proposal.propose` with the engine the process (or the enclosing `use_engine`) selects."""
    engine = _instance.get() or _engine(current_name())
    return v3_propose(sem, samples, excluded_reason=excluded_reason, engine=engine)


__all__ = [
    "ENGINES",
    "ENV_NAME",
    "V3",
    "configure",
    "current_name",
    "propose",
    "use_engine",
    "use_engine_instance",
]
