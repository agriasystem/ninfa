"""What a bookings file says ACROSS its columns, beyond what each header says on its own.

Two things only a look at several columns can settle:

* a lone "Total": in a file that is plainly a list of reservations, with no other column of money,
  the only amount is the reservation's - but whether it is the ROOM revenue (what the analysis
  works with) or the whole stay with extras and taxes is not written anywhere, so it is proposed,
  never decided: one confirmation. With any other amount beside it (room total, extras, tax,
  commission...) nothing is chosen;
* arrival and departure: a stay does not end before it begins. When the arrival is after the
  departure on (nearly) every row, the headers contradict the values - the columns may be swapped,
  or the file is wrong - and NINFA neither swaps them nor imports them: the person is asked to
  look.
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime

from app.modules.bookings.parsers import Cell
from app.modules.data_sources.channel_words import channel_share
from app.modules.data_sources.proposal import CONTESTED, ColumnProposal, Proposal
from app.modules.data_sources.semantics import Level, NameMatch
from app.modules.data_sources.understanding_types import Choice, OriginKind, Question, QuestionKind
from app.modules.document_understanding.stats import ColumnStats
from app.modules.document_understanding.text import fold, stems, tokens
from app.modules.ingestion.value_text import month_name_date, split_weekday

_BARE_TOTALS = frozenset({"total", "totale", "tot"})
# A reservation's identity and its dates must be there before a lone amount is read as its revenue.
_STRUCTURE = frozenset({"source_record_id", "booked_at", "check_in", "check_out"})
# Fields that are, or hold, money: a second one beside the "Total" means the "Total" is not alone.
_MONEY_FIELDS = frozenset({"room_revenue", "total_revenue", "commission_amount"})
# Words that name an amount beside the total (tax, extras, fees...): the column is a competitor
# even when its values are small whole numbers.
_MONEY_WORDS = stems(
    "tax tasse tassa imposta iva vat extra extras fee fees supplemento supplementi commissione "
    "commission acconto deposito deposit saldo balance prezzo price tariffa importo amount"
)
_MIN_COMPARED = 3
_REVERSED = 0.8


# --- a lone total ---------------------------------------------------------------------------------


def _looks_like_money(column: ColumnProposal) -> bool:
    stats: ColumnStats = column.stats
    if stats.n == 0 or stats.numeric_fraction < 0.8:
        return False
    if tokens(column.header) & _MONEY_WORDS:
        return True
    # small whole numbers are counts (rooms, guests, nights); anything else is an amount
    return stats.integral < stats.numeric or (stats.maximum is not None and stats.maximum > 100)


def lone_total_is_room_revenue(proposal: Proposal) -> Proposal:
    """A bare "Total" that is the only amount of a list of reservations is proposed (MEDIUM) as the
    room revenue. Anything else beside it, or a structure that is not a reservation's, leaves it
    alone."""
    assigned = proposal.assigned()
    total = assigned.get("total_revenue")
    if "room_revenue" in assigned or total is None or fold(total.header) not in _BARE_TOTALS:
        return proposal
    if not set(assigned) >= _STRUCTURE:
        return proposal
    for column in proposal.columns:
        if column is total or column.locked is not None or column.pii is not None:
            continue
        if column.ambiguous_group in {"AMOUNT", CONTESTED}:
            return proposal  # another amount that does not say which, or two that look alike
        if column.field in _MONEY_FIELDS or (column.field is None and _looks_like_money(column)):
            return proposal
    return Proposal(
        tuple(
            replace(c, field="room_revenue", level=Level.MEDIUM) if c is total else c
            for c in proposal.columns
        )
    )


# --- a channel the hotel has already taught -------------------------------------------------------

_MOST = 0.6


def channel_by_taught(proposal: Proposal, taught: frozenset[str]) -> Proposal:
    """What the hotel has already told NINFA about its channels ("BDC" is Booking.com) counts as
    one more word for them: a channel column, named as one, whose values are for the most part
    channels NINFA knows - by its own words or by that mapping - is a channel for certain. The
    mapping belongs to the property (it is read from the saved source, never shared)."""
    column = proposal.assigned().get("channel")
    if (
        column is None
        or column.level != Level.MEDIUM
        or column.name not in (NameMatch.EXACT, NameMatch.TOKEN)
        or not column.stats.enough()
        or not taught
        or channel_share(column.stats.texts, taught) < _MOST
    ):
        return proposal
    return Proposal(
        tuple(replace(c, level=Level.HIGH) if c is column else c for c in proposal.columns)
    )
# --- a stay that ends before it begins ------------------------------------------------------------

_ISO = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?$")
_SLASHED = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?$")


def _day(cell: Cell, order: str) -> date | None:
    """The day a cell holds, reading a numeric text date day-first (DMY) or month-first (MDY)."""
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    if not isinstance(cell, str):
        return None
    text = split_weekday(cell.strip())[0]
    named = month_name_date(text)
    try:
        if named is not None:
            return named.date()
        if match := _ISO.match(text):
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if match := _SLASHED.match(text):
            first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return date(year, second, first) if order == "DMY" else date(year, first, second)
    except ValueError:
        return None
    return None


def _inverted(arrival: Cell, departure: Cell) -> bool | None:
    """Is the arrival after the departure? None when the two cannot be compared. A text date that
    reads two ways counts as inverted only if it is inverted both ways."""
    verdicts: list[bool] = []
    for order in ("DMY", "MDY"):
        first, second = _day(arrival, order), _day(departure, order)
        if first is not None and second is not None:
            verdicts.append(first > second)
    if not verdicts:
        return None
    return all(verdicts)


def stay_is_reversed(rows: Sequence[Sequence[Cell]], arrival: int, departure: int) -> bool:
    """Arrival after departure on (nearly) every row that has both."""
    compared = reversed_rows = 0
    for row in rows:
        if arrival >= len(row) or departure >= len(row):
            continue
        verdict = _inverted(row[arrival], row[departure])
        if verdict is None:
            continue
        compared += 1
        reversed_rows += 1 if verdict else 0
    return compared >= _MIN_COMPARED and reversed_rows >= _REVERSED * compared


def check_stay(
    proposal: Proposal, rows: Sequence[Sequence[Cell]]
) -> tuple[Proposal, Question | None]:
    """When arrival is after departure on (nearly) every row: neither column is trusted (MEDIUM, so
    the import is never automatic), nothing is swapped, and the person is asked to look."""
    assigned = proposal.assigned()
    arrival, departure = assigned.get("check_in"), assigned.get("check_out")
    if arrival is None or departure is None:
        return proposal, None
    if not stay_is_reversed(rows, arrival.position, departure.position):
        return proposal, None
    demoted = Proposal(
        tuple(
            replace(c, level=Level.MEDIUM) if c is arrival or c is departure else c
            for c in proposal.columns
        )
    )
    question = Question(
        id="DATES_REVERSED",
        kind=QuestionKind.DATES_REVERSED,
        column=arrival.header,
        origin=OriginKind.COLUMN,
        choices=(Choice(departure.header),),
    )
    return demoted, question


__all__ = ["check_stay", "lone_total_is_room_revenue", "stay_is_reversed"]
