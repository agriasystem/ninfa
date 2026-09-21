"""The FatturaPA XML reader (Gate 6 group G), pure: no database involved. Synthetic data only."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.invoices.documents import ParsedDocument
from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError, WarningCode
from app.modules.invoices.fatturapa import MAX_XML_BYTES, parse_fatturapa
from app.modules.invoices.models import DocumentKind, SourceFormat
from tests.invoice_support import (
    IBAN_A,
    IBAN_B,
    RECIPIENT_NAME,
    RECIPIENT_TAX_CODE,
    SUPPLIER_EMAIL,
    SUPPLIER_PHONE,
    SUPPLIER_STREET,
    Body,
    Cedente,
    Line,
    Payment,
    fattura_xml,
)

D = Decimal


def only(content: bytes) -> ParsedDocument:
    documents = parse_fatturapa(content)
    assert len(documents) == 1
    return documents[0]


def codes(document: ParsedDocument) -> list[str]:
    return [item.issue.code.value for item in document.located_issues()]


# --- versions, structure and namespaces ---------------------------------------------------------


def test_a_standard_private_invoice_fpr12_is_read() -> None:
    body = Body(
        number="FA/12",
        date="2026-03-10",
        lines=[
            Line(1, "Lavanderia biancheria", "100.00", quantity="10", unit="kg", unit_price="10"),
            Line(2, "Trasporto", "20.00"),
        ],
        total="146.40",
    )

    document = only(fattura_xml([body]))

    assert document.valid and document.canonical is not None
    canonical = document.canonical
    assert canonical.invoice_number == "FA/12" and canonical.invoice_date == date(2026, 3, 10)
    assert canonical.document_kind == DocumentKind.INVOICE and canonical.currency == "EUR"
    assert canonical.source_format == SourceFormat.FATTURAPA_XML
    assert (canonical.net_amount, canonical.tax_amount, canonical.gross_amount) == (
        D("120.00"),
        D("26.40"),
        D("146.40"),
    )
    assert [(line.source_line_number, line.line_total) for line in canonical.lines] == [
        (1, D("100.00")),
        (2, D("20.00")),
    ]
    first = canonical.lines[0]
    assert (first.quantity, first.unit, first.unit_price, first.vat_rate) == (
        D("10"),
        "kg",
        D("10"),
        D("22.00"),
    )


def test_a_public_administration_invoice_fpa12_is_read() -> None:
    document = only(fattura_xml([Body()], version="FPA12"))
    assert document.valid


def test_element_names_are_matched_without_regard_to_the_namespace_prefix() -> None:
    plain = only(fattura_xml([Body(number="7")]))
    prefixed = only(fattura_xml([Body(number="7")], prefix="p:"))
    bare = only(fattura_xml([Body(number="7")], namespace=False))
    for document in (plain, prefixed, bare):
        assert document.canonical is not None
        assert document.canonical.invoice_number == "7"
    assert plain.canonical is not None and prefixed.canonical is not None
    assert plain.canonical.fingerprint("s") == prefixed.canonical.fingerprint("s")


def test_an_xml_that_is_not_a_fatturapa_is_refused_with_a_stable_code() -> None:
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(b'<?xml version="1.0"?><Ordine><Riga/></Ordine>')
    assert error.value.error_code == InvoiceErrorCode.UNSUPPORTED_FATTURAPA
    assert error.value.details == {"reason": "not_fatturapa"}


def test_other_format_versions_are_refused() -> None:
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(fattura_xml([Body()], version="FSM10"))
    assert error.value.error_code == InvoiceErrorCode.UNSUPPORTED_FATTURAPA
    assert (
        error.value.details is not None and error.value.details["reason"] == "unsupported_version"
    )


def test_a_fatturapa_without_a_supplier_or_a_body_is_refused() -> None:
    header_only = (
        b'<?xml version="1.0"?><FatturaElettronica versione="FPR12">'
        b"<FatturaElettronicaHeader/></FatturaElettronica>"
    )
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(header_only)
    assert error.value.error_code == InvoiceErrorCode.UNSUPPORTED_FATTURAPA
    assert error.value.details == {"reason": "missing_structure"}


def test_malformed_xml_is_unreadable_not_a_crash() -> None:
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(b"<FatturaElettronica versione='FPR12'><oops>")
    assert error.value.error_code == InvoiceErrorCode.UNREADABLE_FILE


# --- supplier -----------------------------------------------------------------------------------


def test_the_supplier_comes_from_the_cedente_prestatore_only() -> None:
    document = only(fattura_xml([Body()], cedente=Cedente(name="Rossi Food S.r.l.")))

    assert document.canonical is not None
    supplier = document.canonical.supplier
    assert supplier.legal_name == "Rossi Food S.r.l."
    assert supplier.normalized_name == "rossi food srl"
    assert supplier.vat_number == "IT01234567890" and supplier.country == "IT"
    assert supplier.tax_code is None and supplier.iban_sha256 == ()


def test_vat_number_and_tax_code_are_both_read() -> None:
    document = only(fattura_xml([Body()], cedente=Cedente(tax_code="rssmra80a01h501u")))
    assert document.canonical is not None
    assert document.canonical.supplier.vat_number == "IT01234567890"
    assert document.canonical.supplier.tax_code == "RSSMRA80A01H501U"


def test_a_sole_trader_is_named_from_first_and_last_name() -> None:
    cedente = Cedente(
        name=None, vat=None, tax_code="RSSMRA80A01H501U", first_name="Mario", last_name="Rossi"
    )
    document = only(fattura_xml([Body()], cedente=cedente))
    assert document.canonical is not None
    assert document.canonical.supplier.legal_name == "Mario Rossi"
    assert document.canonical.supplier.vat_number is None
    assert document.canonical.supplier.tax_code == "RSSMRA80A01H501U"


def test_a_foreign_supplier_is_supported_without_an_italian_checksum() -> None:
    cedente = Cedente(name="Beispiel GmbH", vat="123456789", country="DE")  # IdPaese=DE
    document = only(fattura_xml([Body()], cedente=cedente))
    assert document.canonical is not None
    assert document.canonical.supplier.vat_number == "DE123456789"
    assert document.canonical.supplier.country == "DE"


def test_an_italian_vat_number_with_the_wrong_length_is_invalid() -> None:
    document = only(fattura_xml([Body()], cedente=Cedente(vat="123")))
    assert not document.valid
    assert codes(document) == [InvoiceErrorCode.INVALID_VAT_NUMBER.value]


def test_a_supplier_without_a_name_is_invalid() -> None:
    document = only(fattura_xml([Body()], cedente=Cedente(name=None)))
    assert not document.valid
    assert InvoiceErrorCode.REQUIRED_VALUE_MISSING.value in codes(document)


# --- multi-body -------------------------------------------------------------------------------


def test_each_body_of_a_multi_body_file_is_a_separate_document_of_the_same_supplier() -> None:
    bodies = [
        Body(number="1", date="2026-03-01", lines=[Line(1, "Prima", "10.00")]),
        Body(number="2", date="2026-03-02", type_code="TD04", lines=[Line(1, "Seconda", "5.00")]),
        Body(
            number="3",
            date="2026-03-03",
            lines=[Line(1, "Terza", "7.00"), Line(2, "Extra", "1.00")],
        ),
    ]

    documents = parse_fatturapa(fattura_xml(bodies))

    assert [d.index for d in documents] == [1, 2, 3]
    assert all(d.valid and d.canonical is not None for d in documents)
    canonicals = [d.canonical for d in documents if d.canonical is not None]
    assert [c.invoice_number for c in canonicals] == ["1", "2", "3"]
    assert [c.document_kind for c in canonicals] == [
        DocumentKind.INVOICE,
        DocumentKind.CREDIT_NOTE,
        DocumentKind.INVOICE,
    ]
    assert len({c.supplier.key for c in canonicals}) == 1
    assert [len(c.lines) for c in canonicals] == [1, 1, 2]


def test_one_invalid_body_does_not_make_the_others_invalid() -> None:
    bodies = [Body(number="1"), Body(number="2", date="not-a-date"), Body(number="3")]
    documents = parse_fatturapa(fattura_xml(bodies))
    assert [d.valid for d in documents] == [True, False, True]
    assert InvoiceErrorCode.INVALID_DATE.value in codes(documents[1])


# --- credit notes -----------------------------------------------------------------------------


@pytest.mark.parametrize("type_code", ["TD04", "TD08"])
def test_credit_notes_td04_and_td08_become_negative_credit_notes(type_code: str) -> None:
    body = Body(
        number="NC1", type_code=type_code, lines=[Line(1, "Storno", "100.00")], total="122.00"
    )

    document = only(fattura_xml([body]))

    assert document.canonical is not None
    canonical = document.canonical
    assert canonical.document_kind == DocumentKind.CREDIT_NOTE
    assert canonical.document_type_code == type_code
    assert canonical.lines[0].line_total == D("-100.00")
    assert (canonical.net_amount, canonical.tax_amount, canonical.gross_amount) == (
        D("-100.00"),
        D("-22.00"),
        D("-122.00"),
    )


def test_a_debit_note_and_the_other_supported_types_are_invoices() -> None:
    for type_code in ("TD01", "TD02", "TD03", "TD05", "TD06", "TD24"):
        document = only(fattura_xml([Body(type_code=type_code)]))
        assert document.canonical is not None
        assert document.canonical.document_kind == DocumentKind.INVOICE, type_code


def test_document_types_that_swap_supplier_and_buyer_are_not_supported() -> None:
    document = only(fattura_xml([Body(type_code="TD17")]))
    assert not document.valid
    assert codes(document) == [InvoiceErrorCode.UNSUPPORTED_DOCUMENT_TYPE.value]


# --- due dates --------------------------------------------------------------------------------


def test_one_distinct_due_date_is_kept() -> None:
    body = Body(payments=[Payment(due="2026-04-10"), Payment(due="2026-04-10")])
    document = only(fattura_xml([body]))
    assert document.canonical is not None
    assert document.canonical.due_date == date(2026, 4, 10)
    assert document.warnings == []


def test_several_due_dates_leave_the_due_date_null_with_a_warning() -> None:
    body = Body(payments=[Payment(due="2026-04-10"), Payment(due="2026-05-10")])
    document = only(fattura_xml([body]))
    assert document.valid and document.canonical is not None
    assert document.canonical.due_date is None  # never one "representative" date
    assert [w.code for w in document.warnings] == [WarningCode.MULTIPLE_PAYMENT_DUE_DATES]


def test_no_payment_data_means_no_due_date_and_no_warning() -> None:
    document = only(fattura_xml([Body()]))
    assert document.canonical is not None and document.canonical.due_date is None
    assert document.warnings == []


# --- IBAN: hashed at the boundary, never kept ---------------------------------------------------


def test_the_payment_iban_is_hashed_and_the_raw_value_goes_nowhere() -> None:
    document = only(fattura_xml([Body(payments=[Payment(due="2026-04-10", iban=IBAN_A)])]))

    assert document.canonical is not None
    expected = hashlib.sha256(IBAN_A.encode()).hexdigest()
    assert document.canonical.supplier.iban_sha256 == (expected,)
    assert IBAN_A not in repr(document)  # nowhere in the parsed document, staged form included
    assert IBAN_A not in repr(document.mapped_header)
    assert expected in repr(document.mapped_header)


def test_an_iban_written_with_spaces_hashes_the_same() -> None:
    spaced = "IT60 X054 2811 1010 0000 0123 456"
    one = only(fattura_xml([Body(payments=[Payment(iban=IBAN_A)])]))
    two = only(fattura_xml([Body(payments=[Payment(iban=spaced)])]))
    assert one.canonical is not None and two.canonical is not None
    assert one.canonical.supplier.iban_sha256 == two.canonical.supplier.iban_sha256


def test_an_invalid_iban_is_ignored_with_a_warning_and_never_echoed() -> None:
    bad = "IT00X0000000000000000000000"
    document = only(fattura_xml([Body(payments=[Payment(iban=bad)])]))
    assert document.valid and document.canonical is not None
    assert document.canonical.supplier.iban_sha256 == ()
    assert [w.code for w in document.warnings] == [WarningCode.INVALID_IBAN_IGNORED]
    assert bad not in repr(document)


def test_an_iban_of_another_beneficiary_does_not_identify_the_supplier() -> None:
    body = Body(payments=[Payment(iban=IBAN_B, beneficiary="Factoring Fittizio S.p.A.")])
    document = only(fattura_xml([body]))
    assert document.canonical is not None and document.canonical.supplier.iban_sha256 == ()
    assert [w.code for w in document.warnings] == [WarningCode.BENEFICIARY_IBAN_IGNORED]


def test_an_iban_whose_beneficiary_is_the_supplier_is_used() -> None:
    body = Body(payments=[Payment(iban=IBAN_A, beneficiary="FORNITORE FITTIZIO SRL")])
    document = only(fattura_xml([body]))
    assert document.canonical is not None and len(document.canonical.supplier.iban_sha256) == 1


# --- data minimisation ------------------------------------------------------------------------


def test_recipient_address_phone_and_email_never_reach_the_parsed_documents() -> None:
    document = only(fattura_xml([Body(payments=[Payment(iban=IBAN_A)])]))

    surfaces = repr(document) + repr(document.canonical)
    for private in (
        RECIPIENT_NAME,
        RECIPIENT_TAX_CODE,
        SUPPLIER_EMAIL,
        SUPPLIER_PHONE,
        SUPPLIER_STREET,
        "cliente-pec@example.com",
        "Perugia",
        "06121",
        "JVBERi0xLjQKJSVFT0Y=",  # the embedded attachment
        "copia.pdf",
    ):
        assert private not in surfaces, private


def test_the_supplier_country_comes_from_the_office_when_the_vat_has_none() -> None:
    xml = fattura_xml([Body()]).replace(
        b"<IdPaese>IT</IdPaese><IdCodice>01234567890", b"<IdCodice>01234567890"
    )
    document = only(xml)
    assert document.canonical is not None
    assert document.canonical.supplier.country == "IT"
    assert document.canonical.supplier.vat_number == "IT01234567890"


# --- missing or invalid data --------------------------------------------------------------------


def test_an_xml_with_missing_required_data_is_invalid_and_says_which_fields() -> None:
    content = fattura_xml([Body()])
    for tag, field in (
        (b"Numero", "invoice_number"),
        (b"Data", "invoice_date"),
        (b"Divisa", "currency"),
        (b"TipoDocumento", "document_type"),
    ):
        broken = content.replace(b"<" + tag + b">", b"<X" + tag + b">").replace(
            b"</" + tag + b">", b"</X" + tag + b">"
        )
        document = only(broken)
        assert not document.valid, tag
        assert field in {item.issue.field for item in document.located_issues()}, tag


def test_a_body_without_lines_is_invalid() -> None:
    document = only(fattura_xml([Body(lines=[])]))
    assert not document.valid
    assert InvoiceErrorCode.NO_LINES.value in codes(document)


def test_a_line_without_a_total_or_a_description_is_invalid() -> None:
    content = fattura_xml([Body(lines=[Line(1, "Servizio", "10.00")])])
    no_total = content.replace(b"<PrezzoTotale>10.00</PrezzoTotale>", b"")
    no_description = content.replace(b"<Descrizione>Servizio</Descrizione>", b"")
    assert InvoiceErrorCode.REQUIRED_VALUE_MISSING.value in codes(only(no_total))
    assert InvoiceErrorCode.REQUIRED_VALUE_MISSING.value in codes(only(no_description))


def test_a_duplicate_line_number_is_invalid() -> None:
    body = Body(lines=[Line(1, "Uno", "1.00"), Line(1, "Due", "2.00")])
    document = only(fattura_xml([body]))
    assert not document.valid
    assert codes(document).count(InvoiceErrorCode.DUPLICATE_LINE.value) == 2


def test_an_amount_with_too_many_decimals_is_refused_not_rounded() -> None:
    document = only(fattura_xml([Body(lines=[Line(1, "Servizio", "1.123456789")])]))
    assert not document.valid
    assert InvoiceErrorCode.AMOUNT_PRECISION.value in codes(document)


def test_eight_decimals_are_accepted_and_rounded_once_at_the_end() -> None:
    body = Body(
        lines=[Line(1, "Servizio", "20.00500000", quantity="1.00000000", unit_price="20.005")]
    )
    document = only(fattura_xml([body]))
    assert document.canonical is not None
    assert document.canonical.lines[0].line_total == D("20.01")  # HALF_UP, once
    assert document.canonical.lines[0].unit_price == D("20.005")  # the unit price is not rounded


def test_an_unknown_currency_is_invalid() -> None:
    document = only(fattura_xml([Body(currency="XXX")]))
    assert InvoiceErrorCode.INVALID_CURRENCY.value in codes(document)


# --- XML security ------------------------------------------------------------------------------

BILLION_LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
    "<FatturaElettronica versione='FPR12'>&b;</FatturaElettronica>"
)
EXTERNAL_ENTITY = (
    '<?xml version="1.0"?><!DOCTYPE f [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    "<FatturaElettronica versione='FPR12'>&xxe;</FatturaElettronica>"
)


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, EXTERNAL_ENTITY])
def test_a_doctype_or_entity_is_rejected_with_a_security_code(payload: str) -> None:
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(payload.encode())
    assert error.value.error_code == InvoiceErrorCode.XML_SECURITY_REJECTED
    assert "passwd" not in error.value.message


def test_a_doctype_inside_an_otherwise_valid_invoice_is_rejected() -> None:
    content = fattura_xml([Body()], doctype='<!DOCTYPE FatturaElettronica [<!ENTITY e "x">]>')
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(content)
    assert error.value.error_code == InvoiceErrorCode.XML_SECURITY_REJECTED


def test_a_doctype_is_rejected_in_a_utf16_document_too() -> None:
    utf16 = ('<?xml version="1.0" encoding="UTF-16"?>' + EXTERNAL_ENTITY.split("?>", 1)[1]).encode(
        "utf-16"
    )
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(utf16)
    assert error.value.error_code == InvoiceErrorCode.XML_SECURITY_REJECTED


def test_an_undefined_entity_is_not_expanded() -> None:
    escaped = fattura_xml([Body(lines=[Line(1, "Servizio &undefined;", "1.00")])])
    content = escaped.replace(b"&amp;undefined;", b"&undefined;")  # a raw, undeclared entity
    assert b"&undefined;" in content
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(content)
    assert error.value.error_code == InvoiceErrorCode.UNREADABLE_FILE


def test_an_xml_beyond_the_size_limit_is_refused_before_parsing() -> None:
    with pytest.raises(InvoiceImportError) as error:
        parse_fatturapa(b"<a>" + b"x" * MAX_XML_BYTES + b"</a>")
    assert error.value.error_code == InvoiceErrorCode.FILE_LIMIT_EXCEEDED


def test_the_reader_uses_the_standard_library_parser_and_no_custom_parser() -> None:
    import app.modules.invoices.fatturapa as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "xml.etree.ElementTree" in source
    assert "defusedxml" not in source and "lxml" not in source
