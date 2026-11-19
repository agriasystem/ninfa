"""Operating costs with no document number (ADR 0057): identity, multiset, scope and safety.

A cost register with no invoice number is imported without inventing one: the number stays NULL and
NINFA identifies each record by its content, inside the data source it came from, numbered among its
identical siblings. The tests below are the contract of that identity:

  A  a cost WITH a document number behaves as it always did
  B  without one, it imports (after the person said these are operating costs) with a NULL number
  C  the same file again is a no-op            D  the same rows in another order too
  E  two identical rows are two costs          F  from 2 identical rows to 3 creates only the third
  G  FULL, 3 -> 2, takes one away              H  PARTIAL takes nothing   I  DELTA takes nothing
  J  a changed amount: replaced under FULL, never inferred otherwise
  K  two data sources never merge              L  a FatturaPA without a number still fails
  M  the internal key is never a number        P  nothing personal is kept
"""

import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ingestion.models import DataSourceDomain, ImportJob, ImportJobStatus
from app.modules.intelligence.costs.repository import CostLineRepository
from app.modules.invoices.canonical import RECORD_KEY_VERSION, record_key
from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError
from app.modules.invoices.mapping import InvoiceMappingConfig
from app.modules.invoices.models import (
    IdentityOrigin,
    Invoice,
    InvoiceImportRow,
    InvoiceLine,
    InvoiceRemoval,
    SourceFormat,
)
from tests.booking_support import csv_bytes
from tests.invoice_support import Body, CostWorld, fattura_xml, persisted_hits, standard_csv
from tests.operational_costs_support import (
    OPERATIONAL_COLUMNS,
    OPERATIONAL_HEADERS,
    SYNTHETIC,
    all_records,
    confirm_operational,
    cost_row,
    current_records,
    delta,
    full,
    import_costs,
    operational_csv,
    partial,
    removals,
)
from tests.support import BookingFactory

KEY = re.compile(r"^cost:v1:[0-9a-f]{64}#[1-9][0-9]*$")
API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"
CONTRACTS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "src" / "index.ts"

X = cost_row()  # a utility bill
Y = cost_row(day="2026-10-06", supplier="Acqua Salento", description="Acqua ottobre", net="40.00")
Z = cost_row(
    supplier="Acqua Salento", description="Acqua ottobre", net="40.00"
)  # the same day as X
W = cost_row(day="2026-10-07", supplier="Lavanderia Salento", description="Lavanderia", net="55.00")


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    """A COSTS source whose confirmed mapping says: operating costs, no document number."""
    costs = CostWorld.create(db_session, factory)
    confirm_operational(costs)
    return costs


