"""NINFA's domain rules, applied to the READING of a file before it can be called certain.

The importers already refuse a row that breaks a rule (a departure not after its arrival, a negative
amount, a room count below one). That is the last line. This is the FIRST: a column named for a
field
whose values break that field's own rule is probably not that field, and a person is asked about it
now, with the file in front of them, instead of the import failing on every row later.

It can only take certainty AWAY, never add it, and it reads values only through the aligned rows
the caller already holds:

    swapped stay    "arrival" and "departure" where the departure is BEFORE the arrival on nearly
                    every row: the two names are on the wrong columns -> both LOW
    rooms           a count of rooms that is not a whole number of at least one -> MEDIUM
    negative        a booking amount, a commission or a labour cost below zero -> MEDIUM (a
    credit note
                    is a cost-register thing, never a booking's room revenue)

The rest of the rules the brief lists are already enforced where they are cheapest and exact:
`net + VAT = total` (`understanding_costs.amounts_check`, shown as a warning), hours per person
(`DomainSem.person_limits`), planned and actual hours as two columns (the assignment never gives two
fields one column), a category that NINFA cannot read (the labels question), an unknown booking
status
(the labels question) and an identifier that repeats (`fit_unique_identifier`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.relations import MIN_PAIRS, _as_day, _order_of
from app.modules.data_sources.semantics import Level
from app.modules.document_understanding.structure import as_decimal
from app.modules.ingestion.models import DataSourceDomain

# the share of rows that must agree for a reading to be judged by them
SWAPPED = 0.95

NON_NEGATIVE = {
    DataSourceDomain.BOOKINGS: frozenset({"room_revenue", "total_revenue", "commission_amount"}),
    DataSourceDomain.LABOR: frozenset({"planned_cost", "actual_cost"}),
}


@dataclass(frozen=True, slots=True)
class Finding:
    column: int
    field: str
    level: Level  # the most sure the reading may now be
    reason: str


def _column_of(chosen: Mapping[int, str], field: str) -> int | None:
    return next((column for column, name in chosen.items() if name == field), None)


def _stay_days(first: ColumnSample, second: ColumnSample) -> list[int]:
    if not first.rows or len(first.rows) != len(second.rows):
        return []
    order = _order_of(first.rows, second.rows)
    gaps: list[int] = []
    for a, b in zip(first.rows, second.rows, strict=True):
        start, end = _as_day(a, order), _as_day(b, order)
        if isinstance(start, date) and isinstance(end, date):
            gaps.append((end - start).days)
    return gaps


def validate_reading(
    domain: DataSourceDomain,
    chosen: Mapping[int, str],
    samples: Sequence[ColumnSample],
) -> list[Finding]:
    findings: list[Finding] = []
    if domain == DataSourceDomain.BOOKINGS:
        arrival, departure = _column_of(chosen, "check_in"), _column_of(chosen, "check_out")
        if arrival is not None and departure is not None:
            gaps = _stay_days(samples[arrival], samples[departure])
            if len(gaps) >= MIN_PAIRS and sum(1 for gap in gaps if gap < 0) / len(gaps) >= SWAPPED:
                reason = "the departure is before the arrival on nearly every row: names swapped?"
                findings.append(Finding(arrival, "check_in", Level.LOW, reason))
                findings.append(Finding(departure, "check_out", Level.LOW, reason))
        rooms = _column_of(chosen, "rooms")
        if rooms is not None:
            numbers = [n for cell in samples[rooms].values if (n := as_decimal(cell)) is not None]
            if numbers and any(n < 1 or n != n.to_integral_value() for n in numbers):
                findings.append(
                    Finding(
                        rooms,
                        "rooms",
                        Level.MEDIUM,
                        "a room count must be a whole number of 1 or more",
                    )
                )
    for field in NON_NEGATIVE.get(domain, ()):
        column = _column_of(chosen, field)
        if column is None:
            continue
        numbers = [n for cell in samples[column].values if (n := as_decimal(cell)) is not None]
        if any(n < Decimal(0) for n in numbers):
            findings.append(
                Finding(column, field, Level.MEDIUM, "negative amounts: a credit, not a charge")
            )
    return findings


__all__ = ["Finding", "validate_reading"]
