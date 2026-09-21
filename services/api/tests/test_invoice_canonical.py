"""The canonical invoice, pure (Gate 6 groups D, E, F): signs, amounts, lines, classification."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.invoices.canonical import (
    RawDocument,
    RawLine,
    canonicalize,
    document_multiplier,
    normalize_description,
    normalize_invoice_number,
    plain,
    to_money,
)
from app.modules.invoices.classification import (
    CLASSIFICATION_VERSION,
    RULES,
    classify_line,
    matching_categories,
)
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory
from app.modules.invoices.models import DocumentKind, SourceFormat
from app.modules.suppliers.resolution import SupplierEvidence

D = Decimal
SUPPLIER = SupplierEvidence.build(
    legal_name="Fornitore Fittizio S.r.l.", vat_number="IT01234567890"
)


def document(
    kind: DocumentKind,
    lines: list[str],
    *,
    net: str | None = None,
    tax: str | None = None,
    gross: str | None = None,
    number: str = "1",
) -> RawDocument:
    return RawDocument(
        source_document_index=1,
        supplier=SUPPLIER,
        invoice_number=number,
        invoice_date=date(2026, 3, 10),
        document_kind=kind,
        currency="EUR",
        lines=tuple(RawLine(i, f"riga {i}", D(total)) for i, total in enumerate(lines, start=1)),
        source_format=SourceFormat.FATTURAPA_XML,
        net_amount=None if net is None else D(net),
        tax_amount=None if tax is None else D(tax),
        gross_amount=None if gross is None else D(gross),
    )


# --- D: signed monetary semantics ------------------------------------------------------------


def test_a_standard_invoice_keeps_the_amounts_of_the_source() -> None:
    canonical = canonicalize(
        document(
            DocumentKind.INVOICE, ["100.00", "50.00"], net="150.00", tax="33.00", gross="183.00"
        )
    )
    assert [line.line_total for line in canonical.lines] == [D("100.00"), D("50.00")]
    assert (canonical.net_amount, canonical.tax_amount, canonical.gross_amount) == (
        D("150.00"),
        D("33.00"),
        D("183.00"),
    )


def test_a_credit_note_written_with_positive_amounts_becomes_negative() -> None:
    canonical = canonicalize(
        document(
            DocumentKind.CREDIT_NOTE, ["100.00", "50.00"], net="150.00", tax="33.00", gross="183.00"
        )
    )
    assert [line.line_total for line in canonical.lines] == [D("-100.00"), D("-50.00")]
    assert (canonical.net_amount, canonical.tax_amount, canonical.gross_amount) == (
        D("-150.00"),
        D("-33.00"),
        D("-183.00"),
    )


def test_a_credit_note_already_written_negative_is_not_negated_twice() -> None:
    canonical = canonicalize(
        document(
            DocumentKind.CREDIT_NOTE,
            ["-100.00", "-50.00"],
            net="-150.00",
            tax="-33.00",
            gross="-183.00",
        )
    )
    assert [line.line_total for line in canonical.lines] == [D("-100.00"), D("-50.00")]
    assert canonical.gross_amount == D("-183.00")


def test_the_sign_of_a_credit_note_follows_its_headline_amount_even_with_a_discount_line() -> None:
    positive = canonicalize(document(DocumentKind.CREDIT_NOTE, ["100.00", "-10.00"], gross="90.00"))
    assert [line.line_total for line in positive.lines] == [D("-100.00"), D("10.00")]
    already = canonicalize(document(DocumentKind.CREDIT_NOTE, ["-100.00", "10.00"], gross="-90.00"))
    assert [line.line_total for line in already.lines] == [D("-100.00"), D("10.00")]


def test_the_headline_amount_falls_back_from_gross_to_net_to_the_lines() -> None:
    assert document_multiplier(DocumentKind.CREDIT_NOTE, None, D("10"), [D("-5")]) == -1
    assert document_multiplier(DocumentKind.CREDIT_NOTE, None, None, [D("5"), D("5")]) == -1
    assert document_multiplier(DocumentKind.CREDIT_NOTE, None, None, [D("-5")]) == 1
    assert document_multiplier(DocumentKind.CREDIT_NOTE, D("0"), None, [D("0")]) == 1
    assert document_multiplier(DocumentKind.INVOICE, D("-5"), None, []) == 1


def test_header_amounts_share_one_sign_with_the_lines() -> None:
    canonical = canonicalize(
        document(DocumentKind.CREDIT_NOTE, ["80.00"], net="80.00", tax="17.60")
    )
    assert canonical.net_amount == D("-80.00") and canonical.tax_amount == D("-17.60")
    assert canonical.lines[0].line_total == D("-80.00")
    assert canonical.gross_amount is None  # an amount the source did not state is not invented


def test_simplified_credit_notes_use_the_same_sign_rule() -> None:
    canonical = canonicalize(document(DocumentKind.CREDIT_NOTE, ["12.30"], gross="12.30"))
    assert canonical.lines[0].line_total == D("-12.30") and canonical.gross_amount == D("-12.30")


# --- E: lines and amounts ------------------------------------------------------------------------


def test_money_is_quantised_once_half_up_after_the_sign() -> None:
    assert to_money(D("20.005")) == D("20.01")
    assert to_money(D("-20.005")) == D("-20.01")  # half up, away from zero
    assert to_money(D("20.0049")) == D("20.00")
    canonical = canonicalize(document(DocumentKind.CREDIT_NOTE, ["20.005"], gross="20.005"))
    assert canonical.lines[0].line_total == D("-20.01") and canonical.gross_amount == D("-20.01")


def test_line_amounts_are_decimals_never_floats() -> None:
    canonical = canonicalize(document(DocumentKind.INVOICE, ["0.10", "0.20"]))
    assert all(isinstance(line.line_total, Decimal) for line in canonical.lines)
    assert sum(line.line_total for line in canonical.lines) == D("0.30")  # not 0.30000000000000004


def test_an_amount_beyond_the_column_is_refused() -> None:
    with pytest.raises(ValueError):
        to_money(D("100000000000.00"))


def test_optional_line_fields_stay_null() -> None:
    line = canonicalize(document(DocumentKind.INVOICE, ["10.00"])).lines[0]
    assert (line.quantity, line.unit, line.unit_price, line.vat_rate) == (None, None, None, None)


def test_the_source_line_number_is_kept() -> None:
    canonical = canonicalize(document(DocumentKind.INVOICE, ["1.00", "2.00", "3.00"]))
    assert [line.source_line_number for line in canonical.lines] == [1, 2, 3]


def test_description_normalisation_is_deterministic() -> None:
    assert (
        normalize_description("  Lavanderia — Biancheria (Hôtel)!  ")
        == "lavanderia biancheria hotel"
    )
    assert normalize_description("LAVANDERIA biancheria HOTEL") == "lavanderia biancheria hotel"
    assert normalize_description("a") == normalize_description("A")


def test_invoice_numbers_are_normalised_conservatively() -> None:
    assert normalize_invoice_number("  fa 12/2026 ") == "FA 12/2026"
    assert normalize_invoice_number("123/A") == "123/A"  # not "123A"
    assert normalize_invoice_number("12-3") == "12-3"  # not "123"
    assert normalize_invoice_number("a  b") == "A B"  # whitespace collapsed
    assert normalize_invoice_number("１２３") == "123"  # compatibility form
    assert normalize_invoice_number("123/A") != normalize_invoice_number("123A")


def test_plain_text_makes_equal_numbers_equal() -> None:
    assert plain(D("1.50")) == plain(D("1.5")) == "1.5"
    assert plain(D("0.000")) == "0" and plain(None) is None


def test_the_fingerprint_is_stable_and_covers_the_canonical_content_only() -> None:
    base = canonicalize(document(DocumentKind.INVOICE, ["100.00"], net="100.00"))
    same = canonicalize(document(DocumentKind.INVOICE, ["100.00"], net="100.00"))
    assert base.fingerprint("s1") == same.fingerprint("s1")
    assert base.fingerprint("s1") != base.fingerprint("s2")  # another supplier
    other_amount = canonicalize(document(DocumentKind.INVOICE, ["100.01"], net="100.00"))
    assert base.fingerprint("s1") != other_amount.fingerprint("s1")
    # technical and analytical details do not change it
    from dataclasses import replace

    relabelled = replace(
        base, source_document_index=9, due_date=date(2026, 4, 1), document_type_code="TD01"
    )
    assert base.fingerprint("s1") == relabelled.fingerprint("s1")
    categorised = replace(
        base, lines=tuple(replace(line, explicit_category=CostCategory.FOOD) for line in base.lines)
    )
    assert base.fingerprint("s1") == categorised.fingerprint("s1")


def test_the_reconciliation_is_a_diagnostic_never_a_requirement() -> None:
    canonical = canonicalize(document(DocumentKind.INVOICE, ["100.00", "50.00"], net="151.00"))
    diagnostics = canonical.reconciliation()
    assert (diagnostics.line_net_sum, diagnostics.document_net_amount) == (D("150.00"), D("151.00"))
    assert diagnostics.reconciliation_delta == D("1.00")
    assert (
        canonicalize(document(DocumentKind.INVOICE, ["1.00"])).reconciliation().reconciliation_delta
        is None
    )


# --- F: cost categories and classification -------------------------------------------------------


def test_there_are_fourteen_canonical_categories() -> None:
    assert {c.value for c in CostCategory} == {
        "PERSONNEL",
        "LAUNDRY",
        "CLEANING",
        "AMENITIES",
        "FOOD",
        "BEVERAGE",
        "UTILITIES",
        "MAINTENANCE",
        "SOFTWARE",
        "MARKETING",
        "OTA_COMMISSIONS",
        "PROFESSIONAL_SERVICES",
        "TRANSPORT",
        "OTHER",
    }


def test_an_explicit_source_category_wins_with_confidence_100() -> None:
    result = classify_line(
        normalize_description("Lavanderia"),
        explicit=CostCategory.FOOD,
        supplier_default=CostCategory.SOFTWARE,
    )
    assert (result.category, result.confidence, result.method) == (
        CostCategory.FOOD,
        D("100.00"),
        ClassificationMethod.EXPLICIT_SOURCE,
    )


def test_the_supplier_default_comes_second_with_confidence_90() -> None:
    result = classify_line("qualunque cosa", supplier_default=CostCategory.MAINTENANCE)
    assert (result.category, result.confidence, result.method) == (
        CostCategory.MAINTENANCE,
        D("90.00"),
        ClassificationMethod.SUPPLIER_DEFAULT,
    )


@pytest.mark.parametrize(
    ("description", "category"),
    [
        ("Servizio di lavanderia biancheria camere", CostCategory.LAUNDRY),
        ("Noleggio biancheria e linen service", CostCategory.LAUNDRY),
        ("Fornitura energia elettrica marzo", CostCategory.UTILITIES),
        ("Fornitura gas naturale", CostCategory.UTILITIES),
        ("Canone software gestionale", CostCategory.SOFTWARE),
        ("Abbonamento SaaS", CostCategory.SOFTWARE),
        ("Commissione Booking.com marzo", CostCategory.OTA_COMMISSIONS),
        ("Servizio di pulizia camere", CostCategory.CLEANING),
        ("Manutenzione caldaia", CostCategory.MAINTENANCE),
    ],
)
def test_a_deterministic_rule_classifies_a_clear_description(
    description: str, category: CostCategory
) -> None:
    result = classify_line(normalize_description(description))
    assert (result.category, result.confidence, result.method) == (
        category,
        D("80.00"),
        ClassificationMethod.DETERMINISTIC_RULE,
    )


def test_an_unknown_description_is_other_with_confidence_zero() -> None:
    result = classify_line(normalize_description("Materiale vario"))
    assert (result.category, result.confidence, result.method) == (
        CostCategory.OTHER,
        D("0.00"),
        ClassificationMethod.UNCLASSIFIED,
    )


def test_an_ambiguous_description_is_not_guessed() -> None:
    description = normalize_description("Lavanderia e pulizie camere")
    assert set(matching_categories(description)) == {CostCategory.LAUNDRY, CostCategory.CLEANING}
    result = classify_line(description)
    assert (result.category, result.method) == (
        CostCategory.OTHER,
        ClassificationMethod.UNCLASSIFIED,
    )


def test_a_phrase_matches_whole_words_only() -> None:
    assert classify_line("softwarehouse arredi").method == ClassificationMethod.UNCLASSIFIED
    assert classify_line("gasolio").method == ClassificationMethod.UNCLASSIFIED


def test_the_rule_dictionary_is_small_and_versioned() -> None:
    assert CLASSIFICATION_VERSION == "cost-classification-v1"
    assert sum(len(phrases) for phrases in RULES.values()) < 40
    assert set(RULES) <= set(CostCategory) - {CostCategory.OTHER}


def test_classification_uses_no_ai_and_no_fuzzy_matching() -> None:
    import app.modules.invoices.classification as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for word in ("openai", "anthropic", "embedding", "difflib", "SequenceMatcher", "llm"):
        assert word.lower() not in source.lower(), word
