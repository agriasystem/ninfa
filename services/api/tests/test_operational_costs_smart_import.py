"""Operating costs with no document number, through Smart Import (ADR 0057, final correctness
gate): when a file is read as operating costs, when it is asked about, and what a person can do.

Real files through the real API and database (rolled back), the way a person meets them. The rule:
without a column of document numbers filled in most rows, a file is NEVER taken to be invoices by
itself (FatturaPA aside, and a person's saved word aside):

  - nothing points at documents (or only a due date / a row number): operating costs, no question
  - something does (document type, the whole picture of an invoice register, a number column empty
    in most rows): ONE semantic question, remembered by the family, correctable
  - "fatture o documenti": not imported, a plain reason, never a column to match
  - credit notes without a number are refused row by row, never synthetic
  - the internal reference never reaches a person as a number
  - a complete file of operating costs asks what it holds, once a source exists

T13-T17, T20, T23 and T24 of the gate are named in the tests.
"""

import json
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
NUMBER = {"document_identity": "DOCUMENT_NUMBER"}
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
    """A source whose first register (three operating costs) was imported, the person having
    said what it holds (an answer the register itself did not need)."""
    content = csv(OCTOBER)
    answered = ask(api_client, env, content, YES)
    assert answered["understanding"]["level"] == "READY"
    result = imported(api_client, env, content, answered)
    assert result["succeeded"] is True, result
    return source_id(db_session, env)


# --- T13-T15: nothing points at documents -> operating costs, no question ----------------------


