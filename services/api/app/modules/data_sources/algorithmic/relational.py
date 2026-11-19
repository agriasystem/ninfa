"""What columns say about EACH OTHER: evidence no single column carries.

Three dates in a booking file are, in order on every row, when it was booked, when the guest
arrives and when they leave - a fact no header has to state. In a purchase register, a net amount,
a VAT amount and a total that add up on every row are those three things. A relation is evidence
about the PAIR (or triple), so it can raise a reading (a bonus to the roles it explains) and, when a
column has no helpful name at all, it can name the roles by itself (`proof`) - but only when the
explanation is UNIQUE: two orderings that both fit leave the roles to a person.

Deterministic and bounded: it reads the rows the caller already holds, keeps nothing, and a relation
that is not there (a file with no departure) is not an error, it is just no evidence.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import combinations, permutations

from app.modules.bookings.parsers import Cell
from app.modules.data_sources.algorithmic.profile import ColumnProfile
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.relations import _as_day, _order_of
from app.modules.document_understanding.structure import as_decimal
from app.modules.ingestion.models import DataSourceDomain

MIN_ROWS = 5
# the share of rows a relation must hold on to be evidence (a few slips are data entry)
HOLDS = 0.95
LONGEST_STAY = 90
TYPICAL_STAY = 21
LONGEST_LEAD = 540
MAX_DATE_COLUMNS = 4
MAX_TAX_RATE = Decimal("0.30")
PENNY = Decimal("0.02")

BONUS = 0.15
PROOF = 0.9


@dataclass(frozen=True, slots=True)
class Relational:
    """What the relations between columns add to a (column position, field) pair."""

    bonus: dict[tuple[int, str], float] = field(default_factory=dict)
    # the relation alone names the field of this column (it needs no helpful header)
    proof: dict[tuple[int, str], float] = field(default_factory=dict)
    reasons: dict[tuple[int, str], str] = field(default_factory=dict)

    def add(self, position: int, name: str, *, proves: bool, reason: str) -> None:
        self.bonus[(position, name)] = BONUS
        if proves:
            self.proof[(position, name)] = PROOF
        self.reasons[(position, name)] = reason


def _parsed(samples: Sequence[ColumnSample], dated: Sequence[int]) -> dict[int, list[date | None]]:
    """Every date column read ONCE as days, with the day/month order the written dates of all of
    them prove together (a file writes its dates one way)."""
    rows = {i: samples[i].rows for i in dated}
    if not all(rows.values()) or len({len(r) for r in rows.values()}) != 1:
        return {}
    order = _order_of(*rows.values())
    return {i: [_as_day(cell, order) for cell in cells] for i, cells in rows.items()}


def _days(parsed: dict[int, list[date | None]], positions: Sequence[int]) -> list[tuple[date, ...]]:
    """The rows on which every one of these columns holds a date, as days."""
    if not parsed:
        return []
    out: list[tuple[date, ...]] = []
    for cells in zip(*(parsed[position] for position in positions), strict=True):
        if all(day is not None for day in cells):
            out.append(tuple(day for day in cells if day is not None))
    return out


def _chains(days: list[tuple[date, ...]]) -> list[tuple[int, ...]]:
    """The orderings of three columns under which every row reads booked <= arrival < departure
    (a stay of a plausible length, booked a plausible time ahead). One that fits = a fact."""
    found: list[tuple[int, ...]] = []
    for order in permutations(range(3)):
        good = 0
        for row in days:
            booked, arrival, departure = (row[i] for i in order)
            stay = (departure - arrival).days
            lead = (arrival - booked).days
            if 0 < stay <= LONGEST_STAY and 0 <= lead <= LONGEST_LEAD:
                good += 1
        if days and good / len(days) >= HOLDS:
            found.append(order)
    return found


def booking_dates(
    samples: Sequence[ColumnSample], profiles: Sequence[ColumnProfile], out: Relational
) -> None:
    """booked <= arrival < departure, from the values of the date columns themselves."""
    dated = [
        i
        for i, profile in enumerate(profiles)
        if profile.date_share >= 0.9 and profile.non_null >= MIN_ROWS and not profile.personal
    ]
    if not 2 <= len(dated) <= MAX_DATE_COLUMNS:
        return
    parsed = _parsed(samples, dated)
    solutions: list[tuple[tuple[int, int, int], tuple[int, ...]]] = []
    for triple in combinations(dated, 3):
        days = _days(parsed, triple)
        if len(days) < MIN_ROWS:
            continue
        solutions.extend((triple, order) for order in _chains(days))
    if len(solutions) == 1:
        triple, order = solutions[0]
        roles = ("booked_at", "check_in", "check_out")
        for role, position in zip(roles, (triple[i] for i in order), strict=True):
            out.add(
                position, role, proves=True, reason="booked <= arrival < departure on every row"
            )
        return
    if len(dated) == 2:
        # two dates cannot tell a booking date from an arrival: only a stay (short) is a fact
        for a, b in permutations(dated, 2):
            days = _days(parsed, (a, b))
            if len(days) < MIN_ROWS:
                continue
            gaps = sorted((row[1] - row[0]).days for row in days)
            if (
                all(0 < gap <= LONGEST_STAY for gap in gaps)
                and gaps[len(gaps) // 2] <= TYPICAL_STAY
            ):
                out.add(
                    a, "check_in", proves=False, reason="a stay: the other date is a few days later"
                )
                out.add(
                    b, "check_out", proves=False, reason="a stay: a few days after the other date"
                )


def _amount(cell: Cell) -> Decimal | None:
    return as_decimal(cell) if cell is not None else None


def invoice_amounts(
    samples: Sequence[ColumnSample], profiles: Sequence[ColumnProfile], out: Relational
) -> None:
    """net + VAT = total on every row: the three amounts of an invoice register."""
    money = [
        i
        for i, profile in enumerate(profiles)
        if profile.numeric_share >= 0.95
        and profile.non_null >= MIN_ROWS
        and not profile.personal
        and profile.identifier_like < 0.5
        and samples[i].rows
    ]
    if not 3 <= len(money) <= 6:
        return
    solutions: list[tuple[int, int, int]] = []
    for net, tax, gross in permutations(money, 3):
        if len({len(samples[i].rows) for i in (net, tax, gross)}) != 1:
            continue
        checked = good = 0
        for a, b, c in zip(samples[net].rows, samples[tax].rows, samples[gross].rows, strict=True):
            x, y, z = _amount(a), _amount(b), _amount(c)
            if x is None or y is None or z is None:
                continue
            checked += 1
            if x > 0 and 0 <= y <= x * MAX_TAX_RATE and abs(x + y - z) <= PENNY:
                good += 1
        if checked >= MIN_ROWS and good / checked >= HOLDS:
            solutions.append((net, tax, gross))
    if len(solutions) == 1:
        net, tax, gross = solutions[0]
        for position, name in (
            (net, "invoice_net_amount"),
            (tax, "invoice_tax_amount"),
            (gross, "invoice_gross_amount"),
        ):
            out.add(position, name, proves=False, reason="net + VAT = total on every row")


def relations_of(
    domain: DataSourceDomain,
    samples: Sequence[ColumnSample],
    profiles: Sequence[ColumnProfile],
) -> Relational:
    out = Relational()
    if domain == DataSourceDomain.BOOKINGS:
        booking_dates(samples, profiles, out)
    elif domain == DataSourceDomain.COSTS:
        invoice_amounts(samples, profiles, out)
    return out


__all__ = ["BONUS", "PROOF", "Relational", "relations_of"]
