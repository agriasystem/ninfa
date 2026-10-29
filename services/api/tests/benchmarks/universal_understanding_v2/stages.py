"""Where the time goes: scan of the workbook, semantic mapping of the columns, and the rest.

A call of Smart Import is measured as a whole (as the main benchmark does) and, in the same call,
the time spent in the two stages the product's cost is made of: reading the workbook into cells
(`scan_workbook`) and deciding what each column means (`propose`). What is left is the rest of
the understanding: finding the tables, the header, the kind of data, the questions.

The two functions are wrapped for the length of the measurement only; nothing else is touched.
"""

import statistics
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from unittest.mock import patch

from app.modules.data_sources import understanding as engine
from app.modules.data_sources.proposal import propose
from app.modules.document_understanding.grid import scan_workbook
from tests.benchmarks.smart_import_v3.metrics import performance
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.smart_import_v3.observe import make_service, run


@dataclass(slots=True)
class StageTimes:
    scan_ms: float = 0.0
    mapping_ms: float = 0.0
    total_ms: float = 0.0

    @property
    def understanding_ms(self) -> float:
        return max(0.0, self.total_ms - self.scan_ms - self.mapping_ms)


@dataclass(slots=True)
class _Clock:
    scan: float = 0.0
    mapping: float = 0.0


def _timed(function: Any, add: Any) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            add((perf_counter() - started) * 1000)

    return wrapper


@contextmanager
def _clock() -> Iterator[_Clock]:
    clock = _Clock()

    def add_scan(ms: float) -> None:
        clock.scan += ms

    def add_mapping(ms: float) -> None:
        clock.mapping += ms

    with (
        patch.object(engine, "scan_workbook", _timed(scan_workbook, add_scan)),
        patch.object(engine, "propose", _timed(propose, add_mapping)),
    ):
        yield clock


def measure(docs: list[Doc], *, repeats: int = 3) -> dict[str, StageTimes]:
    """Median of `repeats` calls per document, per stage."""
    service = make_service()
    warm = docs[0]
    run(service, warm.card, warm.filename, warm.content)
    out: dict[str, StageTimes] = {}
    for doc in docs:
        samples: list[StageTimes] = []
        for _ in range(repeats):
            with _clock() as clock:
                observed = run(service, doc.card, doc.filename, doc.content)
            samples.append(StageTimes(clock.scan, clock.mapping, observed.elapsed_ms))
        out[doc.id] = StageTimes(
            statistics.median(s.scan_ms for s in samples),
            statistics.median(s.mapping_ms for s in samples),
            statistics.median(s.total_ms for s in samples),
        )
    return out


def summarise(times: dict[str, StageTimes]) -> dict[str, dict[str, float]]:
    values = list(times.values())
    return {
        "scan_ms": performance([t.scan_ms for t in values]),
        "understanding_ms": performance([t.understanding_ms for t in values]),
        "mapping_ms": performance([t.mapping_ms for t in values]),
        "total_ms": performance([t.total_ms for t in values]),
    }
