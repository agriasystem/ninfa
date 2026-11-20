"""Columns that may hold a document number nobody named (ADR 0057, final correctness gate).

The detector only ever leads to a question, never to a decision: these are its edges, one shape
at a time.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.number_candidates import is_number_candidate


def column(*cells: Any) -> ColumnSample:
    values = tuple(cell for cell in cells if cell not in (None, ""))
    return ColumnSample(
        position=0,
        header="Campo 1",
        examples=tuple(str(v) for v in values[:3]),
        values=values,
        rows=tuple(cells),
    )


NUMBERS = [f"2026/{n}" for n in range(101, 113)]


@pytest.mark.parametrize(
    ("name", "cells"),
    [
        ("invoice numbers", NUMBERS),
        ("letters and digits", [f"FT-{n:04d}" for n in range(1, 11)]),
        ("dotted codes", [f"A.{n}.26" for n in range(1, 9)]),
        # a number repeated on the lines of its invoice: uniqueness per row is not required
        ("four lines per invoice", [f"FE/{n}" for n in range(1, 5) for _ in range(4)]),
        ("integers, not one step at a time", ["1045", "1047", "1052", "1060", "1061", "1075"]),
        ("half the rows filled", [*NUMBERS[:6], *([""] * 6)]),
        ("numbers read as numbers", [Decimal(1045), Decimal(1047), Decimal(1052), Decimal(1060)]),
    ],
)
def test_a_column_of_codes_may_be_the_document_number(name: str, cells: list[Any]) -> None:
    assert is_number_candidate(column(*cells)), name


@pytest.mark.parametrize(
    ("name", "cells"),
    [
        ("a row counter", [str(n) for n in range(1, 13)]),
        ("a row counter from 101", [str(n) for n in range(101, 113)]),
        ("dates as text", ["05/10/2026", "06/10/2026", "07/10/2026", "08/10/2026"]),
        ("dates", [date(2026, 10, d) for d in range(1, 10)]),
        ("amounts", ["12,50", "40,00", "1.234,56", "7,20", "99,99"]),
        ("amounts as numbers", [Decimal("12.50"), Decimal("40.10"), Decimal("7.25")]),
        ("VAT numbers", ["IT01234567890", "IT09876543210", "IT11111111111", "IT22222222222"]),
        ("tax codes", ["RSSMRA80A01H501U", "BNCLRA85M41F205X", "VRDGPP70C10L219Z"]),
        ("IBANs", ["IT60X0542811101000000123456", "IT02A0301503200000003517230"]),
        ("a quantity", ["1", "2", "1", "3", "2", "1", "1", "2", "3", "1", "2", "1"]),
        ("a VAT rate", ["22", "10", "22", "4", "22", "10", "22", "22"]),
        ("a supplier code", ["F01", "F02", "F01", "F01", "F02", "F01", "F02", "F01", "F01"]),
        ("mostly empty", [*NUMBERS[:4], *([""] * 8)]),
        ("words", ["Lavanderia", "Utenze", "Pulizie", "Manutenzione"]),
        ("two values only", ["A1", "B2"]),
    ],
)
def test_a_column_that_is_something_else_is_never_offered(name: str, cells: list[Any]) -> None:
    assert not is_number_candidate(column(*cells)), name
