"""Universal Understanding 2 does not undo Source Learning.

The primary Universal Understanding Benchmark V2 reads every file as a FIRST upload: no learned
profile helps. This is the secondary check: a V2 document that needed a question is answered once,
imported (which remembers what the person confirmed) and then uploaded again as "the next file of
the same source" - it is recognised and the question is not asked again. Real bytes, the real API
and database (rolled back); no model.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.universal_understanding_v2.corpus import build_corpus
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import import_mapped, understand
from tests.support import BookingFactory

DOMAIN_OF = {"bookings": "BOOKINGS", "labor": "LABOR", "costs": "COSTS"}
HOW_MANY = 3  # documents tried per kind of data
PLAIN = {"COLUMN_MEANING", "VALUE_LABELS", "AMOUNT_BASIS", "DATE_ORDER", "DECIMAL_STYLE"}


def _teachable() -> list[Doc]:
    """Documents of V2 the system answers with a plain question the truth can answer: not a choice
    of table, not a department no file states (those are tested in the Source Learning suites)."""
    chosen: list[Doc] = []
    for group in DOMAIN_OF:
        chosen.extend(
            [
                doc
                for doc in build_corpus((group,))
                if doc.golden.outcome == "ASK"
                and doc.golden.answers
                and set(doc.golden.questions) <= PLAIN
                and not doc.filename.endswith(".csv")
            ][:HOW_MANY]
        )
    return chosen


TEACHABLE = _teachable()


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def test_every_kind_of_data_has_documents_to_teach() -> None:
    assert {doc.card for doc in TEACHABLE} == set(DOMAIN_OF)


@pytest.mark.parametrize("doc", TEACHABLE, ids=[doc.id for doc in TEACHABLE])
def test_what_the_person_answered_once_is_not_asked_again(
    doc: Doc, api_client: TestClient, env: SourcesEnv
) -> None:
    domain = DOMAIN_OF[doc.card]

    first = understand(api_client, env, domain, doc.filename, doc.content)
    assert first["understanding"]["questions"]

    answers: dict[str, Any] = dict(doc.golden.answers)
    answered = understand(api_client, env, domain, doc.filename, doc.content, answers)
    assert answered["understanding"]["level"] == "READY"
    done = import_mapped(
        api_client,
        env,
        domain,
        doc.filename,
        doc.content,
        answered["proposal"],
        snapshot="2026-10-30",
    )
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text

    again = understand(api_client, env, domain, "next-month-" + doc.filename, doc.content)
    assert again["understanding"]["level"] == "READY"
    assert again["understanding"]["questions"] == []
