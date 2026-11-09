"""Has the booking source said anything new? No new data is not the same as no new bookings.

    NO NEW BOOKING DATA      the source has delivered nothing since the last day analysed: what
                             happened to the bookings since then is not known
    NEW DATA, ZERO PICKUP    the source delivered, and a night did not move: that is a fact

An analysis runs every day, so every day has an observation: Dati and the capacity read it. On a day
with no new data that observation repeats what was already known. It must not be read as "nothing
was booked": not by today's pickup, and not, later, as a sample of history.

THE RULE. Each run records the latest import that had changed the source when it looked
(`input_provenance.bookings.import_job_id`). A day is NEW when what it saw differs from what the
previous analysed day saw, and only then. So:

* the same file again changes nothing: it is not a changing import, and the day stays not new;
* a file arriving at 14:00 after an analysis at 10:00 makes the day new: the day's LAST run counts;
* a restart or a second analysis of the same data sees the same import: nothing becomes new;
* a day's own earlier runs never count: the comparison is with the days before it.

It says nothing about files or uploads: whatever delivers bookings through an import job is judged
the same way. A source whose import changed nothing, an automatic one included, has nothing new to
say.

A run or a day with no record of what it saw (from before provenance, or a run that failed after its
observation) is not judged, and stays as it was: nothing can be said of it.

Read-only, no clock: everything is what the runs recorded.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decisions.models import DecisionRun
from app.modules.decisions.provenance import RunInputProvenance


@dataclass(frozen=True, slots=True)
class BookingObservationFreshness:
    """`fresh`: the day being analysed has new booking data. `stale_days`: the earlier days that
    had none, whose observation is no sample of anything."""

    fresh: bool
    stale_days: frozenset[date]


def _import_seen(payload: dict[str, object], data_source_id: UUID) -> UUID | None:
    """The import a run saw of this source, or None when the run says nothing about it."""
    try:
        bookings = RunInputProvenance.from_json(payload).bookings
    except (ValueError, KeyError, TypeError):
        return None
    return bookings.import_job_id if bookings.data_source_id == data_source_id else None


def booking_observation_freshness(
    session: Session,
    tenant: TenantContext,
    *,
    property_id: UUID,
    data_source_id: UUID,
    as_of_local_date: date,
    import_job_id: UUID | None,
) -> BookingObservationFreshness:
    """`import_job_id` is what the observation of `as_of_local_date` has just seen (the run being
    made is not stored yet). Every day before it is read from the runs of that day."""
    rows = session.execute(
        select(DecisionRun.as_of_local_date, DecisionRun.input_provenance)
        .where(
            DecisionRun.workspace_id == tenant.workspace_id,
            DecisionRun.property_id == property_id,
            DecisionRun.as_of_local_date < as_of_local_date,
            DecisionRun.input_provenance.is_not(None),
        )
        .order_by(DecisionRun.as_of_local_date, DecisionRun.run_sequence)
    ).all()
    seen_by_day: dict[date, UUID] = {}
    for day, payload in rows:
        seen = _import_seen(payload, data_source_id)
        if seen is not None:
            seen_by_day[day] = seen  # (in order: a day's last run is the one that stays)

    stale: set[date] = set()
    previous: UUID | None = None
    for day in sorted(seen_by_day):
        if seen_by_day[day] == previous:
            stale.add(day)
        previous = seen_by_day[day]
    fresh = import_job_id is None or previous is None or import_job_id != previous
    return BookingObservationFreshness(fresh=fresh, stale_days=frozenset(stale))


__all__ = ["BookingObservationFreshness", "booking_observation_freshness"]
