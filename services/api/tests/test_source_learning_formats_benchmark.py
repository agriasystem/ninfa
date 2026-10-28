"""The multi-format extension of the Source Learning benchmark is an instrument: it must be right
when every family is read the way it was taught, and it must SAY SO when one is read with the layout
of whichever family was imported last (a sheet that is not there, a grid that is not a grid, a
department added to a table that has its own).

Each property runs here (the whole timeline); the three together are
`python -m tests.benchmarks.source_learning`.
"""

from collections.abc import Callable, Sequence
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.modules.data_sources import source_learning
from app.modules.data_sources.source_learning import (
    FamilyChoice,
    Learning,
    Memory,
    SourceMatch,
    is_revision,
    match_source,
    residual,
)
from app.modules.data_sources.understanding import UnderstandingService
from app.modules.document_understanding.layout import LayoutSpec
from tests.benchmarks.source_learning.formats import (
    FORMATS,
    SITES,
    Site,
    run_formats,
)
from tests.benchmarks.source_learning.report import formats_markdown

UNDERSTANDING = "app.modules.data_sources.understanding"


def _order(site: Site) -> list[str]:
    """The formats the property meets, in order (a format met twice in a row counts once)."""
    order: list[str] = []
    for kind, key, _ in site.script:
        if kind in ("teach", "see") and (not order or order[-1] != key):
            order.append(key)
    return order


def _contains(order: list[str], pattern: Sequence[str]) -> bool:
    window = list(pattern)
    return any(order[i : i + len(window)] == window for i in range(len(order)))


def _site(site_id: str) -> Site:
    return next(site for site in SITES if site.id == site_id)


# --- the instrument is what it says it is ---


def test_the_formats_are_what_the_benchmark_says_they_are() -> None:
    assert len(SITES) == 3
    assert {site.domain.value for site in SITES} == {"BOOKINGS", "LABOR"}
    bookings = _site("bookings")
    assert len(bookings.formats) >= 3 and {FORMATS[f].kind for f in bookings.formats} >= {
        "xlsx",
        "csv",
    }
    labor = _site("labor")
    assert {FORMATS[f].kind for f in labor.formats} >= {"grid", "title", "table", "table-csv"}
    layouts = [FORMATS[f].layout for f in bookings.formats]
    assert {"sheets": ["Prenotazioni"]} in layouts and {"sheets": ["Export"]} in layouts
    assert FORMATS["F-grid"].layout == {"grid": {"hours_field": "planned_hours"}}
    assert FORMATS["F-title"].layout == {"department": {"kind": "TITLE"}}


def test_the_timelines_are_real_ones() -> None:
    pms, export, csv = "F-pms", "F-export", "F-csv"
    bookings = _order(_site("bookings"))
    for pattern in (
        (pms, export, pms),  # A -> B -> A
        (pms, export, pms, export),  # A -> B -> A -> B
        (pms, csv, pms, csv),  # A -> C -> A -> C
        (pms, export, csv, pms, export),  # A -> B -> C -> A -> B
    ):
        assert _contains(bookings, pattern), pattern
    labor = _order(_site("labor"))
    grid, table, title = "F-grid", "F-table", "F-title"
    for pattern in ((grid, table, grid), (title, table, title)):  # SPECIAL -> NORMAL -> SPECIAL
        assert _contains(labor, pattern), pattern


# --- when every family is read as it was taught, the benchmark says so ---


@pytest.mark.parametrize("site", SITES, ids=lambda site: site.id)
def test_when_every_family_is_read_as_taught_the_benchmark_says_so(
    db_session: Session, site: Site
) -> None:
    data = run_formats(db_session, (site,))

    assert data["failures"] == []
    assert data["correct_family"]["value"] == 1.0 and data["correct_family"]["den"] >= 5
    assert data["correct_family_layout"]["value"] == 1.0
    assert data["wrong_layout_reuse"] == 0
    assert data["cross_family_layout_contamination"] == 0
    assert data["documents_that_could_not_be_read"] == 0
    assert data["repeated_mapping_questions_on_returning_unchanged"] == 0
    assert data["returning_family_recognition"]["value"] == 1.0
    assert data["returning_family_recognition"]["den"] >= 2
    assert data["recognised_after_harmless_drift"]["value"] == 1.0
    assert data["ambiguous_layout_reuse"] == 0 and data["ambiguous_family_reuse"] == 0
    assert data["store_intact_after_import"]["value"] == 1.0 or site.id == "twins"
    assert data["every_step_as_expected"]["value"] == 1.0


