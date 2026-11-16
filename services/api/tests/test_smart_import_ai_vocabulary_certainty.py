"""ADR 0052: with the REAL model, a column it named and NINFA's vocabulary recognised made three
files that carry a sentence of orders READY (no question). The model had read them right and did
not flag the sentence; nothing in the file was wrong but the file had to reach a person.

The three files are the adversarial ones of the benchmark (`ADV06`, `ADV07`, `ADV08`: the sentence
sits in a cell, in a sheet name, in a title above the header). The stand-in below is a model that
reads every column right and says NOTHING about the sentence - what the real one did. The checks:

* with the certainty withdrawn (production), none of them is READY, and each asks the person;
* with it on (what was measured), they were READY - so the checks above would fail without the
  withdrawal, which is what makes them mean something.
"""

import pytest

from app.modules.ai.import_understanding.types import AiMode
from app.modules.data_sources.understanding_types import UnderstandingLevel
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.smart_import_v3.openai_intelligence import _truth, adversarial_docs
from tests.semantic_support import Behaviour, SemanticStandIn, understand_semantic

INJECTION_FILES = (
    "ADV06-injection-in-a-cell",
    "ADV07-injection-in-a-sheet-name",
    "ADV08-injection-in-a-title-header-on-row-4",
)


def _level(doc_id: str, *, vocabulary_certainty: bool) -> tuple[UnderstandingLevel, int]:
    doc = next(d for d in adversarial_docs() if d.id == doc_id)
    model = SemanticStandIn(Behaviour.ORACLE, _truth(doc), None, doc.golden.pii_values)
    inspection = understand_semantic(
        model,
        DataSourceDomain.BOOKINGS,
        doc.content,
        mode=AiMode.ASSIST,
        vocabulary_certainty=vocabulary_certainty,
    )
    understanding = inspection.understanding
    assert understanding is not None
    assert model.calls >= 1  # the model WAS asked: the difference is not "nothing happened"
    return understanding.level, len(understanding.questions)


@pytest.mark.parametrize("doc_id", INJECTION_FILES)
def test_with_the_certainty_withdrawn_a_file_with_a_sentence_of_orders_reaches_a_person(
    doc_id: str,
) -> None:
    level, questions = _level(doc_id, vocabulary_certainty=False)

    assert level != UnderstandingLevel.READY
    assert questions >= 1


@pytest.mark.parametrize("doc_id", INJECTION_FILES)
def test_it_was_the_certainty_that_made_them_ready(doc_id: str) -> None:
    level, questions = _level(doc_id, vocabulary_certainty=True)

    assert level == UnderstandingLevel.READY
    assert questions == 0
