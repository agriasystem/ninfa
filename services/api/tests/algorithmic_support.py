"""Helpers shared by the Smart Import V4 (algorithmic understanding) tests.

Free functions, no fixtures (as the other test support modules): a column sample built by hand, a
proposal read with an explicit engine, and generators of the values a hotel's columns really hold.
"""

import random
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from app.modules.data_sources.algorithmic.engine import (
    DEFAULT,
    AlgorithmicConfig,
    AlgorithmicEngine,
)
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.proposal import Proposal, propose
from app.modules.data_sources.semantics import DomainSem


def sample(position: int, header: str, values: Sequence[Any]) -> ColumnSample:
    """A column as the reader hands it over: every cell kept in `rows` (an empty one as None)."""
    cells = tuple(v for v in values if v is not None)
    return ColumnSample(
        position, header, tuple(str(v) for v in cells[:3]), cells, rows=tuple(values)
    )


def table(columns: Mapping[str, Any]) -> list[ColumnSample]:
    return [sample(i, header, values) for i, (header, values) in enumerate(columns.items())]


def read(
    sem: DomainSem,
    columns: Mapping[str, Any],
    config: AlgorithmicConfig | None = DEFAULT,
) -> Proposal:
    """The proposal of a table, read by V4 (`config`) or by V3 (None)."""
    engine = AlgorithmicEngine(config) if config is not None else None
    return propose(sem, table(columns), engine=engine)


def fields_of(proposal: Proposal) -> dict[str, str | None]:
    return {c.header: c.field for c in proposal.columns}


def levels_of(proposal: Proposal) -> dict[str, str | None]:
    return {c.header: c.level.value if c.level else None for c in proposal.columns}


# --- the values of a hotel's columns --------------------------------------------------------------


def codes(n: int = 12, prefix: str = "BK") -> list[str]:
    return [f"{prefix}{100200 + i * 17}" for i in range(n)]


def stay(n: int = 12, seed: int = 3) -> tuple[list[date], list[date], list[date]]:
    """(booked, arrival, departure) per booking: booked on or before arrival, a short stay."""
    rng = random.Random(seed)
    booked, arrival, departure = [], [], []
    for _ in range(n):
        b = date(2026, 9, 1) + timedelta(days=rng.randint(0, 40))
        a = b + timedelta(days=rng.randint(3, 60))
        booked.append(b)
        arrival.append(a)
        departure.append(a + timedelta(days=rng.randint(1, 7)))
    return booked, arrival, departure


STATUSES = ["Confirmed", "Cancelled", "Confirmed", "No show", "Confirmed", "Checked in"] * 2
CHANNELS = ["Booking.com", "Expedia", "Direct", "Booking.com", "Phone", "Website"] * 2
DEPARTMENTS = ["Reception", "Housekeeping", "Cucina", "Sala", "Bar", "Manutenzione"] * 2
MONEY = [round(80 + 37.5 * (i % 9), 2) for i in range(12)]
ROOMS = [1, 1, 2, 1, 1, 1, 2, 1, 1, 1, 1, 2]
