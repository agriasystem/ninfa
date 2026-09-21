"""Only authorised data reaches the canonical model (Gate 6 group I, FatturaPA side).

The source carries a supplier e-mail, phone and street address, the recipient's name, tax code and
address, the PEC, an embedded attachment and a raw IBAN. Every table of the schema, the logs, the
results and the errors are scanned: none of it may appear, while the authorised data (and the
SHA-256 of the IBAN) does.
"""

import hashlib
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.invoices.models import InvoiceImportRow
from app.modules.suppliers.models import IdentifierKind, Supplier, SupplierIdentifier
from tests.invoice_support import (
    IBAN_A,
    RECIPIENT_NAME,
    RECIPIENT_TAX_CODE,
    SUPPLIER_EMAIL,
    SUPPLIER_PHONE,
    SUPPLIER_STREET,
    Body,
    Cedente,
    CostWorld,
    Line,
    Payment,
    fattura_xml,
    job_of,
    persisted_hits,
)
from tests.support import BookingFactory

# Never persisted, never logged. (Short numeric codes such as a postal code are left out on purpose:
# a random UUID could contain them and make the scan flaky; the parser tests cover them.)
FORBIDDEN = [
    RECIPIENT_NAME,
    "Cliente Fittizia",
    RECIPIENT_TAX_CODE,
    SUPPLIER_EMAIL,
    "fornitore-fittizio.example",
    SUPPLIER_PHONE,
    "5550101",
    SUPPLIER_STREET,
    "Via Inventata",
    "Via del Cliente",
    "cliente-pec@example.com",
    "Perugia",
    "JVBERi0xLjQKJSVFT0Y=",
    "copia.pdf",
    IBAN_A,
    "IT60X054",
    "0542811101",
    "<FatturaElettronica",
    "DatiTrasmissione",
    "CessionarioCommittente",
    "xmlns",
]
DIGEST = hashlib.sha256(IBAN_A.encode()).hexdigest()


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    return CostWorld.create(db_session, factory)


def rich_xml(**cedente: str) -> bytes:
    body = Body(
        number="PII-1",
        lines=[Line(1, "Servizio lavanderia", "80.00")],
        payments=[Payment(due="2026-04-10", iban=IBAN_A, beneficiary="Fornitore Fittizio S.r.l.")],
    )
    return fattura_xml([body], cedente=Cedente(tax_code="RSSMRA80A01H501U", **cedente))


def test_the_source_really_contains_everything_that_must_not_be_stored() -> None:
    xml = rich_xml().decode()
    for needle in FORBIDDEN:
        assert needle in xml or needle in {"IT60X054", "0542811101", "Cliente Fittizia"}, needle
    assert IBAN_A in xml and SUPPLIER_EMAIL in xml and RECIPIENT_NAME in xml


