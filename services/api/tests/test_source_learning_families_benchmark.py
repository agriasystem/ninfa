"""The multi-source extension of the Source Learning benchmark is an instrument: it must be right
when several families live side by side, and it must SAY SO when they do not (a source that keeps
only its last family, a lookalike taken for its twin, a guess where nothing can be told).

Each property runs here (the whole timeline, 40 steps); the three together are
`python -m tests.benchmarks.source_learning`.
"""

from collections.abc import Sequence
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
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.source_learning.multi import SCRIPT, SITES, Site, run_multi_family
from tests.benchmarks.source_learning.report import multi_markdown

# A short timeline for the sabotages: two families, a lookalike taught later, what could be either.
SHORT: tuple[tuple[str, str, str], ...] = (
    ("teach", "A", ""),
    ("see", "A", "V2"),
    ("teach", "B", ""),
    ("see", "B", "V2"),
    ("see", "A", "V2"),  # B -> A
    ("teach", "D", ""),  # the lookalike of A
    ("see", "A", "V2"),
    ("see", "D", "V2"),
    ("see", "A", "V5"),
    ("undecidable", "A", "base"),
    ("undecidable", "A", "both"),
)
LABOR = next(site for site in SITES if site.domain == DataSourceDomain.LABOR)
# (the names Smart Import's own modules call these by)
SMART_IMPORT = "app.modules.data_sources.smart_import"
UNDERSTANDING = "app.modules.data_sources.understanding"


def _timeline(script: Sequence[tuple[str, str, str]]) -> list[str]:
    """The families the property meets, in order (a family met twice in a row counts once)."""
    order: list[str] = []
    for kind, letter, _ in script:
        if kind in ("teach", "see") and (not order or order[-1] != letter):
            order.append(letter)
    return order


def _contains(order: list[str], pattern: str) -> bool:
    window = list(pattern)
    return any(order[i : i + len(window)] == window for i in range(len(order)))


# --- the instrument is what it says it is ---


def test_the_sources_are_what_the_benchmark_says_they_are() -> None:
    assert len(SITES) == 3
    assert {site.domain.value for site in SITES} == {"BOOKINGS", "LABOR", "COSTS"}
    ids = [f.id for site in SITES for f in site.families]
    assert len(ids) == len(set(ids)) == 12  # four families in each property, none shared
    for site in SITES:
        assert len(site.families) >= 3 and all(f.domain == site.domain for f in site.families)
        a, _, _, twin = site.families
        extra_a = site.apart[0]
        extra_twin = site.apart[1]
        assert extra_a in a.columns and extra_a not in twin.columns
        assert extra_twin in twin.columns and extra_twin not in a.columns
        assert set(a.columns) - {extra_a} == set(twin.columns) - {extra_twin}  # one column apart


def test_the_timeline_is_a_real_one() -> None:
    order = _timeline(SCRIPT)

    for pattern in ("AB", "BA", "ABAB", "ABCACB", "CB", "AD", "DA"):
        assert _contains(order, pattern), pattern
    assert [kind for kind, letter, _ in SCRIPT[:2]] == ["teach", "see"]  # A -> A
    kinds = {kind for kind, _, _ in SCRIPT}
    assert kinds == {"teach", "see", "undecidable", "import", "correct"}
    drift = [
        key for kind, letter, key in SCRIPT if kind == "see" and key in ("V3", "V4", "V5", "V6")
    ]
    assert len(drift) >= 8  # drifted files of the families, after others were taught


# --- when several families live side by side, the benchmark says so ---