def counted(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- A. a cost with a document number keeps its identity ----------------------------------------


def test_a_cost_with_a_document_number_keeps_its_historical_identity(
    db_session: Session, factory: BookingFactory
) -> None:
    costs = CostWorld.create(db_session, factory)
    costs.confirm()
    row = {
        "supplier_name": "Fornitore Uno",
        "invoice_number": "fa/1",
        "invoice_date": "2026-03-10",
        "line_description": "Servizio",
        "line_total": "100.00",
    }

    first = costs.import_rows([row])
    again = costs.import_rows([row])

    assert first.succeeded and first.invoices_created == 1
    assert again.invoices_unchanged == 1 and again.invoices_created == 0
    [invoice] = costs.invoices()
    assert invoice.invoice_number == "fa/1" and invoice.normalized_invoice_number == "FA/1"
    assert invoice.source_record_key == "FA/1"  # the key IS the number: nothing changed
    assert invoice.identity_origin == IdentityOrigin.DOCUMENT_NUMBER


def test_a_corrected_row_of_a_numbered_document_is_still_the_next_revision(
    db_session: Session, factory: BookingFactory
) -> None:
    costs = CostWorld.create(db_session, factory)
    costs.confirm()
    row = {
        "supplier_name": "Fornitore Uno",
        "invoice_number": "FA/1",
        "invoice_date": "2026-03-10",
        "line_description": "Servizio",
        "line_total": "100.00",
    }
    costs.import_rows([row])

    corrected = costs.import_rows([{**row, "line_total": "110.00"}])

    assert corrected.invoices_revised == 1 and corrected.records_removed == 0
    assert sorted(i.revision for i in costs.invoices()) == [1, 2]


# --- B. without a number: imported once a person said so -------------------------------------


def test_without_a_number_and_without_the_persons_word_the_mapping_is_refused(
    db_session: Session, factory: BookingFactory
) -> None:
    """Nothing is ever made up on the importer's own initiative."""
    costs = CostWorld.create(db_session, factory)

    with pytest.raises(InvoiceImportError) as refused:
        costs.confirm(headers=OPERATIONAL_HEADERS, columns=OPERATIONAL_COLUMNS)

    assert refused.value.code == InvoiceErrorCode.INVALID_MAPPING


def test_an_operating_cost_is_imported_with_no_number_and_a_technical_key(
    db_session: Session, world: CostWorld
) -> None:
    result = import_costs(world, [X, Y])

    assert result.succeeded and result.invoices_created == 2 and result.rows_invalid == 0
    records = all_records(db_session, world)
    assert len(records) == 2 and counted(db_session, InvoiceLine) == 2
    for record in records:
        assert record.invoice_number is None and record.normalized_invoice_number is None
        assert record.identity_origin == IdentityOrigin.SYNTHETIC_COST_RECORD
        assert record.source_format == SourceFormat.CSV
        assert KEY.match(record.source_record_key)
        assert record.revision == 1
    assert len({r.source_record_key for r in records}) == 2  # two different costs, two keys


def test_the_cost_keeps_what_the_register_says_and_nothing_else(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X])

    [record] = all_records(db_session, world)
    [line] = db_session.scalars(select(InvoiceLine)).all()
    assert str(line.line_total) == "100.00" and line.description_raw == X[3]
    assert str(record.tax_amount) == "22.00" and str(record.gross_amount) == "122.00"
    assert record.invoice_date.isoformat() == "2026-10-05"
    assert line.cost_category.value == "UTILITIES"


# --- C. the same file again; D. the same rows in another order --------------------------------


def test_the_same_file_again_changes_nothing(db_session: Session, world: CostWorld) -> None:
    import_costs(world, [X, Y])

    again = import_costs(world, [X, Y])

    assert again.succeeded
    assert again.invoices_created == 0 and again.invoices_unchanged == 2
    assert again.records_removed == 0 and not again.changed_data
    assert len(all_records(db_session, world)) == 2


def test_the_same_rows_in_another_order_are_the_same_records(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, Y, X])
    before = sorted(r.source_record_key for r in all_records(db_session, world))

    reordered = import_costs(world, [X, X, Y])

    assert reordered.invoices_created == 0 and reordered.invoices_unchanged == 3
    assert sorted(r.source_record_key for r in all_records(db_session, world)) == before


# --- E, F. identical rows are a multiset ---------------------------------------------------------


def test_two_identical_rows_are_two_costs(db_session: Session, world: CostWorld) -> None:
    result = import_costs(world, [X, X])

    assert result.succeeded and result.invoices_created == 2
    first, second = sorted(r.source_record_key for r in all_records(db_session, world))
    assert first.rsplit("#", 1)[0] == second.rsplit("#", 1)[0]  # the same content...
    assert (first.rsplit("#", 1)[1], second.rsplit("#", 1)[1]) == ("1", "2")  # ...counted twice
    assert counted(db_session, InvoiceLine) == 2


def test_from_two_identical_rows_to_three_only_the_third_is_new(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X])
    before = {r.id for r in all_records(db_session, world)}

    grown = import_costs(world, [X, X, X])

    assert grown.invoices_created == 1 and grown.invoices_unchanged == 2
    records = all_records(db_session, world)
    assert len(records) == 3
    assert [r.id for r in records if r.id not in before] != []
    assert sorted(r.source_record_key.rsplit("#", 1)[1] for r in records) == ["1", "2", "3"]


# --- G, H, I. what a file says about the records it does not hold ------------------------------


def test_a_complete_file_with_fewer_identical_rows_takes_away_one_only(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X, X])

    result = import_costs(world, [X, X], scope=full(1))

    assert result.succeeded and result.records_removed == 1 and result.changed_data
    assert len(all_records(db_session, world)) == 3  # the invoices are never touched
    assert len(current_records(db_session, world)) == 2  # what counts
    [removal] = removals(db_session, world)
    assert removal.identity_origin == IdentityOrigin.SYNTHETIC_COST_RECORD


