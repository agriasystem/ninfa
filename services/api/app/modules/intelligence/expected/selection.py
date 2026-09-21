"""Which stored snapshots are comparable to a target (pure functions, no database).

A candidate is comparable when ALL of these hold, checked in this order:

 1. no temporal leakage: its stay date is strictly before the target's stay date AND its snapshot
    day is strictly before the target's snapshot day (nothing that was not yet known);
 2. same lead time: `stay_date - snapshot_local_date` equals the target's (no interpolation: a
    stay date that has no snapshot at exactly this distance simply has no comparable);
 3. within the 730-day horizon;
 4. same weekday;
 5. seasonal distance <= 42 days (see `seasonality`);
 6. quality: a snapshot with uncertainty (`uncertain_rooms > 0`) is never used.

(Data source, property and workspace are the database query's job: the candidates passed in are
already from ONE data source.) Then the provenance policy V1:

* at least 5 usable OBSERVED comparables -> the sample is made of OBSERVED ones only (a
  reconstruction is never added just to enlarge the sample), the 24 most recent at most;
* fewer than 5 -> ALL the observed ones, completed with the clean RECONSTRUCTED ones, newest
  first, up to the 24-comparable sample limit (a reconstruction is an approximation: it fills the
  sample, it never replaces observed evidence, and the confidence pays for it);
* the sample is ranked newest first by stay date (rank 1 = most recent).

Every selected comparable has the same statistical weight: recency only decides who is dropped
by the cap. Rejections are counted in a small, non-persisted diagnostics mapping.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from uuid import UUID

from app.modules.intelligence.expected.seasonality import (
    same_weekday,
    within_horizon,
    within_seasonal_window,
)
from app.modules.snapshots.models import SnapshotOrigin

MIN_SAMPLE = 5
MAX_SAMPLE = 24


class Exclusion(StrEnum):
    """Why a candidate was left out (diagnostics only, never persisted per candidate)."""

    LEAD_TIME_MISMATCH = "LEAD_TIME_MISMATCH"
    STAY_DATE_NOT_BEFORE_TARGET = "STAY_DATE_NOT_BEFORE_TARGET"
    SNAPSHOT_NOT_BEFORE_TARGET = "SNAPSHOT_NOT_BEFORE_TARGET"
    OUTSIDE_HORIZON = "OUTSIDE_HORIZON"
    WEEKDAY_MISMATCH = "WEEKDAY_MISMATCH"
    OUTSIDE_SEASONAL_WINDOW = "OUTSIDE_SEASONAL_WINDOW"
    UNCERTAIN = "UNCERTAIN"
    RECONSTRUCTED_NOT_NEEDED = "RECONSTRUCTED_NOT_NEEDED"
    BEYOND_MAX_SAMPLE = "BEYOND_MAX_SAMPLE"


@dataclass(frozen=True, slots=True)
class HistoricalTarget:
    """WHAT an Expected is computed for: a stay date seen `lead_time_days` before it.

    Deliberately free of any snapshot, alert or decision: the same mathematics can serve a
    backtest or a later "expected final" without duplicating it.
    """

    stay_date: date
    lead_time_days: int

    def __post_init__(self) -> None:
        if self.lead_time_days < 0:
            raise ValueError("lead_time_days must be >= 0")

    @property
    def snapshot_local_date(self) -> date:
        return self.stay_date - timedelta(days=self.lead_time_days)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A stored snapshot considered as a comparable (only what the selection needs)."""

    snapshot_id: UUID
    snapshot_local_date: date
    stay_date: date
    origin: SnapshotOrigin
    rooms_on_books: int
    uncertain_rooms: int

    @property
    def lead_time_days(self) -> int:
        return (self.stay_date - self.snapshot_local_date).days


@dataclass(frozen=True, slots=True)
class SelectedComparable:
    candidate: Candidate
    recency_rank: int  # 1 = the most recent comparable stay date


@dataclass(frozen=True, slots=True)
class Selection:
    comparables: tuple[SelectedComparable, ...]
    observed_count: int
    reconstructed_count: int
    rejected_uncertain_count: int
    diagnostics: Mapping[Exclusion, int] = field(default_factory=dict)

    @property
    def sample_size(self) -> int:
        return len(self.comparables)


def calendar_exclusion(target: HistoricalTarget, candidate: Candidate) -> Exclusion | None:
    """The first calendar rule the candidate breaks, or None when it is calendar-comparable."""
    if not candidate.stay_date < target.stay_date:
        return Exclusion.STAY_DATE_NOT_BEFORE_TARGET
    if not candidate.snapshot_local_date < target.snapshot_local_date:
        return Exclusion.SNAPSHOT_NOT_BEFORE_TARGET
    if candidate.lead_time_days != target.lead_time_days:
        return Exclusion.LEAD_TIME_MISMATCH
    if not within_horizon(candidate.stay_date, target.stay_date):
        return Exclusion.OUTSIDE_HORIZON
    if not same_weekday(candidate.stay_date, target.stay_date):
        return Exclusion.WEEKDAY_MISMATCH
    if not within_seasonal_window(candidate.stay_date, target.stay_date):
        return Exclusion.OUTSIDE_SEASONAL_WINDOW
    return None


def _newest_first(candidates: Iterable[Candidate]) -> list[Candidate]:
    # The snapshot key makes (stay date, lead time) unique inside a data source; the id only
    # makes the order total for hand-built inputs.
    return sorted(candidates, key=lambda c: (c.stay_date, str(c.snapshot_id)), reverse=True)


def select_comparables(target: HistoricalTarget, candidates: Iterable[Candidate]) -> Selection:
    """Apply the calendar rules, the quality filter and the provenance policy V1."""
    diagnostics: Counter[Exclusion] = Counter()
    observed: list[Candidate] = []
    reconstructed: list[Candidate] = []
    rejected_uncertain = 0
    seen: set[UUID] = set()
    for candidate in candidates:
        if candidate.snapshot_id in seen:
            continue
        seen.add(candidate.snapshot_id)
        reason = calendar_exclusion(target, candidate)
        if reason is not None:
            diagnostics[reason] += 1
        elif candidate.uncertain_rooms > 0:
            diagnostics[Exclusion.UNCERTAIN] += 1
            rejected_uncertain += 1
        elif candidate.origin == SnapshotOrigin.OBSERVED:
            observed.append(candidate)
        else:
            reconstructed.append(candidate)

    observed = _newest_first(observed)
    reconstructed = _newest_first(reconstructed)
    if len(observed) >= MIN_SAMPLE:
        chosen = observed[:MAX_SAMPLE]
        diagnostics[Exclusion.BEYOND_MAX_SAMPLE] += len(observed) - len(chosen)
        diagnostics[Exclusion.RECONSTRUCTED_NOT_NEEDED] += len(reconstructed)
    else:
        room = MAX_SAMPLE - len(observed)
        chosen = observed + reconstructed[:room]
        diagnostics[Exclusion.BEYOND_MAX_SAMPLE] += max(0, len(reconstructed) - room)
    chosen = _newest_first(chosen)

    return Selection(
        comparables=tuple(
            SelectedComparable(candidate, rank) for rank, candidate in enumerate(chosen, start=1)
        ),
        observed_count=sum(c.origin == SnapshotOrigin.OBSERVED for c in chosen),
        reconstructed_count=sum(c.origin != SnapshotOrigin.OBSERVED for c in chosen),
        rejected_uncertain_count=rejected_uncertain,
        diagnostics=dict(diagnostics),
    )