@pytest.mark.parametrize("site", SITES, ids=lambda site: site.id)
def test_when_families_live_side_by_side_the_benchmark_says_so(
    db_session: Session, site: Site
) -> None:
    data = run_multi_family(db_session, (site,))

    assert data["failures"] == []
    assert data["families_per_property"] == 4 and data["families_in_memory"] == [4]
    assert data["returning_family_recognition"]["value"] == 1.0
    assert data["returning_family_recognition"]["den"] >= 20
    assert data["right_family_every_expected_step"]["value"] == 1.0
    assert data["cross_family_wrong_reuse"] == 0
    assert data["family_collision_false_match"]["num"] == 0
    assert data["family_collision_false_match"]["den"] == 5
    assert data["twin_confusions"] == 0
    assert data["repeated_questions_after_returning_source"] == 0
    assert data["correct_family_after_cosmetic_or_additive_drift"]["value"] == 1.0
    assert data["correct_family_after_cosmetic_or_additive_drift"]["den"] >= 12
    assert data["store_intact_after_import_or_correction"]["value"] == 1.0
    assert data["cross_property_contamination"] == 0 and data["cross_domain_contamination"] == 0
    assert data["every_step_as_expected"]["value"] == 1.0
    assert data["questions_saved"]["saved"] > 0
    assert data["questions_saved"]["documents_asking_nothing_without_memory"] == 0
    # nothing was lost on the way: the corrected family has a second revision, the others the first
    revisions = data["per_site"][0]["revisions"]
    assert sorted(revisions.values()) == [1, 1, 1, 2]


# --- and when they do not ---


def _one_slot(real: Any) -> Any:
    """The defect this extension exists for: the source remembers only the last family written."""

    def learn(*args: Any, **kwargs: Any) -> Learning | None:
        learning: Learning | None = real(*args, **kwargs)
        if learning is None:
            return None
        kept = [m for m in learning.families if m.id == learning.current]
        return learning.model_copy(update={"families": kept})

    return learn


def test_if_the_source_kept_only_its_last_family_the_benchmark_notices(db_session: Session) -> None:
    with patch(f"{SMART_IMPORT}.learn", _one_slot(source_learning.remember_in)):
        data = run_multi_family(db_session, (LABOR,), script=SHORT)

    assert data["returning_family_recognition"]["value"] < 1.0
    assert data["right_family_every_expected_step"]["value"] < 1.0
    assert data["failures"]  # and it names which steps
    assert any(f["kind"] == "see" and f["family"] == "M2-turni" for f in data["failures"])


def _guess(real: Any) -> Any:
    """Never leave a file undecided: take the family that explains it best, tie or not."""

    def choose(
        learning: Learning | None, columns: Sequence[Any], matcher: Any = match_source
    ) -> FamilyChoice:
        choice: FamilyChoice = real(learning, columns, matcher)
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


def test_if_an_undecided_file_were_settled_by_a_guess_the_benchmark_notices(
    db_session: Session,
) -> None:
    with patch(f"{UNDERSTANDING}.choose_family", _guess(source_learning.choose_family)):
        data = run_multi_family(db_session, (LABOR,), script=SHORT)

    assert data["family_collision_false_match"]["num"] > 0
    assert any(f["kind"] == "undecidable" for f in data["failures"])


def test_if_every_new_structure_were_a_revision_the_twin_would_overwrite_the_first_family(
    db_session: Session,
) -> None:
    with patch.object(source_learning, "is_revision", lambda _match: True):
        data = run_multi_family(db_session, (LABOR,), script=SHORT)

    assert data["failures"]
    assert data["families_in_memory"] == [2]  # the twin took the first family's place
    assert data["returning_family_recognition"]["value"] < 1.0 or data["twin_confusions"] > 0


# --- the report ---


def test_the_report_names_every_measure_and_every_step(db_session: Session) -> None:
    data = run_multi_family(db_session, (LABOR,), script=SHORT)

    text = multi_markdown(data)

    assert "Several sources in one property" in text and "Every step" in text
    for measure in (
        "Returning-family recognition",
        "Cross-family wrong reuse",
        "Family-collision false match",
        "Repeated questions after a returning source",
        "Correct family after cosmetic / additive drift",
    ):
        assert measure in text
    assert text.count("| labor |") == len(data["steps"])
    assert "NOT OK" not in text
