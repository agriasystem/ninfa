"""The recordings kept in the repository hold nothing but what a replay needs.

A recording of the real model is useful as a fixture - the benchmark can be recomputed with no key,
no network and no money - and dangerous as an archive: a vendor's request id identifies a call at
the vendor, and an answer could in principle hold a word of a file. These tests are the proof that
it does not, for every recording that is committed: keys are hashes of a request (not the request),
every string of every answer belongs to a closed vocabulary NINFA itself defines, nothing is shaped
like personal data, and no request id survives.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.modules.ai.import_understanding.interpretation import (
    AmbiguityKind,
    AmbiguityReading,
    AnswerReading,
    ColumnReading,
    HeaderAssessment,
    InterpretationStatus,
    Reason,
    SemanticInterpretation,
    Warning,
)
from app.modules.ai.import_understanding.types import NO_FIELD, UNKNOWN, Confidence
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR
from app.modules.document_understanding.personal_shapes import is_personal_value
from tests.benchmarks.smart_import_v3.openai_live import Recorded

RESULTS = Path(__file__).resolve().parent / "benchmarks" / "results"
FIXTURES = sorted(RESULTS.glob("smart-import-openai-*-recording.jsonl"))


def vocabulary() -> set[str]:
    words: set[str] = {NO_FIELD, UNKNOWN, "BOOKINGS", "COSTS", "LABOR", "DOMAIN"}
    for sem in (BOOKINGS, COSTS, LABOR):
        words |= set(sem.fields)
    for enum in (
        InterpretationStatus,
        Reason,
        HeaderAssessment,
        AmbiguityKind,
        Warning,
        Confidence,
    ):
        words |= {member.value for member in enum}
    return words


def contract_keys() -> set[str]:
    """The names of the fields of the closed answer (`semantic-v1`): nothing else is a key."""
    keys: set[str] = set()
    for model in (SemanticInterpretation, ColumnReading, AmbiguityReading, AnswerReading):
        keys |= set(model.model_fields)
    return keys


def walk(node: Any, keys: set[str], values: list[str]) -> None:
    """The keys and the string values of an answer, apart: a key must be a field of the contract,
    a value must belong to a closed vocabulary."""
    if isinstance(node, str):
        values.append(node)
    elif isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            walk(value, keys, values)
    elif isinstance(node, list):
        for item in node:
            walk(item, keys, values)


def test_the_recordings_are_there() -> None:
    assert FIXTURES, "no recording fixture is committed: the benchmark cannot be recomputed"


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_a_fixture_holds_hashes_closed_vocabularies_and_counts_only(fixture: Path) -> None:
    allowed = vocabulary()
    entries = [
        json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line
    ]

    assert entries
    for entry in entries:
        assert re.fullmatch(r"[0-9a-f]{64}", entry["key"])  # a hash, never the request
        assert set(entry) <= {"key", "ok", "payload", "usage", "attempt", "kind"}
        if entry["usage"] is not None:
            assert entry["usage"]["request_id"] is None  # the vendor's id never leaves the vendor
        keys: set[str] = set()
        values: list[str] = []
        walk(entry.get("payload"), keys, values)
        assert keys <= contract_keys(), keys - contract_keys()
        for text in values:
            assert not is_personal_value(text)
            assert text in allowed or re.fullmatch(r"Q\d+", text), text
    assert len({e["key"] for e in entries}) == len(entries)  # one answer per request, no more


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_a_fixture_replays_without_a_provider(fixture: Path) -> None:
    recorded = Recorded(None, fixture, frozen=True)

    assert recorded.entries  # it loads, and a replay needs nothing else
    assert all(
        entry["usage"] is None or entry["usage"]["request_id"] is None for entry in recorded.entries
    )
