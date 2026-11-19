"""Operating costs with no document number, through Smart Import (ADR 0057): the question, the
answer that travels with the decision, the memory of the source, and what a person can still do.

Real files through the real API and database (rolled back), the way a person meets them:

  - a register with everything but a number is ONE question, never the matching screen
  - the answer is verified by the server (it is not a claim the browser makes)
  - the next file of the same source does not ask again; the answer can be forgotten
  - a register of fiscal documents keeps needing its number
  - a complete file of operating costs asks what it holds, once a source exists
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.data_sources.source_learning import parse_learning
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.invoices.models import (
    IdentityOrigin,
    Invoice,
    InvoiceMappingProfile,
    InvoiceRemoval,
    is_current_invoice,
)
from tests.data_sources_support import SourcesEnv, sources_env
from tests.operational_costs_support import OPERATIONAL_HEADERS, cost_row, operational_csv
from tests.smart_import_support import (
    by_hand,
    dry_run,
    import_mapped,
    profiles_of,
    refused_as_unresolved,
    understand,
)
from tests.support import BookingFactory

COSTS = "COSTS"
YES = {"document_identity": "SYNTHETIC_COST_RECORD"}
NOVEMBER = [
    cost_row(day="2026-11-05", description="Energia elettrica novembre"),
    cost_row(
        day="2026-11-06",
        supplier="Acqua Salento",
        description="Acqua novembre",
        net="42.00",
        tax="9.24",
        gross="51.24",
    ),
    cost_row(
        day="2026-11-07",
        supplier="Lavanderia Salento",
        category="LAUNDRY",
        description="Lavanderia novembre",
        net="58.00",
        tax="12.76",
        gross="70.76",
    ),
]
OCTOBER = [
    cost_row(day="2026-10-05", description="Energia elettrica ottobre"),
    cost_row(
        day="2026-10-06",
        supplier="Acqua Salento",
        description="Acqua ottobre",
        net="40.00",
        tax="8.80",
        gross="48.80",
    ),
    cost_row(
        day="2026-10-07",
        supplier="Lavanderia Salento",
        category="LAUNDRY",
        description="Lavanderia ottobre",
        net="55.00",
        tax="12.10",
        gross="67.10",
    ),
]


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def csv(rows: list[list[Any]], headers: list[str] | None = None) -> bytes:
    return operational_csv(rows, headers)


def ask(
    client: TestClient, env: SourcesEnv, content: bytes, answers: dict[str, Any] | None = None
) -> dict[str, Any]:
    return understand(client, env, COSTS, "costi.csv", content, answers)


def kinds(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


def imported(
    client: TestClient, env: SourcesEnv, content: bytes, body: dict[str, Any]
) -> dict[str, Any]:
    response = import_mapped(client, env, COSTS, "costi.csv", content, body["proposal"])
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def records(session: Session, env: SourcesEnv) -> list[Invoice]:
    session.expire_all()
    return list(session.scalars(select(Invoice).where(Invoice.workspace_id == env.workspace.id)))


def counting(session: Session, env: SourcesEnv) -> list[Invoice]:
    session.expire_all()
    return list(
        session.scalars(
            select(Invoice).where(Invoice.workspace_id == env.workspace.id, is_current_invoice())
        )
    )


def source_id(session: Session, env: SourcesEnv) -> UUID:
    source = session.scalar(
        select(DataSource).where(
            DataSource.property_id == env.property.id, DataSource.domain == DataSourceDomain.COSTS
        )
    )
    assert source is not None
    return source.id


def remembered(client: TestClient, env: SourcesEnv, source: UUID) -> dict[str, Any]:
    response = client.get(f"{env.base}/{source}/remembered-answers")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def known(api_client: TestClient, env: SourcesEnv, db_session: Session) -> UUID:
    """A source whose first register (three operating costs) was answered once and imported."""
    content = csv(OCTOBER)
    answered = ask(api_client, env, content, YES)
    assert answered["understanding"]["level"] == "READY"
    result = imported(api_client, env, content, answered)
    assert result["succeeded"] is True, result
    return source_id(db_session, env)


# --- the question ----------------------------------------------------------------------------


def test_a_register_with_everything_but_a_number_is_one_question_and_no_blocker(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = ask(api_client, env, csv(OCTOBER))

    u = body["understanding"]
    assert u["level"] == "ASK" and u["blockers"] == []
    assert kinds(body) == ["DOCUMENT_IDENTITY"]
    assert u["detection"]["domain"] == COSTS
    assert body["proposal"]["document_identity"] is None  # nothing is decided until it is answered
    fields = {c["header"]: c["field"] for c in body["columns"]}
    assert "invoice_number" not in fields.values()  # no column is made to be a number
    [question] = u["questions"]
    assert [choice["value"] for choice in question["choices"]] == ["SYNTHETIC_COST_RECORD"]


def test_the_answer_makes_it_ready_and_the_number_is_no_longer_required(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = ask(api_client, env, csv(OCTOBER), YES)

    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == []
    assert body["proposal"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    assert ["invoice_number"] not in body["requirement_groups"]


def test_nothing_is_written_by_asking_or_answering(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    ask(api_client, env, csv(OCTOBER))
    ask(api_client, env, csv(OCTOBER), YES)

    assert records(db_session, env) == []
    assert profiles_of(db_session, env, InvoiceMappingProfile) == []
    assert db_session.scalar(select(func.count()).select_from(DataSource)) == 0


# --- the decision is verified by the server -----------------------------------------------------


def test_the_answer_cannot_be_posted_by_hand_to_turn_a_question_into_a_yes(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = csv(OCTOBER)
    asked = ask(api_client, env, content)
    forged = {**asked["proposal"], "document_identity": "SYNTHETIC_COST_RECORD"}

    details = refused_as_unresolved(api_client, env, COSTS, "costi.csv", content, forged)

    assert "DOCUMENT_IDENTITY" in details["questions"]


def test_a_matching_built_by_hand_never_carries_the_answer(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """Nobody was asked when the matching is built by hand: it identifies by the number it maps."""
    content = csv(OCTOBER)
    answered = ask(api_client, env, content, YES)
    manual = by_hand(answered["proposal"])

    judged = dry_run(api_client, env, COSTS, "costi.csv", content, manual)
    result = import_mapped(api_client, env, COSTS, "costi.csv", content, manual)

    for response in (judged, result):
        body = response.json()
        assert body.get("succeeded") is not True and body.get("status") != "OK", body
    assert records(db_session, env) == []


# --- the import, and the memory of the source ---------------------------------------------------


def test_the_import_records_operating_costs_with_no_number_and_remembers_the_answer(
    api_client: TestClient, env: SourcesEnv, db_session: Session, known: UUID
) -> None:
    saved = records(db_session, env)
    assert len(saved) == 3
    for record in saved:
        assert record.invoice_number is None and record.normalized_invoice_number is None
        assert record.identity_origin == IdentityOrigin.SYNTHETIC_COST_RECORD
    [profile] = profiles_of(db_session, env, InvoiceMappingProfile)
    assert profile.format_options["document_identity"] == "SYNTHETIC_COST_RECORD"
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    [family] = store.of_domain(COSTS).families
    assert family.answers.get("document_identity") == "SYNTHETIC_COST_RECORD"


def test_the_next_file_of_the_same_source_does_not_ask_again(
    api_client: TestClient, env: SourcesEnv, db_session: Session, known: UUID
) -> None:
    content = csv(NOVEMBER)

    body = ask(api_client, env, content)  # no answer given: the source remembers it

    assert body["understanding"]["level"] == "READY" and kinds(body) == [], body["understanding"][
        "questions"
    ]
    assert body["proposal"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    result = imported(api_client, env, content, body)
    assert result["succeeded"] is True
    assert len(counting(db_session, env)) == 6


def test_the_same_file_again_creates_no_cost(
    api_client: TestClient, env: SourcesEnv, db_session: Session, known: UUID
) -> None:
    content = csv(OCTOBER)

    body = ask(api_client, env, content)
    result = imported(api_client, env, content, body)

    assert result["succeeded"] is True
    assert len(records(db_session, env)) == 3  # nothing new: the three are the same three


# --- correctable and forgettable ---------------------------------------------------------------


def test_the_answer_is_shown_with_the_remembered_answers_and_can_be_forgotten(
    api_client: TestClient, env: SourcesEnv, known: UUID
) -> None:
    [item] = remembered(api_client, env, known)["files"]
    assert item["answers"]["document_identity"] == "SYNTHETIC_COST_RECORD"

    response = api_client.delete(f"{env.base}/{known}/remembered-answers/{item['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["files"] == []
    again = ask(api_client, env, csv(OCTOBER))
    assert again["understanding"]["level"] == "ASK"
    assert kinds(again) == ["DOCUMENT_IDENTITY"]  # asked again, as the first time


def test_a_forgotten_answer_can_be_given_again_and_is_remembered_again(
    api_client: TestClient, env: SourcesEnv, known: UUID, db_session: Session
) -> None:
    [item] = remembered(api_client, env, known)["files"]
    api_client.delete(f"{env.base}/{known}/remembered-answers/{item['id']}")
    content = csv(OCTOBER)

    answered = ask(api_client, env, content, YES)
    result = imported(api_client, env, content, answered)

    assert result["succeeded"] is True
    assert len(remembered(api_client, env, known)["files"]) == 1
    assert kinds(ask(api_client, env, csv(NOVEMBER))) == []


# --- a register of fiscal documents keeps needing its number --------------------------------


def test_a_register_of_documents_is_not_offered_the_shortcut(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """A due date makes it document-level: the number stays required, and nothing is asked."""
    headers = [*OPERATIONAL_HEADERS, "Scadenza"]
    rows = [[*row, "2026-11-30"] for row in OCTOBER]

    body = ask(api_client, env, csv(rows, headers))

    u = body["understanding"]
    assert "DOCUMENT_IDENTITY" not in kinds(body)
    assert u["level"] in ("MANUAL", "BLOCKED")
    assert any(
        b["code"] == "MISSING_REQUIRED" and ["invoice_number"] in b["groups"] for b in u["blockers"]
    )


def test_a_register_that_has_a_number_never_gets_the_question(
    api_client: TestClient, env: SourcesEnv
) -> None:
    headers = ["Numero documento", *OPERATIONAL_HEADERS]
    rows = [[f"FA/{i}", *row] for i, row in enumerate(OCTOBER, start=1)]

    body = ask(api_client, env, csv(rows, headers))

    assert "DOCUMENT_IDENTITY" not in kinds(body)
    assert body["proposal"]["document_identity"] is None


# --- what a complete file of operating costs holds ----------------------------------------------


def test_a_first_file_never_asks_what_it_holds(api_client: TestClient, env: SourcesEnv) -> None:
    body = ask(api_client, env, csv(OCTOBER), YES)

    assert "FILE_SCOPE" not in kinds(body)  # no source yet: nothing can be missing from it


def test_a_file_that_lacks_a_cost_of_its_period_asks_what_it_holds(
    api_client: TestClient, env: SourcesEnv, known: UUID
) -> None:
    lacking = csv([OCTOBER[0], OCTOBER[2]])  # October 5th to 7th, without the cost of the 6th

    body = ask(api_client, env, lacking)

    assert kinds(body) == ["FILE_SCOPE"]
    [question] = body["understanding"]["questions"]
    assert question["absent_records"] == 1


def test_a_complete_file_takes_the_missing_cost_away_and_says_so(
    api_client: TestClient, env: SourcesEnv, db_session: Session, known: UUID
) -> None:
    lacking = csv([OCTOBER[0], OCTOBER[2]])

    body = ask(api_client, env, lacking, {"file_scope": "FULL"})

    assert body["understanding"]["level"] == "READY" and body["understanding"]["removes"] == 1
    assert body["proposal"]["file_scope"] == "FULL" and body["proposal"]["expected_removals"] == 1
    result = imported(api_client, env, lacking, body)
    assert result["succeeded"] is True and result["removed"] == 1
    assert len(records(db_session, env)) == 3 and len(counting(db_session, env)) == 2
    assert db_session.scalar(select(func.count()).select_from(InvoiceRemoval)) == 1


@pytest.mark.parametrize("scope", ["PARTIAL", "DELTA"])
def test_a_part_of_the_period_takes_nothing_away(
    api_client: TestClient, env: SourcesEnv, db_session: Session, known: UUID, scope: str
) -> None:
    lacking = csv([OCTOBER[0], OCTOBER[2]])

    body = ask(api_client, env, lacking, {"file_scope": scope})
    result = imported(api_client, env, lacking, body)

    assert body["understanding"]["removes"] == 0 and result["removed"] == 0
    assert len(counting(db_session, env)) == 3


def test_a_register_with_numbers_never_asks_what_it_holds(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """A cost register may always be partial when its unit is the document."""
    headers = ["Numero documento", *OPERATIONAL_HEADERS]
    rows = [[f"FA/{i}", *row] for i, row in enumerate(OCTOBER, start=1)]
    first = csv(rows, headers)
    body = ask(api_client, env, first)
    # (the register is read by its numbers; whatever it asks, it never asks what it holds)
    assert "FILE_SCOPE" not in kinds(body)
    if body["understanding"]["level"] == "READY":
        imported(api_client, env, first, body)
        shorter = ask(api_client, env, csv(rows[:2], headers))
        assert "FILE_SCOPE" not in kinds(shorter)