@pytest.mark.parametrize(("name", "scope"), [("PARTIAL", partial()), ("DELTA", delta())])
def test_a_part_of_the_period_or_only_the_news_takes_nothing_away(
    db_session: Session, world: CostWorld, name: str, scope: object
) -> None:
    import_costs(world, [X, X, X])

    result = import_costs(world, [X, X], scope=scope)  # type: ignore[arg-type]

    assert result.succeeded and result.records_removed == 0, name
    assert len(current_records(db_session, world)) == 3
    assert removals(db_session, world) == []


def test_with_no_word_about_the_file_absence_means_nothing(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X, X])

    result = import_costs(world, [X])  # no scope at all: a cost register may always be partial

    assert result.records_removed == 0 and len(current_records(db_session, world)) == 3


def test_a_complete_file_only_takes_away_what_is_inside_the_period_it_covers(
    db_session: Session, world: CostWorld
) -> None:
    november = cost_row(day="2026-11-05", description="Energia elettrica novembre")
    import_costs(world, [X, Y, W, november])

    # a file of ONE day says nothing about the days it does not cover, complete as it is
    one_day = import_costs(world, [X], scope=full(0))
    assert one_day.records_removed == 0 and len(current_records(db_session, world)) == 4

    # a file from the 5th to the 7th that lacks the cost of the 6th takes that one only
    result = import_costs(world, [X, W], scope=full(1))

    assert result.records_removed == 1
    survivors = current_records(db_session, world)
    assert sorted(s.invoice_date.isoformat() for s in survivors) == [
        "2026-10-05",
        "2026-10-07",
        "2026-11-05",
    ]


def test_what_a_complete_file_would_take_away_is_checked_again_when_it_does(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X, X])

    result = import_costs(world, [X, X], scope=full(5))  # the person was shown 5, the truth is 1

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == InvoiceErrorCode.IMPORT_PLAN_CHANGED
    assert len(current_records(db_session, world)) == 3 and removals(db_session, world) == []


def test_the_preview_of_what_would_go_writes_nothing(db_session: Session, world: CostWorld) -> None:
    import_costs(world, [X, X, X])
    config = InvoiceMappingConfig.parse(
        {
            "column_mapping": OPERATIONAL_COLUMNS,
            "format_options": dict(SYNTHETIC),
        }
    )
    jobs, records = counted(db_session, ImportJob), len(all_records(db_session, world))

    gone = world.service().records_a_complete_file_would_remove(
        world.source.id,
        world.tenant.property.id,
        filename="costi.csv",
        content=operational_csv([X, X]),
        mapping=config,
    )

    assert gone == 1
    assert counted(db_session, ImportJob) == jobs
    assert len(all_records(db_session, world)) == records and removals(db_session, world) == []


def test_a_record_that_comes_back_counts_again_as_the_next_revision(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X, X])
    import_costs(world, [X, X], scope=full(1))

    back = import_costs(world, [X, X, X])

    assert back.records_restored == 1 and back.invoices_created == 0 and back.changed_data
    assert len(current_records(db_session, world)) == 3
    revisions = sorted(r.revision for r in all_records(db_session, world))
    assert revisions == [1, 1, 1, 2]  # the removed one stays, with the next revision beside it


# --- J. a changed amount ----------------------------------------------------------------------


def test_a_changed_amount_is_replaced_when_a_person_said_the_file_is_complete(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X])
    changed = cost_row(net="120.00", tax="26.40", gross="146.40")

    result = import_costs(world, [changed], scope=full(1))

    assert result.invoices_created == 1 and result.records_removed == 1
    [current] = current_records(db_session, world)
    assert str(current.gross_amount) == "146.40"
    assert len(all_records(db_session, world)) == 2  # the old observation stays as history


def test_a_changed_amount_is_never_inferred_to_be_a_correction(
    db_session: Session, world: CostWorld
) -> None:
    """No document number, no scope: nobody can say the new row is the same cost, so both count."""
    import_costs(world, [X])
    changed = cost_row(net="120.00", tax="26.40", gross="146.40")

    result = import_costs(world, [changed], scope=partial())

    assert result.invoices_created == 1 and result.records_removed == 0
    assert len(current_records(db_session, world)) == 2


# --- K. two sources never merge -----------------------------------------------------------------


