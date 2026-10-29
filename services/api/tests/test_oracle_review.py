"""The review of the questions the scorer called unnecessary (Universal Understanding 2.1).

A tolerance in a golden is only honest if it is not dead weight and if the decision it relies on is
really written down: every reviewed question is really asked by Smart Import, every document and
every test it cites exists, and a gap nobody can justify (`L62`) was not reviewed away.
"""

from pathlib import Path

import pytest

from tests.benchmarks.smart_import_v3.corpus import build_corpus
from tests.benchmarks.smart_import_v3.observe import make_service, run
from tests.benchmarks.smart_import_v3.oracle_review import REVIEWS, Review

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
DOCS = {doc.id.split("_", 1)[0]: doc for doc in build_corpus()}
CASES = [(prefix, review) for prefix, reviews in REVIEWS.items() for review in reviews]


@pytest.mark.parametrize(("prefix", "review"), CASES, ids=[f"{p}-{r.kind}" for p, r in CASES])
def test_a_reviewed_question_is_really_asked(prefix: str, review: Review) -> None:
    document = DOCS[prefix]

    seen = run(make_service(), document.card, document.filename, document.content)

    assert review.kind in {q.kind for q in seen.questions}
    assert review.kind in document.golden.tolerated
    assert review.kind not in document.golden.questions  # (tolerated, never made necessary)


@pytest.mark.parametrize(("prefix", "review"), CASES, ids=[f"{p}-{r.kind}" for p, r in CASES])
def test_the_decision_behind_it_is_written_down(prefix: str, review: Review) -> None:
    assert review.pinned_by and review.why
    for path in review.pinned_by:
        assert (REPO / path).is_file(), path
    for pin in review.tests:
        file, name = pin.split("::")
        assert f"def {name}(" in (TESTS / file).read_text(encoding="utf-8"), pin


def test_a_gap_is_not_reviewed_away() -> None:
    # `L62`: the department column holds people, and the question asked is the wrong one
    assert "L62" not in REVIEWS
    assert all(len(reviews) >= 1 for reviews in REVIEWS.values())