def test_the_lookalikes_that_need_other_sheets_are_told_from_what_could_be_either(
    db_session: Session,
) -> None:
    data = run_formats(db_session, (_site("twins"),))

    either = [row for row in data["steps"] if row["kind"] == "either"]
    assert len(either) == 3
    assert all(row["ambiguous"] and row["read_as"] == {} and row["ok"] for row in either)
    assert data["ambiguous_layout_reuse"] == 0


# --- and when a family is read with the layout of the last import, it does not ---


def _as_it_was() -> Any:
    """The defect this extension exists for: the layout of the LAST import decides how every
    document is read, and no family lends its own."""
    holder: dict[str, LayoutSpec | None] = {}
    saved = UnderstandingService._saved
    base = UnderstandingService._base_layout

    def remember_last(
        self: UnderstandingService, adapter: Any, source: Any
    ) -> tuple[Any, LayoutSpec | None]:
        config, layout = saved(self, adapter, source)
        holder["layout"] = layout
        return config, layout

    def with_last(answers: Any, from_family: LayoutSpec | None) -> LayoutSpec:
        return base(answers, from_family or holder.get("layout"))

    def nobody_lends(*_args: Any) -> None:
        return None

    return (
        patch.object(UnderstandingService, "_saved", remember_last),
        patch.object(UnderstandingService, "_base_layout", staticmethod(with_last)),
        patch.object(UnderstandingService, "_hints", staticmethod(nobody_lends)),
    )


def test_if_the_layout_of_the_last_import_decided_the_benchmark_notices(
    db_session: Session,
) -> None:
    first, second, third = _as_it_was()
    with first, second, third:
        data = run_formats(db_session, (_site("bookings"),))

    assert data["documents_that_could_not_be_read"] > 0  # a sheet that is not in the file
    assert data["correct_family_layout"]["value"] < 1.0
    assert data["failures"]
    assert any(f["kind"] == "teach" for f in data["failures"])  # a csv cannot even be taught


def test_if_the_grid_of_the_last_import_were_lent_to_every_staff_file_the_benchmark_notices(
    db_session: Session,
) -> None:
    first, second, third = _as_it_was()
    with first, second, third:
        data = run_formats(db_session, (_site("labor"),))

    assert data["failures"]
    assert (
        data["repeated_mapping_questions_on_returning_unchanged"] > 0
        or data["wrong_layout_reuse"] > 0
    )  # the grid hours asked again, or a table read with the layout of a title


def _guess(real: Callable[..., FamilyChoice]) -> Callable[..., FamilyChoice]:
    """Never leave a file undecided: take the family that explains it best, tie or not."""

    def choose(
        learning: Learning | None, columns: Sequence[Any], matcher: Any = match_source
    ) -> FamilyChoice:
        choice = real(learning, columns, matcher)
        if not choice.ambiguous or learning is None:
            return choice
        scored: list[tuple[Memory, SourceMatch]] = [
            (m, matcher(m, columns)) for m in learning.families
        ]
        memory, match = min(scored, key=lambda p: (residual(p[1]), -p[1].score))
        return FamilyChoice(
            memory, match, choice.known, choice.eligible, False, choice.rival,
            revision=is_revision(match),
        )  # fmt: skip

    return choose


def test_if_a_file_that_could_be_either_were_settled_by_a_guess_the_benchmark_notices(
    db_session: Session,
) -> None:
    with patch(f"{UNDERSTANDING}.choose_family", _guess(source_learning.choose_family)):
        data = run_formats(db_session, (_site("twins"),))

    assert data["ambiguous_family_reuse"] > 0  # a family was reused for what could be either
    assert any(f["kind"] == "either" for f in data["failures"])


# --- the report ---


def test_the_report_names_every_measure_and_every_step(db_session: Session) -> None:
    data = run_formats(db_session, (_site("labor"),))

    text = formats_markdown(data)

    assert "Several formats in one source" in text and "Every step" in text
    for measure in (
        "Correct family",
        "Correct layout",
        "Wrong layout reuse",
        "Cross-family layout contamination",
        "Repeated mapping questions on a returning family",
    ):
        assert measure in text
    assert text.count("| labor |") == len(data["steps"])
    assert "NOT OK" not in text