def assert_operating_costs_without_question(body: dict[str, Any]) -> None:
    u = body["understanding"]
    assert u["level"] == "READY", (u["level"], u["questions"], u["blockers"])
    assert u["questions"] == [] and u["blockers"] == []
    assert body["proposal"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    assert ["invoice_number"] not in body["requirement_groups"]


def test_t13_a_cost_register_without_a_number_is_operating_costs_with_no_question(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """T13: the structure of `costi_ottobre_2026.csv` (Data, Fornitore, Categoria, Descrizione,
    Imponibile, IVA, Totale): nothing in it is a fiscal document. Read as operating costs, with no
    question about a document number and no column made to be one."""
    body = ask(api_client, env, csv(OCTOBER))

    assert_operating_costs_without_question(body)
    assert body["understanding"]["detection"]["domain"] == COSTS
    fields = {c["header"]: c["field"] for c in body["columns"]}
    assert "invoice_number" not in fields.values()


def test_t13_the_register_imports_with_no_number_and_a_technical_key(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    content = csv(OCTOBER)
    body = ask(api_client, env, content)

    result = imported(api_client, env, content, body)

    assert result["succeeded"] is True
    saved = records(db_session, env)
    assert len(saved) == 3
    for record in saved:
        assert record.invoice_number is None and record.normalized_invoice_number is None
        assert record.identity_origin == IdentityOrigin.SYNTHETIC_COST_RECORD
        assert record.source_record_key.startswith("cost:v1:")


def with_extra(header: str, value: str, rows: list[list[Any]] | None = None) -> bytes:
    return csv([[*row, value] for row in rows or OCTOBER], [*OPERATIONAL_HEADERS, header])


def test_t14_a_register_with_a_due_date_is_operating_costs_with_no_question(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """T14: a "Scadenza" column is what an operating-cost register carries too."""
    body = ask(api_client, env, with_extra("Scadenza", "2026-11-30"))

    assert_operating_costs_without_question(body)


@pytest.mark.parametrize("header", ["N.", "Progressivo", "N. riga"])
def test_t15_a_register_with_a_row_number_is_operating_costs_with_no_question(
    api_client: TestClient, env: SourcesEnv, header: str
) -> None:
    """T15: a row number or a progressive is a position in the register, not a document."""
    rows = [[*row, str(i)] for i, row in enumerate(OCTOBER, start=1)]

    body = ask(api_client, env, csv(rows, [*OPERATIONAL_HEADERS, header]))

    assert_operating_costs_without_question(body)


def test_a_due_date_and_a_row_number_together_are_still_no_question(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """Both weak signals together (457099e's WEAK class): still nothing that says documents."""
    headers = [*OPERATIONAL_HEADERS, "Scadenza", "N."]
    rows = [[*row, "2026-11-30", str(i)] for i, row in enumerate(OCTOBER, start=1)]

    assert_operating_costs_without_question(ask(api_client, env, csv(rows, headers)))


def test_a_supplier_vat_number_alone_is_no_proof_of_a_register_of_invoices(
    api_client: TestClient, env: SourcesEnv
) -> None:
    assert_operating_costs_without_question(
        ask(api_client, env, with_extra("Partita IVA", "01234567890"))
    )


def test_nothing_is_written_by_reading_a_file(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    ask(api_client, env, csv(OCTOBER))
    ask(api_client, env, with_extra("Tipo documento", "Fattura"))
    ask(api_client, env, with_extra("Tipo documento", "Fattura"), YES)

    assert records(db_session, env) == []
    assert profiles_of(db_session, env, InvoiceMappingProfile) == []
    assert db_session.scalar(select(func.count()).select_from(DataSource)) == 0


# --- T16, T23: something points at documents -> ONE semantic question ---------------------------

TYPED = ["Tipo documento", "Scadenza"]


def typed(rows: list[list[Any]], kinds: list[str] | None = None) -> bytes:
    """A register with a document type and a due date, no document number."""
    kinds = kinds or ["Fattura"] * len(rows)
    return csv(
        [[*row, kind, "2026-11-30"] for row, kind in zip(rows, kinds, strict=True)],
        [*OPERATIONAL_HEADERS, *TYPED],
    )


def assert_asks_what_it_holds(body: dict[str, Any]) -> None:
    u = body["understanding"]
    assert u["level"] == "ASK" and u["blockers"] == []
    assert kinds(body) == ["DOCUMENT_IDENTITY"]
    [question] = u["questions"]
    assert [choice["value"] for choice in question["choices"]] == [
        "SYNTHETIC_COST_RECORD",
        "DOCUMENT_NUMBER",
    ]
    assert body["proposal"]["document_identity"] is None  # nothing decided until it is answered


def test_t23_a_document_type_without_a_number_is_one_question_never_a_number_to_match(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """T23: "Tipo documento" says "Fattura", but there is no column of numbers. The file is not
    taken to be invoices by itself, and nobody is asked to point at a number it does not have."""
    body = ask(api_client, env, with_extra("Tipo documento", "Fattura"))

    assert_asks_what_it_holds(body)
    for blocker in body["understanding"]["blockers"]:
        assert ["invoice_number"] not in blocker["groups"]


def test_the_whole_picture_of_an_invoice_register_is_asked_and_the_answer_decides(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """Document type, due date and a supplier identified fiscally, no number: 457099e's STRONG
    evidence. Asked (never automatic); said to be operating costs, it imports as operating costs."""
    headers = [*OPERATIONAL_HEADERS, "Tipo documento", "Scadenza", "P.IVA"]
    content = csv([[*row, "Fattura", "2026-11-30", "01234567890"] for row in OCTOBER], headers)

    assert_asks_what_it_holds(ask(api_client, env, content))
    answered = ask(api_client, env, content, YES)

    assert answered["understanding"]["level"] == "READY"
    assert answered["proposal"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    assert imported(api_client, env, content, answered)["succeeded"] is True
    assert all(r.invoice_number is None for r in records(db_session, env))


def test_t16_answered_operating_costs_once_the_same_structure_is_not_asked_again(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T16: Scadenza + Tipo documento. One semantic question; "costi operativi" is remembered by the
    family (Source Learning), shown with the remembered answers, and can be forgotten."""
    first = typed(OCTOBER)
    assert_asks_what_it_holds(ask(api_client, env, first))
    answered = ask(api_client, env, first, YES)
    assert answered["understanding"]["level"] == "READY"
    assert imported(api_client, env, first, answered)["succeeded"] is True

    second = typed(NOVEMBER)
    again = ask(api_client, env, second)  # no answer given: the family remembers it

    assert again["understanding"]["level"] == "READY" and kinds(again) == []
    assert again["proposal"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    source = source_id(db_session, env)
    [profile] = profiles_of(db_session, env, InvoiceMappingProfile)
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    [family] = store.of_domain(COSTS).families
    assert family.answers.get("document_identity") == "SYNTHETIC_COST_RECORD"
    [item] = remembered(api_client, env, source)["files"]
    assert item["answers"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    # correctable: forgotten, the question comes back as the first time
    api_client.delete(f"{env.base}/{source}/remembered-answers/{item['id']}")
    assert_asks_what_it_holds(ask(api_client, env, second))


def test_the_answer_cannot_be_posted_by_hand_to_turn_a_question_into_a_yes(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = with_extra("Tipo documento", "Fattura")
    asked = ask(api_client, env, content)
    forged = {**asked["proposal"], "document_identity": "SYNTHETIC_COST_RECORD"}

    details = refused_as_unresolved(api_client, env, COSTS, "costi.csv", content, forged)

    assert "DOCUMENT_IDENTITY" in details["questions"]


# --- T17: said to be invoices -> a plain "no", never a column to match ---------------------------


def assert_refused_as_invoices_without_number(body: dict[str, Any]) -> None:
    u = body["understanding"]
    assert u["level"] == "BLOCKED"
    assert [b["code"] for b in u["blockers"]] == ["DOCUMENT_NUMBER_MISSING"]
    assert u["questions"] == []  # answered: not asked again, and nothing else to answer
    assert body["proposal"]["document_identity"] is None  # never imported as operating costs


def test_t17_said_to_be_invoices_without_a_number_nothing_is_imported_and_nothing_is_to_match(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T17: "Fatture o documenti" with no document number: not imported as invoices (there is no
    number to register them by), a plain reason, and no request to match a column that does not
    exist (BLOCKED is never the matching screen; no MISSING_REQUIRED names the number)."""
    content = with_extra("Tipo documento", "Fattura")

    body = ask(api_client, env, content, NUMBER)

    assert_refused_as_invoices_without_number(body)
    result = import_mapped(api_client, env, COSTS, "costi.csv", content, body["proposal"])
    assert result.json().get("succeeded") is not True
    assert records(db_session, env) == []


def test_said_to_be_invoices_a_register_with_no_signal_is_refused_the_same_way(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """The person's word wins over the file's silence (exception (b) of the rule: a saved answer
    goes through the same path as one given now)."""
    assert_refused_as_invoices_without_number(ask(api_client, env, csv(OCTOBER), NUMBER))


# --- a column of numbers empty in most rows is no column of numbers ------------------------------


def sparse_number(rows: list[list[Any]]) -> bytes:
    numbers = ["FT/1"] + [""] * (len(rows) - 1)
    return csv(
        [[number, *row] for number, row in zip(numbers, rows, strict=True)],
        ["Numero documento", *OPERATIONAL_HEADERS],
    )


def test_a_number_column_empty_in_most_rows_is_asked_never_taken_for_invoices(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    content = sparse_number(OCTOBER)

    assert_asks_what_it_holds(ask(api_client, env, content))
    answered = ask(api_client, env, content, YES)
    assert answered["understanding"]["level"] == "READY"
    proposal_fields = {c["header"]: c["field"] for c in answered["proposal"]["columns"]}
    assert proposal_fields["Numero documento"] is None  # its one number identifies nothing
    assert imported(api_client, env, content, answered)["succeeded"] is True
    saved = records(db_session, env)
    assert len(saved) == 3
    assert all(r.invoice_number is None for r in saved)
    assert_refused_as_invoices_without_number(ask(api_client, env, content, NUMBER))


def test_a_register_that_has_a_number_never_gets_the_question(
    api_client: TestClient, env: SourcesEnv
) -> None:
    headers = ["Numero documento", *OPERATIONAL_HEADERS]
    rows = [[f"FA/{i}", *row] for i, row in enumerate(OCTOBER, start=1)]

    body = ask(api_client, env, csv(rows, headers))

    assert "DOCUMENT_IDENTITY" not in kinds(body)
    assert body["proposal"]["document_identity"] is None
    assert all(b["code"] != "DOCUMENT_NUMBER_MISSING" for b in body["understanding"]["blockers"])


# --- T24: credit notes are never operating costs -------------------------------------------------


def test_t24_remembered_operating_costs_still_refuse_credit_notes_without_a_number(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T24: the family answered "costi operativi" (no question the second time), and the second file
    has a credit note with no number: that row is refused with a readable reason and nothing of the
    file is recorded. (That a negative amount alone is never a credit note is proved on the
    importer: `test_only_the_document_type_says_credit_note_never_the_sign_of_the_amount`.)"""
    first = typed(OCTOBER)
    answered = ask(api_client, env, first, YES)
    assert imported(api_client, env, first, answered)["succeeded"] is True
    second = typed(NOVEMBER, ["Fattura", "Nota di credito", "Fattura"])

    again = ask(api_client, env, second)

    assert again["understanding"]["level"] == "READY" and kinds(again) == []
    judged = dry_run(api_client, env, COSTS, "costi.csv", second, again["proposal"]).json()
    assert judged["can_import"] is False, judged
    assert "CREDIT_NOTE_WITHOUT_NUMBER" in json.dumps(judged)
    result = import_mapped(api_client, env, COSTS, "costi.csv", second, again["proposal"]).json()
    assert result.get("succeeded") is not True
    assert len(records(db_session, env)) == 3  # only the first file's costs
    # the same file with that row said to be an invoice: it imports, the family still not asked
    fine = typed(NOVEMBER)
    body = ask(api_client, env, fine)
    assert body["understanding"]["level"] == "READY" and kinds(body) == []
    assert imported(api_client, env, fine, body)["succeeded"] is True
    assert len(records(db_session, env)) == 6


# --- T20: the internal reference is never a document number --------------------------------------


def test_t20_no_answer_the_api_gives_shows_the_internal_reference_as_a_number(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T20: after an import of operating costs, nothing the API sends a person carries the internal
    reference (as a number or under any name): understanding, validation, import, the remembered
    answers, the sources overview and the data overview."""
    content = csv(OCTOBER)
    body = ask(api_client, env, content)
    judged = dry_run(api_client, env, COSTS, "costi.csv", content, body["proposal"]).json()
    result = imported(api_client, env, content, body)
    keys = [r.source_record_key for r in records(db_session, env)]
    assert keys and all(k.startswith("cost:v1:") for k in keys)
    source = source_id(db_session, env)
    answers = [
        body,
        judged,
        result,
        ask(api_client, env, content),
        remembered(api_client, env, source),
        api_client.get(env.base).json(),
        api_client.get(f"/api/v1/properties/{env.property.id}/data/overview").json(),
    ]
    for answer in answers:
        text = json.dumps(answer)
        assert "cost:v1" not in text and "source_record_key" not in text
        assert "identity_origin" not in text
        for key in keys:
            assert key.split("#")[0].removeprefix("cost:v1:") not in text


def test_a_matching_built_by_hand_keeps_operating_costs_and_never_needs_a_number(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """Point 3 of the gate (this replaces "a matching built by hand never carries the answer"): a
    file classified as operating costs stays so on the matching screen - the number is not
    required - and the server verifies it against the file, never on the browser's word."""
    content = csv(OCTOBER)
    body = ask(api_client, env, content)
    manual = by_hand(body["proposal"])
    assert manual["document_identity"] == "SYNTHETIC_COST_RECORD"

    checked = api_client.post(
        f"{env.base}/import-mapping-check", json={"domain": COSTS, "mapping": manual}
    )
    judged = dry_run(api_client, env, COSTS, "costi.csv", content, manual)
    result = import_mapped(api_client, env, COSTS, "costi.csv", content, manual)

    assert checked.status_code == 200 and ["invoice_number"] not in checked.json()["missing"]
    assert judged.json()["can_import"] is True, judged.json()
    assert result.json()["succeeded"] is True, result.json()
    saved = records(db_session, env)
    assert len(saved) == 3 and all(r.invoice_number is None for r in saved)


def test_operating_costs_missing_something_else_go_to_the_matching_screen_without_the_number(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """The description is in a column nobody named: the file goes to the matching screen for THAT,
    already classified as operating costs - the number is never listed as missing or required."""
    headers = ["Data", "Fornitore", "Categoria", "Campo 2", "Imponibile", "IVA", "Totale"]
    content = csv(OCTOBER, headers)

    body = ask(api_client, env, content)

    u = body["understanding"]
    assert u["level"] == "MANUAL"
    assert [b["groups"] for b in u["blockers"]] == [[["line_description"]]]
    assert body["proposal"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    assert ["invoice_number"] not in body["requirement_groups"]
    # the person names the description by hand: imported as operating costs
    manual = by_hand(body["proposal"])
    manual["columns"] = [
        {**c, "field": "line_description"} if c["header"] == "Campo 2" else c
        for c in manual["columns"]
    ]
    result = import_mapped(api_client, env, COSTS, "costi.csv", content, manual)
    assert result.json()["succeeded"] is True, result.json()
    assert all(r.invoice_number is None for r in records(db_session, env))


def test_a_hand_claim_of_operating_costs_is_never_taken_for_a_file_with_document_numbers(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """A file whose number column is filled is classified as documents: a matching built by hand
    that leaves the number out and says "operating costs" does not make it so - the number stays
    required and nothing is written."""
    headers = ["Numero documento", *OPERATIONAL_HEADERS]
    content = csv([[f"FA/{i}", *row] for i, row in enumerate(OCTOBER, start=1)], headers)
    body = ask(api_client, env, content)
    assert body["proposal"]["document_identity"] is None
    assert ["invoice_number"] in body["requirement_groups"]  # documents: the number is required
    manual = by_hand(body["proposal"])
    manual["document_identity"] = "SYNTHETIC_COST_RECORD"
    manual["columns"] = [
        {**c, "field": None} if c["field"] == "invoice_number" else c for c in manual["columns"]
    ]

    result = import_mapped(api_client, env, COSTS, "costi.csv", content, manual)

    assert result.json().get("succeeded") is not True, result.json()
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
    # (nothing in this register points at documents: forgotten or not, it is not asked about)
    again = ask(api_client, env, csv(OCTOBER))
    assert again["understanding"]["level"] == "READY" and kinds(again) == []


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


# --- T25: FULL between two different registers of the same property --------------------------
# Fact: every costs upload of a property goes into ONE data source (`_source_for_domain`: the
# single active source of (property, COSTS)), whatever its structure or family. A complete file
# takes away only what its own REGISTER (`InvoiceMappingConfig.register_key`) wrote.

UTILITIES_HEADERS = ["Data", "Fornitore", "Descrizione", "Importo netto"]
UTILITY_SUPPLIERS = ["Enel Energia", "Acqua Salento", "Gas Puglia", "Telecom", "Rifiuti Lecce"]
DAYS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
UTILITIES = [
    [day, supplier, f"Utenza {supplier} {day}", f"{40 + 10 * i}.00"]
    for i, (day, supplier) in enumerate(zip(DAYS, UTILITY_SUPPLIERS, strict=True))
]
LAUNDRY = [
    cost_row(
        day=day,
        supplier="Lavanderia Salento",
        category="LAUNDRY",
        description=f"Lavaggio biancheria {day}",
        net="55.00",
        tax="12.10",
        gross="67.10",
    )
    for day in DAYS
]


def test_t25_a_complete_register_never_takes_away_the_costs_of_another_register(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T25: register A (laundry) and register B (utilities, another structure) of the same property
    and period. B again as a complete file with one row less: only B's missing cost may go; A's
    costs stay intact."""
    laundry = csv(LAUNDRY)
    body = ask(api_client, env, laundry)
    assert body["understanding"]["level"] == "READY", body["understanding"]
    assert imported(api_client, env, laundry, body)["succeeded"] is True
    utilities = csv(UTILITIES, UTILITIES_HEADERS)
    body = ask(api_client, env, utilities, {"file_scope": "PARTIAL"})
    assert body["understanding"]["level"] == "READY", body["understanding"]
    assert imported(api_client, env, utilities, body)["succeeded"] is True
    assert len(counting(db_session, env)) == 10

    shorter = csv([u for i, u in enumerate(UTILITIES) if i != 2], UTILITIES_HEADERS)
    body = ask(api_client, env, shorter, {"file_scope": "FULL"})
    assert body["understanding"]["level"] == "READY", body["understanding"]
    shown = body["understanding"]["removes"]
    result = imported(api_client, env, shorter, body)

    left = counting(db_session, env)
    assert result["succeeded"] is True, result
    assert (shown, result["removed"], len(left)) == (1, 1, 9), (shown, result["removed"], len(left))


# --- a document number in a column nobody named (PC_unnamed02-like): T26, T27 ------------------

UNNAMED_HEADERS = ["Data", "Fornitore", "Descrizione", "Imponibile", "Campo 1"]
INVOICES = [
    [f"2026-10-{day:02d}", supplier, description, net, f"2026/{100 + day}"]
    for day, supplier, description, net in [
        (5, "Enel Energia", "Energia elettrica", "100.00"),
        (6, "Acqua Salento", "Acqua", "40.00"),
        (7, "Lavanderia Salento", "Lavaggio biancheria", "55.00"),
        (8, "Gas Puglia", "Gas", "30.00"),
        (9, "Telecom", "Telefono", "20.00"),
        (12, "Rifiuti Lecce", "Rifiuti", "25.00"),
    ]
]
WHICH_COLUMN = {
    "document_identity": "DOCUMENT_NUMBER",
    "column_fields": {"Campo 1": "invoice_number"},
}


def unnamed(rows: list[list[Any]]) -> bytes:
    return csv(rows, UNNAMED_HEADERS)


def test_t27_invoices_whose_number_nobody_named_are_asked_and_imported_with_their_numbers(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T27: the number is in "Campo 1" (2026/105, ...). Never read as operating costs by itself: one
    question; "fatture" -> which column, offering ONLY that column and "none of these"; the column
    chosen -> an import of invoices with their real numbers, no synthetic cost."""
    content = unnamed(INVOICES)

    first = ask(api_client, env, content)
    assert_asks_what_it_holds(first)

    which = ask(api_client, env, content, NUMBER)
    u = which["understanding"]
    assert u["level"] == "ASK" and u["blockers"] == []
    assert kinds(which) == ["DOCUMENT_NUMBER_COLUMN"]
    [question] = u["questions"]
    assert [choice["value"] for choice in question["choices"]] == ["Campo 1", "NONE"]

    chosen = ask(api_client, env, content, WHICH_COLUMN)
    assert chosen["understanding"]["level"] == "READY", chosen["understanding"]
    assert chosen["proposal"]["document_identity"] is None
    fields = {c["header"]: c["field"] for c in chosen["proposal"]["columns"]}
    assert fields["Campo 1"] == "invoice_number"
    assert imported(api_client, env, content, chosen)["succeeded"] is True
    saved = records(db_session, env)
    assert len(saved) == 6
    assert all(r.identity_origin == IdentityOrigin.DOCUMENT_NUMBER for r in saved)
    assert sorted(r.invoice_number or "" for r in saved) == sorted(row[4] for row in INVOICES)


def test_none_of_the_columns_offered_is_a_plain_no(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    content = unnamed(INVOICES)

    body = ask(api_client, env, content, {**NUMBER, "document_number_column": "NONE"})

    assert_refused_as_invoices_without_number(body)
    assert records(db_session, env) == []


def test_a_column_that_was_not_offered_is_never_the_number(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """Only a column the file has, and that may be it, is ever the number: naming another one (or
    one that does not exist) changes nothing."""
    content = unnamed(INVOICES)

    body = ask(
        api_client,
        env,
        content,
        {
            "document_identity": "DOCUMENT_NUMBER",
            "column_fields": {"Numero fattura": "invoice_number"},
        },
    )

    assert kinds(body) == ["DOCUMENT_NUMBER_COLUMN"]
    assert "invoice_number" not in {c["field"] for c in body["proposal"]["columns"]}


def test_said_to_be_operating_costs_the_column_stays_out_and_nothing_is_a_number(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    content = unnamed(INVOICES)

    body = ask(api_client, env, content, YES)

    assert body["understanding"]["level"] == "READY"
    assert body["proposal"]["document_identity"] == "SYNTHETIC_COST_RECORD"
    fields = {c["header"]: c["field"] for c in body["proposal"]["columns"]}
    assert fields["Campo 1"] is None
    assert imported(api_client, env, content, body)["succeeded"] is True
    assert all(r.invoice_number is None for r in records(db_session, env))


def test_t26_a_family_said_to_be_invoices_is_refused_without_asking_again(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T26, exception (b): the family's saved answer is "fatture o documenti" (it was imported as
    invoices, its number in "Campo 1"). The next file of the same structure lost its numbers: no
    question, the same plain refusal as T17, nothing written."""
    first = unnamed(INVOICES)
    chosen = ask(api_client, env, first, WHICH_COLUMN)
    assert imported(api_client, env, first, chosen)["succeeded"] is True
    [item] = remembered(api_client, env, source_id(db_session, env))["files"]
    assert item["answers"]["document_identity"] == "DOCUMENT_NUMBER"
    without_numbers = unnamed(
        [[*row[:4], ""] for row in INVOICES[:5]] + [[*INVOICES[5][:4], "2026/200"]]
    )

    body = ask(api_client, env, without_numbers)

    assert_refused_as_invoices_without_number(body)
    assert len(records(db_session, env)) == 6  # only the first file's invoices


# --- T28: a movement counter is no document number -----------------------------------------------


def test_t28_a_register_with_a_movement_id_1_to_n_is_operating_costs_with_no_question(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows = [[str(i), *row] for i, row in enumerate(OCTOBER, start=1)]

    body = ask(api_client, env, csv(rows, ["ID movimento", *OPERATIONAL_HEADERS]))

    assert_operating_costs_without_question(body)
    fields = {c["header"]: c["field"] for c in body["proposal"]["columns"]}
    assert fields["ID movimento"] is None


# --- T29, T30: the same register when its header changes -------------------------------------

REGISTER = [
    cost_row(
        day=f"2026-10-{day:02d}",
        supplier=supplier,
        category=category,
        description=f"{description} ottobre",
        net=net,
        tax="0.00",
        gross=net,
    )
    for day, supplier, category, description, net in [
        (5, "Enel Energia", "UTILITIES", "Energia elettrica", "100.00"),
        (6, "Acqua Salento", "UTILITIES", "Acqua", "40.00"),
        (7, "Lavanderia Salento", "LAUNDRY", "Lavaggio biancheria", "55.00"),
        (8, "Gas Puglia", "UTILITIES", "Gas", "30.00"),
        (9, "Pulizie Lecce", "CLEANING", "Pulizie camere", "80.00"),
    ]
]


def registers(session: Session, env: SourcesEnv) -> set[str | None]:
    return {r.cost_register_key for r in counting(session, env)}


def with_column(rows: list[list[Any]], header: str, value: str) -> bytes:
    return csv([[*row, value] for row in rows], [*OPERATIONAL_HEADERS, header])


def first_register(api_client: TestClient, env: SourcesEnv, session: Session) -> str | None:
    content = csv(REGISTER)
    body = ask(api_client, env, content)
    assert body["understanding"]["level"] == "READY", body["understanding"]
    assert imported(api_client, env, content, body)["succeeded"] is True
    [key] = registers(session, env)
    return key


def test_t29_a_column_nobody_reads_added_to_the_register_is_the_same_register(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T29 (a): the register keeps its columns and gains one NINFA does not read ("Note"): the
    register is the same (it is made of the columns read), nothing is duplicated."""
    key = first_register(api_client, env, db_session)
    content = with_column(REGISTER, "Note", "verificato")

    body = ask(api_client, env, content)
    assert {c["header"]: c["field"] for c in body["proposal"]["columns"]}["Note"] is None
    result = imported(api_client, env, content, body)

    assert result["succeeded"] is True and result["created"] == 0
    assert len(counting(db_session, env)) == 5 and registers(db_session, env) == {key}


def test_t29_a_column_read_added_to_the_register_duplicates_nothing_and_keeps_the_old_register(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T29 (b): the register gains a column NINFA reads ("Scadenza"): another register (another
    structure). The same costs are recognised by their content: nothing is duplicated. The costs
    re-observed KEEP the register that wrote them: a re-observation writes nothing (an unchanged
    record is never rewritten, and the rows are immutable), so their register cannot move."""
    key = first_register(api_client, env, db_session)
    content = with_column(REGISTER, "Scadenza", "2026-11-30")

    body = ask(api_client, env, content)
    assert {c["header"]: c["field"] for c in body["proposal"]["columns"]}["Scadenza"] == "due_date"
    result = imported(api_client, env, content, body)

    assert result["succeeded"] is True and result["created"] == 0 and result["unchanged"] == 5
    assert len(counting(db_session, env)) == 5
    assert registers(db_session, env) == {key}  # still the register that wrote them


def test_t30_a_complete_file_of_the_same_register_takes_away_exactly_the_missing_cost(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T30 (a): after T29 (a), complete without the cost of the 7th: exactly that one goes."""
    first_register(api_client, env, db_session)
    lacking = with_column([r for r in REGISTER if r[0] != "2026-10-07"], "Note", "verificato")

    body = ask(api_client, env, lacking, {"file_scope": "FULL"})

    assert body["understanding"]["removes"] == 1
    assert [item["supplier"] for item in body["understanding"]["removal_preview"]] == [
        "Lavanderia Salento"
    ]
    result = imported(api_client, env, lacking, body)
    assert result["removed"] == 1 and len(counting(db_session, env)) == 4


def test_t30_after_a_change_of_structure_a_complete_file_takes_away_less_never_more(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T30 (b), a known limit: after T29 (b) the costs belong to the OLD register, so a complete
    file with the new header takes away nothing - the missing cost keeps counting (less, never
    more). It is not asked what the file holds, because nothing would stop counting."""
    first_register(api_client, env, db_session)
    content = with_column(REGISTER, "Scadenza", "2026-11-30")
    imported(api_client, env, content, ask(api_client, env, content))
    lacking = with_column([r for r in REGISTER if r[0] != "2026-10-07"], "Scadenza", "2026-11-30")

    asked = ask(api_client, env, lacking)
    assert "FILE_SCOPE" not in kinds(asked)
    body = ask(api_client, env, lacking, {"file_scope": "FULL"})
    result = imported(api_client, env, lacking, body)

    assert body["understanding"]["removes"] == 0 and result["removed"] == 0
    assert len(counting(db_session, env)) == 5  # never more taken than the file's own register


# --- T33, T34: what a person is shown before a complete file takes costs away ----------------


def test_t33_the_costs_that_would_stop_counting_are_shown_one_by_one(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T33 (backend): date, supplier, category and amount of each, the same ones the import takes
    away, when it is asked and on the summary once said."""
    first_register(api_client, env, db_session)
    lacking = csv([r for r in REGISTER if r[0] not in ("2026-10-06", "2026-10-08")])

    asked = ask(api_client, env, lacking)
    assert kinds(asked) == ["FILE_SCOPE"]
    expected = [
        {
            "date": "2026-10-06",
            "supplier": "Acqua Salento",
            "category": "UTILITIES",
            "amount": "40.00",
            "currency": "EUR",
        },
        {
            "date": "2026-10-08",
            "supplier": "Gas Puglia",
            "category": "UTILITIES",
            "amount": "30.00",
            "currency": "EUR",
        },
    ]
    assert asked["understanding"]["removal_preview"] == expected
    assert asked["understanding"]["scope"]["removal_count"] == 2
    body = ask(api_client, env, lacking, {"file_scope": "FULL"})
    assert body["understanding"]["removes"] == 2
    assert body["understanding"]["removal_preview"] == expected
    assert imported(api_client, env, lacking, body)["removed"] == 2
    assert {r.invoice_date.isoformat() for r in counting(db_session, env)} == {
        "2026-10-05",
        "2026-10-07",
        "2026-10-09",
    }


def test_t33_at_most_twenty_are_listed_and_the_count_says_the_rest(
    api_client: TestClient, env: SourcesEnv
) -> None:
    month = [
        cost_row(
            day=f"2026-10-{day:02d}",
            supplier=f"Fornitore {day:02d}",
            description=f"Servizio del giorno {day}",
            net=f"{day}.00",
            tax="0.00",
            gross=f"{day}.00",
        )
        for day in range(1, 26)
    ]
    content = csv(month)
    imported(api_client, env, content, ask(api_client, env, content))
    ends = csv([month[0], month[1], month[23], month[24]])

    body = ask(api_client, env, ends, {"file_scope": "FULL"})

    u = body["understanding"]
    assert u["removes"] == 21 and u["scope"]["removal_count"] == 21
    assert len(u["removal_preview"]) == 20
    days = [item["date"] for item in u["removal_preview"]]
    assert days == sorted(days) and days[0] == "2026-10-03"


def test_t34_two_registers_with_the_same_header_are_one_register_and_the_preview_says_so(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """T34, a known limit (no change of logic): a laundry list and the utilities exported by the
    same program have the SAME header, so NINFA sees one register. A complete utilities file would
    take the laundry costs of those days away too - and the person is shown exactly which ones,
    supplier and category, before saying the file is complete."""
    laundry = [
        cost_row(
            day=f"2026-10-{day:02d}",
            supplier="Lavanderia Salento",
            category="LAUNDRY",
            description=f"Lavaggio {day}",
            net="55.00",
            tax="0.00",
            gross="55.00",
        )
        for day in (5, 6, 7)
    ]
    utilities = [
        *(r for r in REGISTER if r[2] == "UTILITIES"),  # the 5th, 6th and 8th
        cost_row(day="2026-10-09", supplier="Telecom", description="Telefono", net="20.00"),
    ]
    imported(api_client, env, csv(laundry), ask(api_client, env, csv(laundry)))
    body = ask(api_client, env, csv(utilities), {"file_scope": "PARTIAL"})
    assert imported(api_client, env, csv(utilities), body)["succeeded"] is True
    assert len(registers(db_session, env)) == 1  # one register: the same header

    without_gas = csv([utilities[0], utilities[1], utilities[3]])  # the 5th, 6th and 9th
    asked = ask(api_client, env, without_gas)

    assert kinds(asked) == ["FILE_SCOPE"]
    shown = asked["understanding"]["removal_preview"]
    assert [(i["date"], i["supplier"], i["category"]) for i in shown] == [
        ("2026-10-05", "Lavanderia Salento", "LAUNDRY"),
        ("2026-10-06", "Lavanderia Salento", "LAUNDRY"),
        ("2026-10-07", "Lavanderia Salento", "LAUNDRY"),
        ("2026-10-08", "Gas Puglia", "UTILITIES"),
    ]
    assert asked["understanding"]["scope"]["removal_count"] == 4
