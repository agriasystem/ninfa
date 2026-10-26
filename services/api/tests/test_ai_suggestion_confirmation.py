"""A suggestion is a question to the person, never a decision - enforced by the SERVER (PB-3).

The AI readiness benchmark found documents on which a WRONG model, passing every value check, gets a
suggestion accepted at MEDIUM with a question open:

* L12 (staff): the real date column has an unreadable header ("Colonna 9") and the model says that
  "Ultima modifica" - a "last modified" date, a decoy - is the work date;
* BO05 (bookings): the real reservation code is unreadable and the model says that "KPI" is;

and the same shape exists without any model: B41 has a bare "Total" that NINFA reads as the room
revenue "to be checked" and asks about (`CONFIRM:Total`).

The invariant (server-side workflow integrity, not authentication): the decision NINFA issues for a
file carries the reference of the understanding it came from (`smart_import`: the answers it was
made with). Before a decision with that reference is judged or imported, the server reads the file
AGAIN with those answers - without any model - and accepts it only if that reading is READY and
gives exactly this mapping. So an open question cannot be skipped by posting the proposal again, by
copying the suggested matching, or by declaring it confirmed; the only way through is to ANSWER,
and the server checks the answer. The same for a suggestion of a model and one of the rules.

A matching the person builds by hand (Smart Import V2, no reference) is the manual contract and is
judged on its merits, as it always was.

No live model: a stand-in provider. The database is the real one (rolled back).
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from tests.benchmarks.smart_import_v3.ai_readiness import PlausibleWrong, variants
from tests.benchmarks.smart_import_v3.corpus import build_corpus
from tests.benchmarks.smart_import_v3.model import Doc
from tests.data_sources_support import SourcesEnv, sources_env
from tests.decision_api_support import assert_error
from tests.smart_import_support import dry_run, import_mapped, understand, validation, writes
from tests.support import BookingFactory

# case -> (domain, the decoy header, the field it is suggested as, the unreadable header, the field
#          it really is). The deterministic case has no model and no unreadable header.
AI_CASES = {
    "L12": ("LABOR", "Ultima modifica", "work_date", "Colonna 9", "work_date"),
    "BO05": ("BOOKINGS", "KPI", "source_record_id", "Colonna 9", "source_record_id"),
}
UNRESOLVED = "UNRESOLVED_IMPORT_QUESTIONS"


@pytest.fixture(scope="module")
def docs() -> dict[str, Doc]:
    corpus = build_corpus()
    out: dict[str, Doc] = {}
    for case, prefix in (("L12", "L12_"), ("BO05", "BO05_")):
        source = next(d for d in corpus if d.id.startswith(prefix))
        (out[case],) = variants([source])
    out["B41"] = next(d for d in corpus if d.id.startswith("B41_"))
    return out


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _row_counts(db_session: Session) -> dict[str, int]:
    """Every row of every table: if anything is written anywhere, this moves."""
    return {
        table.name: int(db_session.scalar(select(func.count()).select_from(table)) or 0)
        for table in Base.metadata.sorted_tables
    }


def _model(api_client: TestClient, doc: Doc | None) -> PlausibleWrong | None:
    """Switch the wrong stand-in model on for this file (or no model at all)."""
    model = None if doc is None else PlausibleWrong(doc.golden)
    api_client.app.state.import_understanding_resolver = ImportUnderstandingResolver(model)  # type: ignore[attr-defined]
    return model


def _open_decision(
    api_client: TestClient, env: SourcesEnv, domain: str, doc: Doc, *, with_model: bool
) -> dict[str, Any]:
    """The decision the server issues for a file whose question is still open."""
    _model(api_client, doc if with_model else None)
    body = understand(api_client, env, domain, doc.filename, doc.content)
    assert body["understanding"]["level"] != "READY", "the decision must still be open"
    assert body["proposal"]["smart_import"] is not None  # the server issued it with its reference
    proposal: dict[str, Any] = body["proposal"]
    return proposal


# --- while a question is open: MEDIUM, not automatic, nothing written ---


@pytest.mark.parametrize("case", list(AI_CASES))
def test_an_open_question_keeps_a_wrong_suggestion_medium_not_automatic_and_unwritten(
    api_client: TestClient, env: SourcesEnv, db_session: Session, docs: dict[str, Doc], case: str
) -> None:
    domain, decoy, field, *_ = AI_CASES[case]
    doc = docs[case]
    model = _model(api_client, doc)
    assert model is not None
    rows_before, writes_before = _row_counts(db_session), writes(db_session, env)

    body = understand(api_client, env, domain, doc.filename, doc.content)

    u = body["understanding"]
    suggestions = [r for r in u["recognized"] if r["origin"]["kind"] == "ASSISTANT"]
    assert [(s["origin"]["detail"], s["field"], s["level"]) for s in suggestions] == [
        (decoy, field, "MEDIUM")
    ]
    question = next(q for q in u["questions"] if q["id"] == f"CONFIRM:{decoy}")
    assert question["kind"] == "COLUMN_MEANING" and question["candidate"] == field
    assert u["level"] == "ASK"
    automatic = u["level"] == "READY" and not u["questions"] and not u["blockers"]
    assert automatic is False
    assert writes(db_session, env) == writes_before and _row_counts(db_session) == rows_before
    assert len(model.requests) == 1 and model.violations == []


# --- A, B, C: posting the proposal again is refused, and nothing is written ---


@pytest.mark.parametrize("case", ["L12", "BO05", "B41"])
def test_posting_the_proposal_of_an_open_decision_is_refused_by_both_endpoints_and_writes_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session, docs: dict[str, Doc], case: str
) -> None:
    domain = AI_CASES[case][0] if case in AI_CASES else "BOOKINGS"
    doc = docs[case]
    proposal = _open_decision(api_client, env, domain, doc, with_model=case in AI_CASES)
    rows_before = _row_counts(db_session)

    judged = dry_run(api_client, env, domain, doc.filename, doc.content, proposal)
    imported = import_mapped(api_client, env, domain, doc.filename, doc.content, proposal)

    assert_error(judged, status_code=409, code=UNRESOLVED)
    assert_error(imported, status_code=409, code=UNRESOLVED)
    assert _row_counts(db_session) == rows_before  # not a source, a job, a file or a row
    details = imported.json()["error"]["details"]
    assert details["level"] in {"ASK", "BLOCKED", "MANUAL"}
    if case == "B41":  # the deterministic suggestion is the same kind of open question
        assert details["questions"] == ["CONFIRM:Total"]


# --- a client cannot declare a question resolved ---


def test_a_client_cannot_turn_ask_into_ready_by_saying_so(
    api_client: TestClient, env: SourcesEnv, db_session: Session, docs: dict[str, Doc]
) -> None:
    doc = docs["B41"]
    open_decision = _open_decision(api_client, env, "BOOKINGS", doc, with_model=False)
    rows_before = _row_counts(db_session)

    # every way of claiming it: the reference emptied, a "confirmed" flag, other answers invented
    for forged in (
        {**open_decision, "smart_import": {"answers": {}, "confirmed_domain": False}},
        {
            **open_decision,
            "smart_import": {"answers": {"column_fields": {}}, "confirmed_domain": True},
        },
        {**open_decision, "smart_import": {"answers": {"sheet_name": "Foglio1"}}},
    ):
        response = import_mapped(api_client, env, "BOOKINGS", doc.filename, doc.content, forged)
        assert_error(response, status_code=409, code=UNRESOLVED)

    assert _row_counts(db_session) == rows_before


def test_a_reference_with_answers_that_are_not_answers_is_an_invalid_request(
    api_client: TestClient, env: SourcesEnv, docs: dict[str, Doc]
) -> None:
    doc = docs["B41"]
    open_decision = _open_decision(api_client, env, "BOOKINGS", doc, with_model=False)
    forged = {**open_decision, "smart_import": {"answers": {"not_a_question": "yes"}}}

    response = import_mapped(api_client, env, "BOOKINGS", doc.filename, doc.content, forged)

    assert_error(response, status_code=422, code="INVALID_IMPORT_REQUEST")


def test_a_ready_decision_that_was_changed_is_refused_not_trusted(
    api_client: TestClient, env: SourcesEnv, db_session: Session, docs: dict[str, Doc]
) -> None:
    doc = docs["B41"]
    _model(api_client, None)
    answered = understand(
        api_client,
        env,
        "BOOKINGS",
        doc.filename,
        doc.content,
        {"column_fields": {"Total": "room_revenue"}},
    )
    assert answered["understanding"]["level"] == "READY"
    rows_before = _row_counts(db_session)
    changed = {**answered["proposal"], "constants": {"currency": "USD"}}

    response = import_mapped(api_client, env, "BOOKINGS", doc.filename, doc.content, changed)

    assert_error(response, status_code=409, code="IMPORT_DECISION_CHANGED")
    assert _row_counts(db_session) == rows_before


# --- D: after the person's answer the server settles it, and an explicit import writes ---


@pytest.mark.parametrize("case", ["L12", "BO05", "B41"])
def test_after_the_persons_answer_the_server_settles_the_decision_and_the_import_writes(
    api_client: TestClient, env: SourcesEnv, db_session: Session, docs: dict[str, Doc], case: str
) -> None:
    if case in AI_CASES:
        domain, _, _, unreadable, real = AI_CASES[case]
        _model(api_client, docs[case])
        answers = {"column_fields": {unreadable: real}}
    else:
        domain, real = "BOOKINGS", "room_revenue"
        _model(api_client, None)
        answers = {"column_fields": {"Total": "room_revenue"}}
    doc = docs[case]
    rows_before = _row_counts(db_session)

    answered = understand(api_client, env, domain, doc.filename, doc.content, answers)

    u = answered["understanding"]
    assert u["level"] == "READY" and u["questions"] == []
    assert {r["field"]: r["origin"]["kind"] for r in u["recognized"]}[real] == "USER"
    assert _row_counts(db_session) == rows_before  # the answer itself writes nothing
    assert validation(
        api_client, env, domain, doc.content, answered["proposal"], name=doc.filename
    )["can_import"]
    assert _row_counts(db_session) == rows_before  # nor does the dry run
    result = import_mapped(api_client, env, domain, doc.filename, doc.content, answered["proposal"])
    assert result.status_code == 200 and result.json()["succeeded"] is True
    assert _row_counts(db_session) != rows_before  # only the explicit import writes


# --- E: the person is not obliged to confirm what was suggested ---


def test_the_person_can_choose_a_different_column_than_the_one_suggested(
    api_client: TestClient, env: SourcesEnv, docs: dict[str, Doc]
) -> None:
    domain, decoy, _, unreadable, real = AI_CASES["L12"]
    doc = docs["L12"]
    _model(api_client, doc)  # the wrong model is still suggesting the decoy
    chosen = {"column_fields": {unreadable: real}}  # NOT "Ultima modifica": another, valid, column

    answered = understand(api_client, env, domain, doc.filename, doc.content, chosen)

    assert answered["understanding"]["level"] == "READY"
    placed = {c["header"]: c["field"] for c in answered["proposal"]["columns"]}
    assert placed[unreadable] == real and placed.get(decoy) != real
    result = import_mapped(api_client, env, domain, doc.filename, doc.content, answered["proposal"])
    assert result.status_code == 200 and result.json()["succeeded"] is True


def test_answering_something_else_does_not_settle_the_question_that_is_open(
    api_client: TestClient, env: SourcesEnv, db_session: Session, docs: dict[str, Doc]
) -> None:
    domain, *_ = AI_CASES["L12"]
    doc = docs["L12"]
    _model(api_client, None)
    rows_before = _row_counts(db_session)
    half = understand(api_client, env, domain, doc.filename, doc.content, {"date_order": "DMY"})
    assert half["understanding"]["level"] != "READY"

    response = import_mapped(api_client, env, domain, doc.filename, doc.content, half["proposal"])

    assert_error(response, status_code=409, code=UNRESOLVED)
    assert _row_counts(db_session) == rows_before


# --- F: the manual matching of Smart Import V2 is untouched ---


@pytest.mark.parametrize("case", ["L12", "BO05"])
def test_a_matching_the_person_builds_by_hand_is_judged_on_its_merits_as_before(
    api_client: TestClient, env: SourcesEnv, db_session: Session, docs: dict[str, Doc], case: str
) -> None:
    domain, _, _, unreadable, real = AI_CASES[case]
    doc = docs[case]
    _model(api_client, None)
    answered = understand(
        api_client, env, domain, doc.filename, doc.content, {"column_fields": {unreadable: real}}
    )
    # the person's own matching: the columns they matched, with no reference to any understanding
    by_hand = {**answered["proposal"], "smart_import": None}
    rows_before = _row_counts(db_session)

    judged = validation(api_client, env, domain, doc.content, by_hand, name=doc.filename)
    result = import_mapped(api_client, env, domain, doc.filename, doc.content, by_hand)

    assert judged["can_import"] is True
    assert result.status_code == 200 and result.json()["succeeded"] is True
    assert _row_counts(db_session) != rows_before


def test_a_matching_by_hand_that_is_not_enough_is_refused_by_the_old_rules(
    api_client: TestClient, env: SourcesEnv, docs: dict[str, Doc]
) -> None:
    domain, *_ = AI_CASES["L12"]
    doc = docs["L12"]
    _model(api_client, None)
    proposed = understand(api_client, env, domain, doc.filename, doc.content)["proposal"]
    by_hand = {**proposed, "smart_import": None}

    judged = validation(api_client, env, domain, doc.content, by_hand, name=doc.filename)

    assert judged["can_import"] is False  # not for a question: the work date is simply missing
