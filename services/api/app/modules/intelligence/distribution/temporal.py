"""Gate 3's own booking-certainty rule, re-exported (not reimplemented).

REV_OTA_DEPENDENCY needs to know, for an arbitrary HISTORICAL as-of instant, which bookings were
certainly on the books, which were uncertain, and which did not exist yet - exactly the question
`BookingSnapshotReconstructionService` already answers for the whole property. Rather than write
a second temporal algorithm that could silently drift from Gate 3's, this module imports the
SAME pure primitives Gate 3 extracted for this purpose (`app.modules.snapshots.aggregate`) and
specialises them to a single cutoff (REV_OTA_DEPENDENCY never needs the multi-cutoff batch that
Gate 3's own reconstruction run does).

Zero semantic change to Gate 3: `booking_certainty_window` and `stay_night_overlap` are the exact
functions Gate 3's `aggregate_reconstruction` itself calls, unmodified.
"""

from bisect import bisect_right
from datetime import date, datetime
from enum import StrEnum

from app.modules.snapshots.aggregate import (
    booking_certainty_window as booking_certainty_window,
)
from app.modules.snapshots.aggregate import (
    stay_night_overlap as stay_night_overlap,
)
from app.modules.snapshots.calculation import OBSERVED_STATUSES as OBSERVED_STATUSES
from app.modules.snapshots.calculation import StayRecord as StayRecord
from app.modules.snapshots.calculation import night_revenue_cents as night_revenue_cents
from app.modules.snapshots.calculation import stay_nights as stay_nights
from app.modules.snapshots.calculation import to_cents as to_cents


class BookingCertainty(StrEnum):
    """CERTAIN: definitely on the books. UNCERTAIN: cannot be known either way (Gate 3's own
    rule, e.g. a CANCELLED booking with no `cancelled_at`, or a NO_SHOW past its check-in date).
    NOT_ON_BOOKS: definitely not (not booked yet as of the cutoff, or certainly cancelled)."""

    CERTAIN = "CERTAIN"
    UNCERTAIN = "UNCERTAIN"
    NOT_ON_BOOKS = "NOT_ON_BOOKS"


def booking_certainty_at(
    stay: StayRecord, as_of_local_date: date, cutoff: datetime
) -> BookingCertainty:
    """Whether `stay` is certain/uncertain/not-on-the-books at a SINGLE historical `cutoff`.

    A specialisation of Gate 3's own `booking_certainty_window` to one cutoff: `booked` is 0 (the
    booking already existed at the cutoff, `booked_at < cutoff`) or 1 (it did not exist yet, the
    SAME rule Gate 3 uses via `bisect_right`), and the resulting (certain, uncertain) index
    windows over a single-cutoff list collapse to one yes/no/unknown answer.
    """
    cutoffs = [cutoff]
    booked = bisect_right(cutoffs, stay.booked_at)
    certain, uncertain = booking_certainty_window(stay, [as_of_local_date], cutoffs, booked)
    if certain[0] < certain[1]:
        return BookingCertainty.CERTAIN
    if uncertain[0] < uncertain[1]:
        return BookingCertainty.UNCERTAIN
    return BookingCertainty.NOT_ON_BOOKS