def second_source(db_session: Session, factory: BookingFactory, world: CostWorld) -> CostWorld:
    other = CostWorld(
        db_session, world.tenant, factory.data_source(world.tenant.property, DataSourceDomain.COSTS)
    )
    confirm_operational(other)
    return other


def test_the_same_cost_in_two_sources_is_two_costs(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    other = second_source(db_session, factory, world)

    import_costs(world, [X])
    again = import_costs(other, [X])

    assert again.invoices_created == 1 and again.invoices_unchanged == 0
    keys = {r.source_record_key for r in all_records(db_session, world)}
    assert len(keys) == 2  # the data source is inside the identity: nothing merged silently


def test_a_complete_file_of_one_source_never_takes_away_the_costs_of_another(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    other = second_source(db_session, factory, world)
    import_costs(world, [X, Z])
    import_costs(other, [X, Z])

    result = import_costs(world, [X], scope=full(1))

    assert result.records_removed == 1
    current = current_records(db_session, world)
    assert len(current) == 3
    assert [r.data_source_id for r in current].count(other.source.id) == 2


# --- L. a fiscal document keeps needing its number --------------------------------------------


def test_a_fatturapa_without_a_number_still_fails(db_session: Session, world: CostWorld) -> None:
    xml = fattura_xml([Body(number="X1")]).replace(b"<Numero>X1</Numero>", b"")

    result = world.import_xml(xml, name="fattura.xml")

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == InvoiceErrorCode.VALIDATION_FAILED
    assert counted(db_session, Invoice) == 0


def test_a_register_of_documents_cannot_borrow_the_synthetic_identity(
    db_session: Session, factory: BookingFactory
) -> None:
    """A type, a due date or a line number make a file document-level: the number stays required."""
    for extra, column in (
        ("document_type", "Tipo"),
        ("due_date", "Scadenza"),
        ("line_number", "N"),
    ):
        costs = CostWorld.create(db_session, factory)
        with pytest.raises(InvoiceImportError) as refused:
            costs.confirm(
                headers=[*OPERATIONAL_HEADERS, column],
                columns={**OPERATIONAL_COLUMNS, extra: {"column": column}},
                format_options=dict(SYNTHETIC),
            )
        assert refused.value.code == InvoiceErrorCode.INVALID_MAPPING, extra


def test_a_mapping_with_a_document_number_cannot_also_say_there_is_none(
    db_session: Session, factory: BookingFactory
) -> None:
    costs = CostWorld.create(db_session, factory)

    with pytest.raises(InvoiceImportError) as refused:
        costs.confirm(
            headers=[*OPERATIONAL_HEADERS, "Numero"],
            columns={**OPERATIONAL_COLUMNS, "invoice_number": {"column": "Numero"}},
            format_options=dict(SYNTHETIC),
        )

    assert refused.value.code == InvoiceErrorCode.INVALID_MAPPING


def test_a_synthetic_record_is_never_a_fatturapa_whatever_the_file(
    db_session: Session, world: CostWorld
) -> None:
    """An XML reads its own number: a mapping that says operating costs does not apply to it."""
    result = world.import_xml(fattura_xml([Body(number="Z9")]), name="fattura.xml")

    assert result.succeeded  # an XML reads its own number: the mapping does not apply to it
    [record] = all_records(db_session, world)
    assert (
        record.identity_origin == IdentityOrigin.DOCUMENT_NUMBER and record.invoice_number == "Z9"
    )


# --- M. the internal key is never presented as a number ----------------------------------------


def test_no_invented_number_is_ever_stored(db_session: Session, world: CostWorld) -> None:
    import_costs(world, [X, X, Y])

    assert (
        db_session.scalar(
            select(func.count()).select_from(Invoice).where(Invoice.invoice_number.is_not(None))
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.normalized_invoice_number.is_not(None))
        )
        == 0
    )
    for row in db_session.scalars(select(InvoiceImportRow)):
        assert "invoice_number" not in row.mapped_payload
        header = (row.normalized_payload or {}).get("header") or {}
        assert header.get("invoice_number") is None
    assert persisted_hits(db_session, ["NINFA-", "INTERNAL-"]) == []  # no made-up reference


def test_the_internal_key_appears_in_no_surface_a_person_reads() -> None:
    surfaces = [*API_DIR.rglob("*.py"), CONTRACTS]
    for path in surfaces:
        text = path.read_text(encoding="utf-8")
        for word in ("source_record_key", "identity_origin", "cost:v1", "SYNTHETIC_COST_RECORD"):
            if path == CONTRACTS and word == "SYNTHETIC_COST_RECORD":
                continue  # the person's own answer travels as that word, never as a number
            assert word not in text, f"{path.name} shows {word}"


def test_a_stored_key_keeps_meaning_what_it_meant() -> None:
    """The identity is versioned: a change of what the content holds is a NEW version."""
    assert RECORD_KEY_VERSION == 1
    assert record_key("f" * 64, 3) == "cost:v1:" + "f" * 64 + "#3"


# --- P. nothing personal is kept --------------------------------------------------------------


def test_a_column_nobody_mapped_is_never_stored(db_session: Session, world: CostWorld) -> None:
    content = csv_bytes(
        [[*OPERATIONAL_HEADERS, "Referente"], [*X, "Mario Rossi mario@example.com"]]
    )

    result = world.service().import_file(world.source.id, filename="costi.csv", content=content)

    assert result.succeeded
    assert persisted_hits(db_session, ["Mario Rossi", "mario@example.com"]) == []


def test_the_key_is_a_hash_and_carries_no_value_of_the_file(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X])

    [record] = all_records(db_session, world)
    assert X[3].lower() not in record.source_record_key.lower()
    assert "enel" not in record.source_record_key.lower()


