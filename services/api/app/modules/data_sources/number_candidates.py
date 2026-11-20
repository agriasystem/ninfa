"""Columns that may hold a document number nobody named (operating costs, ADR 0057).

A file of costs may carry its invoice numbers in a column whose header says nothing ("Campo 1",
"Rif."). Read as a register of operating costs, those numbers would be lost and the same invoices,
arriving later as FatturaPA, would count twice. So such a column is a DOCUMENT SIGNAL: it never
decides anything by itself, it only means the person is asked what the file holds (and, if it holds
invoices, which column is the number - only among these columns, never one the file does not have).

A candidate is a column the reading left UNMAPPED that:

  - has a value in at least half of the rows;
  - writes codes: at least one digit, otherwise letters and / - _ . only (not dates, not amounts
    with decimals, not a VAT number, a tax code or an IBAN - those say who the supplier is);
  - is not a row counter (1..N, one step at a time, in file order), nor numbers of one or two
    digits (a quantity, a VAT rate);
  - has values that are not few and repeated (a quantity, a VAT rate, a supplier code): a document
    number may repeat on the lines of one invoice, so uniqueness per row is NOT required.

Deterministic, no model, nothing kept. The thresholds are calibrated on the benchmark corpora (see
the gate report); a change of them is a change of what NINFA asks.
"""

import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.proposal import Proposal

# A value in at least this share of the scanned rows.
MIN_FILLED = 0.5
# At least this share of the values written as codes.
MIN_CODE_SHAPED = 0.8
# Distinct values / values: below this the column repeats a few values (a quantity, a rate, a code
# of the supplier). Low on purpose: an invoice of up to four lines repeats its number four times,
# and missing a number column loses the numbers (a column wrongly offered only costs a question)...
MIN_DISTINCT_SHARE = 0.25
# ...and never fewer than this many distinct values.
MIN_DISTINCT = 3

_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-_.]{0,39}$")
_DIGIT = re.compile(r"\d")
_DATE = re.compile(
    r"^(\d{1,2}[/.\-]\d{1,2}[/.\-](\d{2}|\d{4})|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})"
    r"([T ]\d{1,2}:\d{2}(:\d{2})?)?$"
)
_AMOUNT = re.compile(r"^-?(\d{1,3}([.,' ]\d{3})+|\d+)[.,]\d{1,2}$")
_VAT = re.compile(r"^(IT)?\d{11}$", re.IGNORECASE)
_TAX_CODE = re.compile(r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$", re.IGNORECASE)
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$", re.IGNORECASE)
# One or two digits and nothing else: a quantity, a VAT rate, a count of rooms - not a document
# number (an invoice numbered 1..99 with no prefix is the price of this rule: see the gate report).
_SMALL_NUMBER = re.compile(r"^\d{1,2}$")


def number_candidates(proposal: Proposal, samples: Sequence[ColumnSample]) -> tuple[str, ...]:
    """The headers of the unmapped columns that may hold a document number, in file order."""
    by_position = {sample.position: sample for sample in samples}
    found: list[str] = []
    for column in proposal.columns:
        if column.field is not None or column.locked is not None or column.pii is not None:
            continue
        if column.ambiguous_group is not None:
            continue  # asked about as what it may be, not here
        sample = by_position.get(column.position)
        if sample is not None and is_number_candidate(sample):
            found.append(column.header)
    return tuple(found)


def is_number_candidate(sample: ColumnSample) -> bool:
    rows = sample.rows
    values = [_text(cell) for cell in (rows or sample.values)]
    filled = [value for value in values if value]
    if not filled or (rows and len(filled) / len(rows) < MIN_FILLED):
        return False
    codes = [value for value in filled if _is_code(value)]
    if len(codes) / len(filled) < MIN_CODE_SHAPED:
        return False
    if _is_counter(filled):
        return False
    if sum(1 for value in codes if _SMALL_NUMBER.match(value)) / len(codes) >= MIN_CODE_SHAPED:
        return False
    distinct = len(set(codes))
    return distinct >= MIN_DISTINCT and distinct / len(codes) >= MIN_DISTINCT_SHARE


def _text(cell: object) -> str:
    """A cell as the text a code would be written as ("" for nothing; a date or an amount with
    decimals stays recognisable as what it is)."""
    if cell is None:
        return ""
    if isinstance(cell, datetime | date):
        return cell.isoformat()
    if isinstance(cell, float | Decimal):
        number = Decimal(str(cell))
        return str(int(number)) if number == number.to_integral_value() else f"{number:.2f}"
    return str(cell).strip()


def _is_code(value: str) -> bool:
    if not _CODE.match(value) or not _DIGIT.search(value):
        return False
    if _DATE.match(value) or _AMOUNT.match(value):
        return False
    return not (_VAT.match(value) or _TAX_CODE.match(value) or _IBAN.match(value))


def _is_counter(values: Sequence[str]) -> bool:
    """1, 2, 3 ... (or any start) one step at a time, in file order: the position of the row."""
    if not all(value.isdigit() for value in values):
        return False
    numbers = [int(value) for value in values]
    return all(b - a == 1 for a, b in zip(numbers, numbers[1:], strict=False))
