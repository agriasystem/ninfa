"""What the three importers read from the TEXT of a cell: a weekday before a date, the hotel's
currency next to an amount (Smart Import V3 hardening).

The importers stay strict - a date is read by the pattern the person confirmed, an amount by the
separators the person confirmed - and the only new thing is that a weekday name in front of a date
and "EUR" / "€" next to an amount are not part of the value. A weekday that does not belong to the
date, and any other currency, are still refused.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.bookings.mapping import CanonicalField
from app.modules.bookings.normalization import (
    _FieldError,  # noqa: PLC2701 - the error a refused value raises
    parse_amount,
    parse_date_value,
)
from app.modules.invoices import structured as invoices
from app.modules.invoices.mapping import InvoiceField, InvoiceMappingConfig
from app.modules.labor import structured as labor
from app.modules.labor.mapping import LaborField, LaborMappingConfig
from tests.booking_support import make_config, make_context

THURSDAY = date(2026, 10, 29)

_BOOKINGS = make_context(
    make_config(
        format_options={
            "date_formats": {"check_in": "%d/%m/%Y"},
            "decimal_separator": ",",
            "thousands_separator": ".",
        }
    )
)
_LABOR = LaborMappingConfig.model_validate(
    {
        "column_mapping": {
            "work_date": {"column": "Giorno"},
            "role": {"column": "Reparto"},
            "planned_hours": {"column": "Ore"},
        },
        "format_options": {
            "date_formats": {"work_date": "%d/%m/%Y"},
            "decimal_separator": ",",
            "thousands_separator": ".",
        },
    }
)
_INVOICES = InvoiceMappingConfig.model_validate(
    {
        "column_mapping": {
            "supplier_name": {"column": "Fornitore"},
            "invoice_number": {"column": "N."},
            "invoice_date": {"column": "Data"},
            "line_description": {"column": "Descrizione"},
            "line_total": {"column": "Imponibile"},
        },
        "format_options": {
            "date_formats": {"invoice_date": "%d/%m/%Y"},
            "decimal_separator": ",",
            "thousands_separator": ".",
        },
    }
)

WRITTEN = [
    "gio 29/10/2026",
    "Giovedì 29/10/2026",
    "Thu 29/10/2026",
    "gio. 29/10/2026",
    "29/10/2026",
]


@pytest.mark.parametrize("text", WRITTEN)
def test_bookings_read_a_date_with_its_weekday(text: str) -> None:
    assert parse_date_value(CanonicalField.CHECK_IN, text, _BOOKINGS) == THURSDAY


@pytest.mark.parametrize("text", WRITTEN)
def test_labor_reads_a_date_with_its_weekday(text: str) -> None:
    assert labor._date(text, LaborField.WORK_DATE, _LABOR) == THURSDAY


@pytest.mark.parametrize("text", WRITTEN)
def test_invoices_read_a_date_with_its_weekday(text: str) -> None:
    assert invoices._date(text, InvoiceField.INVOICE_DATE, _INVOICES) == THURSDAY


@pytest.mark.parametrize("text", ["lun 29/10/2026", "Sunday 29/10/2026"])
def test_a_weekday_that_is_not_the_dates_is_refused_by_all_three(text: str) -> None:
    with pytest.raises(_FieldError):
        parse_date_value(CanonicalField.CHECK_IN, text, _BOOKINGS)
    with pytest.raises(labor._BadValueError):
        labor._date(text, LaborField.WORK_DATE, _LABOR)
    with pytest.raises(invoices._BadValueError):
        invoices._date(text, InvoiceField.INVOICE_DATE, _INVOICES)


@pytest.mark.parametrize("text", ["gio 2026-10-29", "gio 31/02/2026"])
def test_a_weekday_does_not_make_an_impossible_date_possible(text: str) -> None:
    with pytest.raises(_FieldError):
        parse_date_value(CanonicalField.CHECK_IN, text, _BOOKINGS)


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("1.250,00 EUR", "1250.00"),
        ("850 EUR", "850.00"),
        ("€ 1.250,50", "1250.50"),
        ("850 euro", "850.00"),
    ],
)
def test_bookings_read_an_amount_with_the_currency(text: str, amount: str) -> None:
    assert parse_amount(CanonicalField.ROOM_REVENUE, text, _BOOKINGS) == Decimal(amount)


@pytest.mark.parametrize(
    ("text", "amount"), [("1.250,00 EUR", "1250.00"), ("850 EUR", "850"), ("€ 12,5", "12.5")]
)
def test_invoices_and_labor_read_an_amount_with_the_currency(text: str, amount: str) -> None:
    assert invoices._parse_decimal_text(text, _INVOICES) == Decimal(amount)
    assert labor._parse_decimal_text(text, _LABOR) == Decimal(amount)


@pytest.mark.parametrize("text", ["850 USD", "$ 850", "850 GBP"])
def test_another_currency_is_not_read_as_euros(text: str) -> None:
    with pytest.raises(_FieldError):
        parse_amount(CanonicalField.ROOM_REVENUE, text, _BOOKINGS)
    with pytest.raises(invoices._BadValueError):
        invoices._parse_decimal_text(text, _INVOICES)
    with pytest.raises(labor._BadValueError):
        labor._parse_decimal_text(text, _LABOR)


# --- a month written as a name (hardening 2) -----------------------------------------------------

NAMED = [
    "26 ottobre 2026",
    "26 ott 2026",
    "26 October 2026",
    "26 Oct 2026",
    "26-Oct-2026",
    "26.ott.2026",
    "lun 26 ottobre 2026",
    "Monday 26 Oct 2026",
]


@pytest.mark.parametrize("text", NAMED)
def test_all_three_importers_read_a_date_whose_month_is_a_name(text: str) -> None:
    monday = date(2026, 10, 26)

    assert parse_date_value(CanonicalField.CHECK_IN, text, _BOOKINGS) == monday
    assert labor._date(text, LaborField.WORK_DATE, _LABOR) == monday
    assert invoices._date(text, InvoiceField.INVOICE_DATE, _INVOICES) == monday


@pytest.mark.parametrize(
    "text",
    [
        "26 ottobre",
        "26 ott 26",
        "ottobre 2026",
        "31 febbraio 2026",
        "26 foo 2026",
        "mar 26 ottobre 2026",
    ],
)
def test_a_date_without_a_year_a_short_year_or_a_day_that_does_not_exist_is_refused(
    text: str,
) -> None:
    with pytest.raises(_FieldError):
        parse_date_value(CanonicalField.CHECK_IN, text, _BOOKINGS)
    with pytest.raises(labor._BadValueError):
        labor._date(text, LaborField.WORK_DATE, _LABOR)
    with pytest.raises(invoices._BadValueError):
        invoices._date(text, InvoiceField.INVOICE_DATE, _INVOICES)


# --- hours written with their unit (hardening 2) -------------------------------------------------

_LABOR_POINT = LaborMappingConfig.model_validate(
    {
        "column_mapping": {
            "work_date": {"column": "Giorno"},
            "role": {"column": "Reparto"},
            "planned_hours": {"column": "Ore"},
        },
        "format_options": {"decimal_separator": "."},
    }
)


@pytest.mark.parametrize(
    ("text", "hours"),
    [
        ("8 h", "8"),
        ("8h", "8"),
        ("7,5 h", "7.5"),
        ("8 ore", "8"),
        ("8 ora", "8"),
        ("8 hours", "8"),
        ("8 hrs", "8"),
        ("8", "8"),
    ],
)
def test_labor_reads_hours_with_their_unit(text: str, hours: str) -> None:
    assert labor._parse_decimal_text(text, _LABOR, hours=True) == Decimal(hours)


def test_labor_reads_a_point_as_the_decimal_mark_when_it_was_confirmed() -> None:
    assert labor._parse_decimal_text("7.5 h", _LABOR_POINT, hours=True) == Decimal("7.5")


@pytest.mark.parametrize(
    "text",
    [
        "8:30",
        "08:00-16:00",
        "mezza giornata",
        "turno completo",
        "8 h 30",
        "14 €/h",
        "14 eur/h",
        "h 8",
    ],
)
def test_what_is_not_a_number_of_hours_is_refused(text: str) -> None:
    with pytest.raises(labor._BadValueError):
        labor._parse_decimal_text(text, _LABOR, hours=True)


def test_an_amount_never_carries_the_unit_of_hours() -> None:
    with pytest.raises(labor._BadValueError):
        labor._parse_decimal_text("120 h", _LABOR)  # a cost column: not hours, not euros
    with pytest.raises(labor._BadValueError):
        labor._decimal("8 ore", _LABOR)