def test_no_table_holds_the_recipient_the_contacts_the_address_or_the_raw_iban(
    world: CostWorld, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    result = world.import_xml(rich_xml())

    assert result.succeeded
    assert persisted_hits(world.session, FORBIDDEN) == []  # in ANY table
    assert not [needle for needle in FORBIDDEN if needle in caplog.text]  # nor in any log
    assert not [needle for needle in FORBIDDEN if needle in repr(result)]


def test_control_the_authorised_data_and_the_iban_hash_are_where_they_belong(
    world: CostWorld,
) -> None:
    """Proves the scan can see data: what MAY be stored is found."""
    world.import_xml(rich_xml())

    assert ("suppliers", "Fornitore Fittizio S.r.l.") in persisted_hits(
        world.session, ["Fornitore Fittizio S.r.l."]
    )
    assert ("supplier_identifiers", "IT01234567890") in persisted_hits(
        world.session, ["IT01234567890"]
    )
    tables = {table for table, _ in persisted_hits(world.session, [DIGEST])}
    assert {"supplier_identifiers", "invoice_import_rows"} <= tables  # the hash, not the account
    assert "invoices" not in tables and "suppliers" not in tables


def test_only_the_authorised_supplier_data_is_canonical(world: CostWorld) -> None:
    world.import_xml(rich_xml())

    supplier = world.session.scalars(select(Supplier)).one()
    assert (supplier.legal_name, supplier.country, supplier.is_verified) == (
        "Fornitore Fittizio S.r.l.",
        "IT",
        False,
    )
    identifiers = {
        (i.kind, i.normalized_value) for i in world.session.scalars(select(SupplierIdentifier))
    }
    assert identifiers == {
        (IdentifierKind.VAT_NUMBER, "IT01234567890"),
        (IdentifierKind.TAX_CODE, "RSSMRA80A01H501U"),
        (IdentifierKind.IBAN_SHA256, DIGEST),
    }
    assert {c.name for c in Supplier.__table__.columns}.isdisjoint(
        {"email", "phone", "address", "pec", "iban", "contact_person"}
    )


def test_the_recipient_never_enters_the_model_and_is_not_matched_to_a_customer(
    world: CostWorld,
) -> None:
    world.import_xml(rich_xml())

    assert world.session.scalars(select(Supplier.legal_name)).all() == ["Fornitore Fittizio S.r.l."]
    assert persisted_hits(world.session, [RECIPIENT_NAME, RECIPIENT_TAX_CODE]) == []


def test_staged_rows_hold_only_mapped_and_canonical_values(world: CostWorld) -> None:
    result = world.import_xml(rich_xml())

    rows = world.session.scalars(
        select(InvoiceImportRow).where(InvoiceImportRow.import_job_id == result.import_job_id)
    ).all()
    header_keys = {
        "supplier_name",
        "supplier_vat_number",
        "supplier_tax_code",
        "supplier_iban_sha256",
        "invoice_number",
        "invoice_date",
        "due_date",
        "document_type",
        "currency",
        "invoice_net_amount",
        "invoice_tax_amount",
        "invoice_gross_amount",
    }
    line_keys = {
        "line_number",
        "line_description",
        "quantity",
        "unit",
        "unit_price",
        "line_total",
        "vat_rate",
    }
    for row in rows:
        assert set(row.mapped_payload) <= header_keys | line_keys
        payload = row.normalized_payload or {}
        assert set(payload) <= {"header", "line"}
    first = rows[0].mapped_payload
    assert first["supplier_iban_sha256"] == [DIGEST]  # only the hash, as a list of hashes
    assert IBAN_A not in str(first)


def test_a_failed_xml_import_leaks_nothing_either(
    world: CostWorld, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    bad = fattura_xml(
        [Body(number="PII-2", date="2026-99-99", payments=[Payment(iban=IBAN_A)])],
        cedente=Cedente(tax_code="RSSMRA80A01H501U"),
    )

    result = world.import_xml(bad)

    assert not result.succeeded
    surfaces = [repr(result), caplog.text, str(job_of(world.session, result).error_message)]
    surfaces += [
        str(r.validation_errors) + str(r.mapped_payload)
        for r in world.session.scalars(select(InvoiceImportRow))
    ]
    joined = "\n".join(surfaces)
    assert not [needle for needle in FORBIDDEN if needle in joined]
    assert persisted_hits(world.session, FORBIDDEN) == []


def test_a_rejected_dangerous_xml_does_not_echo_its_content(world: CostWorld) -> None:
    payload = (
        b'<?xml version="1.0"?><!DOCTYPE f [<!ENTITY x SYSTEM "file:///etc/passwd">]><f>&x;</f>'
    )

    result = world.import_xml(payload)

    assert result.error_code == "INVOICE_XML_SECURITY_REJECTED"
    assert "passwd" not in repr(result) and "passwd" not in str(
        job_of(world.session, result).error_message
    )
    assert persisted_hits(world.session, ["passwd", "ENTITY"]) == []


def test_the_iban_of_a_third_party_beneficiary_is_neither_stored_nor_used(
    world: CostWorld,
) -> None:
    body = Body(payments=[Payment(iban=IBAN_A, beneficiary="Factoring Terzo S.p.A.")])

    result = world.import_xml(fattura_xml([body]))

    assert result.succeeded and result.warning_summary == {"BENEFICIARY_IBAN_IGNORED": 1}
    assert persisted_hits(world.session, [IBAN_A, DIGEST, "Factoring Terzo"]) == []


def test_the_canonical_fingerprint_does_not_depend_on_the_pii_around_the_document(
    world: CostWorld,
) -> None:
    """Two files that differ only in personal data are the same canonical invoice."""
    base = fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "10.00")])])
    changed = (
        base.replace(SUPPLIER_EMAIL.encode(), b"altro@x.example")
        .replace(SUPPLIER_STREET.encode(), b"Via Diversa 1")
        .replace(RECIPIENT_NAME.encode(), b"Un Altro Cliente")
    )
    assert changed != base

    first = world.import_xml(base)
    second = world.import_xml(changed, name="altro.xml")

    assert first.succeeded and second.succeeded
    assert (second.invoices_created, second.invoices_unchanged) == (0, 1)
