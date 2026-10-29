"""Universal Understanding 2 does not undo Source Learning.

The primary Universal Understanding Benchmark V2 reads every file as a FIRST upload: no learned
profile helps. This is the secondary check: a V2 document that needed a question is answered once
(with the answers its truth lists, the way the benchmark's conversation gives them), imported
(which remembers what the person confirmed) and then uploaded again as "the next file of the same
source" - it is recognised and the question is not asked again. Real bytes, the real API and
database (rolled back); no model.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.modules.data_sources.understanding import UnderstandAnswers
from tests.benchmarks.smart_import_v3.dialog import MAX_ROUNDS, _answer
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.smart_import_v3.observe import make_service, run
from tests.benchmarks.universal_understanding_v2.corpus import build_corpus
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import import_mapped, understand
from tests.support import BookingFactory

DOMAIN_OF = {"bookings": "BOOKINGS", "labor": "LABOR", "costs": "COSTS"}
HOW_MANY = 3  # documents tried per kind of data


def _answers_of(doc: Doc) -> dict[str, Any] | None:
    """The answers a careful person gives (as the benchmark's conversation does) until Smart
    Import stops asking - or None when the truth has no answer for one of its questions."""
    service = make_service()
    state = run(service, doc.card, doc.filename, doc.content)
    given: dict[str, Any] = {}
    for _ in range(MAX_ROUNDS):
        if state.automatic or state.error or not state.questions:
            break
        if not any([_answer(q, doc.golden, state, given) for q in state.questions]):
            return None
        state = run(
            service, doc.card, doc.filename, doc.content, answers=UnderstandAnswers(**given)
        )
    return given if state.automatic and given and "period_start" not in given else None


def _teachable() -> list[tuple[Doc, dict[str, Any]]]:
    """V2 documents that ask, and that the truth can answer completely."""
    chosen: list[tuple[Doc, dict[str, Any]]] = []
    for group in DOMAIN_OF:
        found = 0
        for doc in build_corpus((group,)):
            if doc.golden.outcome != "ASK" or doc.filename.endswith(".csv"):
                continue
            if "TABLE" in doc.golden.questions:
                continue  # (which of two tables is not a fact a family remembers: as before)
            answers = _answers_of(doc)
            if answers is not None:
                chosen.append((doc, answers))
                found += 1
            if found == HOW_MANY:
                break
    return chosen


TEACHABLE = _teachable()


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def test_every_kind_of_data_has_documents_to_teach() -> None:
    assert {doc.card for doc, _answers in TEACHABLE} == set(DOMAIN_OF)


@pytest.mark.parametrize(("doc", "answers"), TEACHABLE, ids=[doc.id for doc, _answers in TEACHABLE])
def test_what_the_person_answered_once_is_not_asked_again(
    doc: Doc, answers: dict[str, Any], api_client: TestClient, env: SourcesEnv
) -> None:
    domain = DOMAIN_OF[doc.card]

    first = understand(api_client, env, domain, doc.filename, doc.content)
    assert first["understanding"]["questions"]

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
