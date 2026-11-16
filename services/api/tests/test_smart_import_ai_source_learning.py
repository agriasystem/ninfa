"""A source a person already confirmed is not read by a model again (V1.1).

The authority is, in this order: NINFA's safety, what a PERSON confirmed (Source Learning), the
deterministic reading, a model's candidate, a question. A model sits fourth: it may help the FIRST
time a source is hard, and it must not be paid for - in money, in seconds, in a changed answer -
every time the same source comes back.

Real families through the real services and the real database (rolled back): a source is taught at
V1 (the person decides, the import remembers it), then its next files arrive - next month, columns
moved, a junk column, cosmetic headers, a new column - and a counting stand-in for the model reads
every column right. What is measured is only the one thing the model costs: how many times it was
asked.
"""

import pytest
from sqlalchemy.orm import Session

from tests.benchmarks.source_learning.ai_calls import RECOGNISED, TRUSTED, calls_per_version
from tests.benchmarks.source_learning.families import Family


@pytest.mark.parametrize("family", TRUSTED, ids=[f.id for f in TRUSTED])
def test_a_recognised_source_never_asks_a_model_again(db_session: Session, family: Family) -> None:
    _first, calls = calls_per_version(db_session, family)

    for key, (expect, learned, _cold) in calls.items():
        if expect in RECOGNISED:
            assert learned == 0, f"{family.id} {key}: a recognised source asked the model"


def test_remembering_a_source_costs_the_model_less_than_not_remembering_it(
    db_session: Session,
) -> None:
    learned = cold = 0
    for family in TRUSTED:
        _first, calls = calls_per_version(db_session, family)
        for _expect, with_memory, without in calls.values():
            learned += with_memory
            cold += without

    assert learned < cold
