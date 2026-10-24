"""Smart Import V3: a cost register in the accountant's own columns, into the SAME invoice model.

A register ("Numero documento, Data, Fornitore, Descrizione, Categoria, Imponibile, IVA, Totale")
is read through the invoice import that FatturaPA already uses: the same suppliers, the same cost
categories, the same classification. There is no second cost model. The one thing that is never
guessed is the AMOUNT: NINFA's analysis works with the net amount, and when nothing says that an
"Importo" is net, the person is asked - and "it includes VAT" is a plain "this cannot be imported
as it is".
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.models import Invoice, InvoiceLine, InvoiceMappingProfile
from app.modules.suppliers.models import Supplier
from tests import understanding_support as corpus
from tests.data_sources_support import SourcesEnv, card, sources_env
from tests.smart_import_support import (
    by_header,
    import_mapped,
    profiles_of,
    understand,
    validation,
    writes,
)
from tests.support import BookingFactory

COSTS = "COSTS"


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _kinds(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


def _import(client: TestClient, env: SourcesEnv, content: bytes, body: dict[str, Any]) -> Any:
    response = import_mapped(client, env, COSTS, "registro.xlsx", content, body["proposal"])
    assert response.status_code == 200, response.text
    return response.json()


def _count(db_session: Session, model: Any) -> int:
    return int(db_session.scalar(select(func.count()).select_from(model)) or 0)


# --- a register with net, VAT and total ----------------------------------------------------------


def test_a_register_with_net_vat_and_total_is_understood_with_no_question(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx()

    body = understand(api_client, env, COSTS, "registro.xlsx", content)

    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == []
    assert u["detection"]["domain"] == COSTS and u["detection"]["level"] == "HIGH"
    fields = {c["header"]: c["field"] for c in body["columns"]}
    assert fields == {
        "Numero documento": "invoice_number",
        "Data": "invoice_date",
        "Fornitore": "supplier_name",
        "Descrizione": "line_description",
        "Categoria": "cost_category",
        "Imponibile": "line_total",  # the NET amount is what NINFA works with
        "IVA": "invoice_tax_amount",
        "Totale": "invoice_gross_amount",
    }
    # net + VAT = total on every row: the three columns confirm each other
    assert u["document"]["amounts"] == "MATCH"
    sheets = {s["name"]: s["role"] for s in u["document"]["sheets"]}
    assert sheets == {"Registro acquisti": "DATA", "Riepilogo": "SUMMARY"}


def test_the_dry_run_adds_up_the_documents_from_the_validated_rows(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx()
    body = understand(api_client, env, COSTS, "registro.xlsx", content)

    tried = validation(api_client, env, COSTS, content, body["proposal"], name="registro.xlsx")

    assert tried["can_import"] is True and tried["rows_invalid"] == 0
    summary = tried["summary"]
    assert (summary["documents"], summary["suppliers"]) == (8, 4)
    assert Decimal(summary["net_total"]) == Decimal("10800.00")  # 1000 + ... + 1700
    assert (summary["date_from"], summary["date_to"]) == ("2026-10-03", "2026-10-10")


def test_the_register_is_imported_into_the_invoice_model_with_suppliers_and_categories(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx()
    body = understand(api_client, env, COSTS, "registro.xlsx", content)

    done = _import(api_client, env, content, body)

    assert done["succeeded"] is True and done["created"] == 8 and done["configuration_saved"]
    assert _count(db_session, Invoice) == 8 and _count(db_session, InvoiceLine) == 8
    assert _count(db_session, Supplier) == 4  # resolved by the existing supplier registry
    categories = {
        line.cost_category
        for line in db_session.scalars(
            select(InvoiceLine).where(InvoiceLine.workspace_id == env.workspace.id)
        )
    }
    # "Utenze", "Food", "Lavanderia", "Consulenze" are read into NINFA's own categories
    assert categories == {
        CostCategory.UTILITIES,
        CostCategory.FOOD,
        CostCategory.LAUNDRY,
        CostCategory.PROFESSIONAL_SERVICES,
    }
    assert card(api_client, env, "ACCOUNTING")["state"] != "NOT_CONFIGURED"


def test_the_next_register_is_recognised_and_asks_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    first = corpus.costs_register_xlsx(first_number=200)
    _import(api_client, env, first, understand(api_client, env, COSTS, "a.xlsx", first))

    second = corpus.costs_register_xlsx(first_number=300, with_summary_sheet=False)
    body = understand(api_client, env, COSTS, "novembre.xlsx", second)

    assert body["profile"]["status"] == "RECOGNIZED"
    assert body["understanding"]["level"] == "READY" and _kinds(body) == []
    assert (
        import_mapped(api_client, env, COSTS, "novembre.xlsx", second, None).json()["created"] == 8
    )
    assert _count(db_session, Invoice) == 16


def test_the_saved_configuration_holds_the_columns_and_the_category_words_never_the_values(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx()
    _import(api_client, env, content, understand(api_client, env, COSTS, "r.xlsx", content))

    (profile,) = profiles_of(db_session, env, InvoiceMappingProfile)

    assert profile.column_mapping["line_total"] == {"column": "Imponibile"}
    assert profile.category_mapping == {
        "utenze": "UTILITIES",
        "lavanderia": "LAUNDRY",
        "consulenze": "PROFESSIONAL_SERVICES",
    }
    stored = repr((profile.column_mapping, profile.category_mapping, profile.format_options))
    assert "Enel" not in stored and "FT-2" not in stored and "Bolletta" not in stored


def test_a_register_written_as_italian_excel_csv_asks_how_its_dates_are_written(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.costs_register_csv()  # 03/10/2026 ... 10/10/2026: 3 October, or 10 March?

    asked = understand(api_client, env, COSTS, "registro.csv", content)

    assert asked["understanding"]["level"] == "ASK" and _kinds(asked) == ["DATE_ORDER"]
    answered = understand(api_client, env, COSTS, "registro.csv", content, {"date_order": "DMY"})
    assert answered["understanding"]["level"] == "READY"
    assert answered["proposal"]["date_order"] == "DMY"
    response = import_mapped(api_client, env, COSTS, "registro.csv", content, answered["proposal"])
    assert response.status_code == 200 and response.json()["succeeded"] is True
    assert _count(db_session, Invoice) == 8


# --- the amount is never guessed -----------------------------------------------------------------


def test_an_amount_that_does_not_say_it_is_net_is_asked_about(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.costs_amount_only_xlsx()

    asked = understand(api_client, env, COSTS, "registro.xlsx", content)

    assert asked["understanding"]["level"] == "ASK" and _kinds(asked) == ["AMOUNT_BASIS"]
    question = asked["understanding"]["questions"][0]
    assert question["column"] == "Importo"
    assert {c["value"] for c in question["choices"]} == {"NET", "GROSS"}

    net = understand(api_client, env, COSTS, "registro.xlsx", content, {"amount_basis": "NET"})

    assert net["understanding"]["level"] == "READY" and _kinds(net) == []
    assert {c["header"]: c["field"] for c in net["columns"]}["Importo"] == "line_total"
    assert validation(api_client, env, COSTS, content, net["proposal"], name="r.xlsx")["can_import"]


def test_an_amount_that_includes_vat_cannot_be_imported_and_writes_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.costs_amount_only_xlsx()
    before = writes(db_session, env)

    body = understand(api_client, env, COSTS, "registro.xlsx", content, {"amount_basis": "GROSS"})

    understanding = body["understanding"]
    assert understanding["level"] == "BLOCKED"
    assert [b["code"] for b in understanding["blockers"]] == ["AMOUNT_NOT_NET"]
    assert understanding["questions"] == []
    assert writes(db_session, env) == before
    assert _count(db_session, Invoice) == 0


def test_the_columns_that_add_up_settle_which_amount_is_net_without_asking(
    api_client: TestClient, env: SourcesEnv
) -> None:
    # "Importo" + "IVA" = "Totale" on every row: Importo is the net amount, and the file says so
    header = ["Numero fattura", "Data", "Fornitore", "Descrizione", "Importo", "IVA", "Totale"]
    rows: list[list[object]] = [list(header)]
    for index in range(6):
        net = 500.0 + 10 * index
        rows.append(
            [
                f"A{index}",
                f"0{index + 1}/10/2026",
                "Enel Energia",
                "Bolletta",
                net,
                round(net * 0.22, 2),
                round(net * 1.22, 2),
            ]
        )

    body = understand(api_client, env, COSTS, "registro.csv", corpus.csv_of(rows))

    fields = {c["header"]: c["field"] for c in body["columns"]}
    assert fields["Importo"] == "line_total" and fields["Totale"] == "invoice_gross_amount"
    assert body["understanding"]["document"]["amounts"] == "MATCH"
    assert "AMOUNT_BASIS" not in _kinds(body)


def test_a_total_that_does_not_match_net_plus_vat_is_reported_not_hidden(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = understand(
        api_client, env, COSTS, "registro.xlsx", corpus.costs_register_xlsx(wrong_total=True)
    )

    assert body["understanding"]["document"]["amounts"] == "MISMATCH"
    assert by_header(body)["Imponibile"]["field"] == "line_total"


# --- what a register cannot be imported without -------------------------------------------------


def test_a_register_without_a_description_says_so_instead_of_inventing_one(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx(with_description=False)
    before = writes(db_session, env)

    body = understand(api_client, env, COSTS, "registro.xlsx", content)

    understanding = body["understanding"]
    (blocker,) = understanding["blockers"]
    assert blocker["code"] == "MISSING_REQUIRED" and ["line_description"] in blocker["groups"]
    assert understanding["level"] == "MANUAL"
    assert (
        validation(api_client, env, COSTS, content, body["proposal"], name="r.xlsx")["can_import"]
        is False
    )
    assert writes(db_session, env) == before


# --- category words ------------------------------------------------------------------------------


def test_a_category_word_nobody_knows_is_asked_once_and_remembered(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx(unknown_category=True)

    asked = understand(api_client, env, COSTS, "registro.xlsx", content)

    assert asked["understanding"]["level"] == "ASK" and _kinds(asked) == ["VALUE_LABELS"]
    question = asked["understanding"]["questions"][0]
    assert question["document"] == "category_mapping"
    assert [(item["label"], item["count"]) for item in question["labels"]] == [("Boh???", 1)]
    # untaught, the dry run refuses that row instead of calling it "OTHER"
    tried = validation(api_client, env, COSTS, content, asked["proposal"], name="r.xlsx")
    assert tried["can_import"] is False
    assert tried["row_problems"] == [
        {"field": "cost_category", "code": "UNKNOWN_CATEGORY", "count": 1}
    ]
    assert [q["document"] for q in tried["questions"]] == ["category_mapping"]

    taught = understand(
        api_client,
        env,
        COSTS,
        "registro.xlsx",
        content,
        {"labels": {"category_mapping": {"Boh???": "MARKETING"}}},
    )

    assert taught["understanding"]["level"] == "READY"
    assert _import(api_client, env, content, taught)["succeeded"] is True
    (profile,) = profiles_of(db_session, env, InvoiceMappingProfile)
    assert profile.category_mapping["boh"] == "MARKETING"
    again = understand(api_client, env, COSTS, "registro-dopo.xlsx", content)
    assert again["profile"]["status"] == "RECOGNIZED" and _kinds(again) == []


def test_a_word_taught_for_one_hotel_is_not_known_by_another(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx(unknown_category=True)
    taught = understand(
        api_client,
        env,
        COSTS,
        "r.xlsx",
        content,
        {"labels": {"category_mapping": {"Boh???": "OTHER"}}},
    )
    _import(api_client, env, content, taught)
    sister = SourcesEnv(env.workspace, factory.property(env.workspace), env.user)

    other = understand(api_client, sister, COSTS, "r.xlsx", content)

    assert other["profile"]["status"] == "NONE" and _kinds(other) == ["VALUE_LABELS"]


# --- the other kinds of file ---------------------------------------------------------------------


def test_a_staff_file_chosen_as_costs_is_asked_about(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content, _ = corpus.staff_simple_xlsx()

    body = understand(api_client, env, COSTS, "turni.xlsx", content)

    question = next(q for q in body["understanding"]["questions"] if q["kind"] == "DOMAIN")
    assert question["candidate"] == "LABOR"


def test_a_cost_register_chosen_as_staff_or_bookings_is_asked_about(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.costs_register_xlsx()

    for domain in ("LABOR", "BOOKINGS"):
        body = understand(api_client, env, domain, "registro.xlsx", content)
        question = next(q for q in body["understanding"]["questions"] if q["kind"] == "DOMAIN")
        assert question["candidate"] == COSTS


def test_understanding_a_register_writes_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    before = writes(db_session, env)

    understand(api_client, env, COSTS, "registro.xlsx", corpus.costs_register_xlsx())
    understand(api_client, env, COSTS, "registro.xlsx", corpus.costs_amount_only_xlsx())

    assert writes(db_session, env) == before
    assert _count(db_session, Invoice) == 0 and _count(db_session, Supplier) == 0


def test_an_amount_such_as_1_234_is_asked_about_never_guessed(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [
        ["Numero fattura", "Data", "Fornitore", "Descrizione", "Imponibile"]
    ]
    rows += [
        [f"A{i}", f"2026-10-0{i + 1}", "Enel Energia", "Bolletta", "1,234"] for i in range(6)
    ]  # one thousand two hundred thirty-four, or one point two three four?
    content = corpus.csv_of(rows)

    asked = understand(api_client, env, COSTS, "registro.csv", content)

    assert asked["understanding"]["level"] == "ASK" and _kinds(asked) == ["DECIMAL_STYLE"]

    answered = understand(
        api_client, env, COSTS, "registro.csv", content, {"decimal_style": "COMMA"}
    )

    assert answered["understanding"]["level"] == "READY"
    tried = validation(api_client, env, COSTS, content, answered["proposal"], name="registro.csv")
    assert tried["can_import"] is True
    assert Decimal(tried["summary"]["net_total"]) == Decimal("7.38")  # six times 1,234 -> 1.23 each