# --- the removals never reach a document with a number -----------------------------------------


def test_a_complete_file_never_takes_away_a_real_invoice(
    db_session: Session, factory: BookingFactory
) -> None:
    costs = CostWorld.create(db_session, factory)
    costs.confirm()
    row = {
        "supplier_name": "Fornitore Uno",
        "invoice_date": "2026-03-10",
        "line_description": "Servizio",
        "line_total": "100.00",
    }
    costs.import_rows([{**row, "invoice_number": "FA/1"}, {**row, "invoice_number": "FA/2"}])

    result = costs.service().import_file(
        costs.source.id,
        filename="costs.csv",
        content=standard_csv([{**row, "invoice_number": "FA/1"}]),
        scope=full(1),
    )

    assert result.succeeded and result.records_removed == 0
    assert counted(db_session, InvoiceRemoval) == 0
    assert len(costs.invoices()) == 2  # FA/2 is still there: absence never removes a real invoice


# --- the analysis does not depend on the number ------------------------------------------------


def october(costs: CostWorld, db_session: Session) -> list[tuple[object, ...]]:
    """What the cost analysis reads of October: month, currency, category, sums and counts."""
    aggregates = CostLineRepository(db_session, costs.context).monthly_aggregates(
        costs.tenant.property.id, date(2026, 10, 1), date(2026, 10, 31)
    )
    return [
        (
            a.month,
            a.currency,
            a.cost_category,
            a.net_cost,
            a.absolute_cost,
            a.confidence_weighted_cost,
            a.invoice_count,
            a.line_count,
            a.credit_note_line_count,
        )
        for a in aggregates
    ]


def test_an_operating_cost_counts_exactly_like_the_same_cost_with_a_number(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    numbered = CostWorld.create(db_session, factory)
    numbered.confirm()
    rows = [X, Y, W]
    import_costs(world, rows)
    numbered.import_rows(
        [
            {
                "supplier_name": row[1],
                "invoice_number": f"FA/{index}",
                "invoice_date": row[0],
                "line_description": row[3],
                "line_total": row[4],
                "cost_category": row[2],
            }
            for index, row in enumerate(rows, start=1)
        ]
    )

    assert october(world, db_session) == october(numbered, db_session)
    assert october(world, db_session) != []


def test_a_cost_a_complete_file_took_away_no_longer_counts_in_the_analysis(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, Y, W])
    before = october(world, db_session)

    import_costs(world, [X, W], scope=full(1))

    after = october(world, db_session)
    assert sum(row[7] for row in before) == 3 and sum(row[7] for row in after) == 2
    assert sum(row[3] for row in after) == sum(row[3] for row in before) - 40  # (Y: 40.00 net)


def test_a_record_that_comes_back_counts_again_in_the_analysis(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, Y, W])
    import_costs(world, [X, W], scope=full(1))

    import_costs(world, [X, Y, W])

    assert sum(row[7] for row in october(world, db_session)) == 3
