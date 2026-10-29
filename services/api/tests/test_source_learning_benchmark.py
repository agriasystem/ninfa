"""The Source Learning benchmark is an instrument: it must be right when learning works, and it must
SAY SO when learning does not (a memory that is never used, a contradiction nobody notices).

A subset of the sources runs here (the full set is `python -m tests.benchmarks.source_learning`).
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.modules.data_sources import source_learning
from app.modules.data_sources import understanding as understanding_module
from tests.benchmarks.source_learning.families import FAMILIES, Expect, Family, versions
from tests.benchmarks.source_learning.report import markdown
from tests.benchmarks.source_learning.runner import run_benchmark

# a source the person answers about, one matched by hand, one the engine reads alone
SUBSET = ("L1-ore-a-b", "B2-cod", "X1-staff-clear")


def _subset() -> tuple[Family, ...]:
    return tuple(f for f in FAMILIES if f.id in SUBSET)


@pytest.fixture(scope="module")
def corpus() -> Iterator[tuple[Family, ...]]:
    yield _subset()


def test_the_sources_are_what_the_benchmark_says_they_are() -> None:
    assert len(FAMILIES) == 13
    assert sum(1 for f in FAMILIES if not f.control) == 11 and sum(f.control for f in FAMILIES) == 2
    assert {f.domain.value for f in FAMILIES} == {"LABOR", "BOOKINGS", "COSTS"}
    assert len(FAMILIES) * 8 >= 80  # at least 80 document versions
    assert len({f.id for f in FAMILIES}) == len(FAMILIES)


@pytest.mark.parametrize("family", FAMILIES, ids=lambda f: f.id)
def test_every_version_changes_exactly_what_it_says(family: Family) -> None:
    plan = versions(family)

    assert [v.key for v in plan] == [f"V{n}" for n in range(1, 9)]
    base = plan[0]
    assert [v.expect for v in plan] == [
        Expect.FIRST,
        Expect.EXACT,
        Expect.EXACT,
        Expect.COMPATIBLE,
        Expect.EXACT,
        Expect.COMPATIBLE,
        Expect.MISSING,
        Expect.CONFLICT,
    ]
    assert list(plan[1].columns) == list(base.columns)  # V2: the same columns
    assert sorted(plan[2].columns) == sorted(base.columns)  # V3: the same, moved
    assert list(plan[2].columns) != list(base.columns)
    assert len(plan[3].columns) == len(base.columns) + 1  # V4: a junk column
    assert len(plan[5].columns) == len(base.columns) + 1  # V6: a new column
    assert len(plan[6].columns) == len(base.columns) - 1  # V7: one gone
    assert len(plan[7].columns) == len(base.columns)  # V8: same columns, one means something else
    assert plan[7].columns[family.conflict] == "note"
    assert all(set(v.truth) <= set(v.columns) for v in plan)  # the truth names real columns


def test_when_learning_works_the_benchmark_says_so(
    db_session: Session, corpus: tuple[Family, ...]
) -> None:
    data = run_benchmark(db_session, corpus)

    assert data["failures"] == []
    assert data["document_versions"] == len(corpus) * 8
    assert data["exact_reuse_rate"]["value"] == 1.0
    assert data["compatible_reuse_rate"]["value"] == 1.0
    assert data["wrong_reuse_rate"]["num"] == 0
    assert data["false_automation_with_memory"] == 0
    assert data["cross_property_contamination"] == 0 and data["cross_domain_contamination"] == 0
    assert data["conflict_detection_recall"]["value"] == 1.0
    assert data["repeated_mapping_questions_on_unchanged_source"] == 0
    assert data["questions_saved"]["saved"] > 0
    assert data["performance_ms"]["match_source"]["max"] < 5.0  # macroscopic regressions only
    # the control source is read by the engine alone: nothing learned, nothing harmed
    control = next(r for r in data["per_family"] if r["family"] == "X1-staff-clear")
    assert control["control"] is True and control["wrong_reuse"] == 0
    report = markdown(data, "2026-10-27")
    assert "Source Learning - Benchmark V1" in report and "Every version" in report


def test_with_the_memory_switched_off_the_benchmark_notices_nothing_is_reused(
    db_session: Session, corpus: tuple[Family, ...]
) -> None:
    with patch.object(understanding_module, "reusable", lambda _memory, _match: False):
        data = run_benchmark(db_session, corpus)

    assert data["exact_reuse_rate"]["value"] == 0.0
    assert data["compatible_reuse_rate"]["value"] == 0.0
    assert data["questions_saved"]["saved"] == 0
    assert data["failures"]  # and it says which versions did not behave as expected


def test_with_the_value_checks_sabotaged_the_benchmark_catches_the_contradiction(
    db_session: Session, corpus: tuple[Family, ...]
) -> None:
    def never_disagrees(*_args: Any) -> None:
        return None

    with patch.object(source_learning, "_disagreement", never_disagrees):
        data = run_benchmark(db_session, corpus)

    assert data["conflict_detection_recall"]["value"] < 1.0  # the conflict is not seen
    caught = [f for f in data["failures"] if f["version"] == "V8"]
    assert caught  # ...and the benchmark names it
