"""What a day's booking observation can be used for. Available is not the same as usable.

    AVAILABLE       the last known bookings: Dati and the capacity show them whatever else is true
    FRESH           the source has delivered since the last day analysed: today's position is known,
                    so a new decision can stand on it
    A SAMPLE        a later day may compare with it, because a finished analysis read it and it had
                    something new in it

NO NEW DATA IS NOT NO NEW BOOKINGS. An analysis runs every day, so every day has an observation. On
a day with no new data it repeats what was already known: it says nothing of what happened since,
so no revenue detector speaks on it, and it is no sample of history. When the source does deliver,
a night that gained nothing in its week has a real pickup of zero: that is a fact.

THE RULE. Each run records the latest import that had changed the source when it looked
(`input_provenance.bookings.last_successful_import_job_id`). A day is NEW when what it saw differs
from what the previous analysed day saw, and only then. So:

* the same file again changes nothing: it is not a changing import, and the day stays not new;
* a file arriving at 14:00 after an analysis at 10:00 makes the day new: the day's LAST run counts;
* a restart or a second analysis of the same data sees the same import: nothing becomes new;
* a day's own earlier runs never count: the comparison is with the days before it.

It says nothing about files or uploads: whatever delivers bookings through an import job is judged
the same way. A source whose import changed nothing, an automatic one included, has nothing new to
say.

THE FIRST RUN. With no earlier analysis there is nothing to compare with, and that blocks nothing:
the first valid observation is new, so the detectors are evaluated on what history there is (a
reconstruction counts), and it is the first sample for the days after it.

A FAILED RUN IS NOT HISTORY. Observation, baselines and the final sync are separate commits, so a
job can die leaving an observation no analysis finished reading. `historical_sample_is_eligible` is
the one rule on that, and it is positive: nothing is a sample until a finished run says so. A retry
reaches the same rows and the same revision, so it gives one sample, not two. A later revision of a
day whose analysis failed is not read: the day counts as what its last finished run read.

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
from app.modules.snapshots.repository import ObservationHistory


@dataclass(frozen=True, slots=True)
class BookingObservationFreshness:
    """`fresh`: the day being analysed has new booking data. `history`: which observations of the
    earlier days are samples of anything."""

    fresh: bool
    history: ObservationHistory


@dataclass(frozen=True, slots=True)
class _Seen:
    import_job_id: UUID
    revision: int


def _seen_by(run: DecisionRun, data_source_id: UUID) -> _Seen | None:
    """What a run recorded having read of this source, or None when it does not say enough."""
    if run.input_provenance is None:
        return None
    try:
        bookings = RunInputProvenance.from_json(run.input_provenance).bookings
    except (ValueError, KeyError, TypeError):
        return None
    if bookings.data_source_id != data_source_id or bookings.import_job_id is None:
        return None
    if bookings.snapshot_local_date not in (None, run.as_of_local_date):
        return None
    # A run recorded before a day could be looked at twice read the only observation there was.
    return _Seen(bookings.import_job_id, bookings.observation_revision or 1)


def historical_sample_is_eligible(run: DecisionRun, data_source_id: UUID) -> bool:
    """THE rule for what a run's observation can be used for later (Expected, comparables, curves).

    A `DecisionRun` row exists only once `DecisionService.sync()` has committed: a job that failed
    leaves none, and the table has no other state. So the run finished; what is left to ask is
    whether it says what it read: this source, a known import, this day.
    """
    return _seen_by(run, data_source_id) is not None


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
    runs = session.scalars(
        select(DecisionRun)
        .where(
            DecisionRun.workspace_id == tenant.workspace_id,
            DecisionRun.property_id == property_id,
            DecisionRun.as_of_local_date < as_of_local_date,
            DecisionRun.input_provenance.is_not(None),
        )
        .order_by(DecisionRun.as_of_local_date, DecisionRun.run_sequence)
    ).all()
    seen_by_day: dict[date, _Seen] = {}
    for run in runs:
        seen = _seen_by(run, data_source_id)
        if seen is not None:
            seen_by_day[run.as_of_local_date] = seen  # (in order: a day's last run stays)

    samples: dict[date, int] = {}
    previous: UUID | None = None
    for day in sorted(seen_by_day):
        if seen_by_day[day].import_job_id != previous:
            samples[day] = seen_by_day[day].revision
        previous = seen_by_day[day].import_job_id
    fresh = import_job_id is None or previous is None or import_job_id != previous
    return BookingObservationFreshness(fresh, ObservationHistory(as_of_local_date, samples))


__all__ = [
    "BookingObservationFreshness",
    "booking_observation_freshness",
    "historical_sample_is_eligible",
]
