"""The channel mix AS-OF one instant, over one 30-day stay window (pure, no database, no clock).

For every booking overlapping the window, Gate 3's OWN temporal rule
(`temporal.booking_certainty_at`) decides CERTAIN / UNCERTAIN / NOT_ON_BOOKS at the target as-of
cutoff - never a second algorithm. Only CERTAIN room-nights are attributed to a channel group
(Part "NO SHOW / TEMPORAL UNCERTAINTY": an uncertain booking is never artificially assigned a
channel). The per-day room totals are exposed separately so the caller can reconcile them,
day by day, against the already-stored `BookingSnapshot.rooms_on_books` (Part
"RECONCILIATION AGAINST SNAPSHOTS") - this module never reads or writes a snapshot itself.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.modules.intelligence.distribution.channels import ChannelClassification
from app.modules.intelligence.distribution.precision import CALCULATION_CONTEXT, exact_sum
from app.modules.intelligence.distribution.temporal import (
    BookingCertainty,
    StayRecord,
    booking_certainty_at,
    night_revenue_cents,
    stay_night_overlap,
    stay_nights,
    to_cents,
)
from app.modules.intelligence.distribution.types import (
    OBSERVED_DAY_SCORE,
    RECONSTRUCTED_DAY_SCORE,
    ChannelGroup,
)
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import SnapshotHistoryRow

_CENTS = Decimal(100)


def _from_cents(cents: int) -> Decimal:
    """Money value (two decimals) of whole cents, in the DEDICATED context: `scaleb` still
    consults *some* context for its result, so the ambient process-wide one must never be it."""
    return Decimal(cents).scaleb(-2, context=CALCULATION_CONTEXT)


@dataclass(frozen=True, slots=True)
class DayChannelTotals:
    """One stay night's CERTAIN room-night (and revenue) totals, by channel group."""

    rooms_by_group: Mapping[ChannelGroup, int]
    revenue_by_group: Mapping[ChannelGroup, Decimal]

    @property
    def total_rooms(self) -> int:
        return sum(self.rooms_by_group.values())


@dataclass(frozen=True, slots=True)
class ChannelMixWindow:
    """The channel mix of a whole 30-day window: per-day totals (for reconciliation) and the
    window-level sums (for the metric itself)."""

    by_day: dict[date, DayChannelTotals]
    ota_room_nights: int
    direct_room_nights: int
    other_room_nights: int
    unknown_room_nights: int
    ota_room_revenue_exact: Decimal
    direct_room_revenue_exact: Decimal

    def rooms_on_books(self, day: date) -> int:
        return self.by_day[day].total_rooms


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def reconstruct_channel_mix(
    stays: Sequence[tuple[StayRecord, UUID]],
    classifications: Mapping[UUID, ChannelClassification],
    *,
    as_of_local_date: date,
    cutoff: datetime,
    window_start: date,
    window_end: date,
) -> ChannelMixWindow:
    """Reconstruct the CERTAIN channel mix of `[window_start, window_end]` as of `cutoff`.

    `stays` is every booking that overlaps the window (any status): the temporal rule alone
    decides inclusion, exactly as Gate 3's own reconstruction does. `classifications` is every
    channel of the property, already classified in memory (never written back).
    """
    days = _date_range(window_start, window_end)
    rooms: dict[date, dict[ChannelGroup, int]] = {
        day: dict.fromkeys(ChannelGroup, 0) for day in days
    }
    revenue: dict[date, dict[ChannelGroup, Decimal]] = {
        day: {group: Decimal(0) for group in ChannelGroup} for day in days
    }

    for stay, channel_id in stays:
        if booking_certainty_at(stay, as_of_local_date, cutoff) != BookingCertainty.CERTAIN:
            continue
        classification = classifications.get(channel_id)
        group = ChannelGroup.UNKNOWN if classification is None else classification.group
        total_cents = to_cents(stay.room_revenue)
        night_count = stay_nights(stay.check_in, stay.check_out)
        for index in stay_night_overlap(stay, window_start, window_end):
            day = stay.check_in + timedelta(days=index)
            rooms[day][group] += stay.rooms
            cents = night_revenue_cents(total_cents, night_count, index)
            revenue[day][group] = CALCULATION_CONTEXT.add(revenue[day][group], _from_cents(cents))

    by_day = {
        day: DayChannelTotals(rooms_by_group=dict(rooms[day]), revenue_by_group=dict(revenue[day]))
        for day in days
    }
    return ChannelMixWindow(
        by_day=by_day,
        ota_room_nights=sum(rooms[day][ChannelGroup.OTA] for day in days),
        direct_room_nights=sum(rooms[day][ChannelGroup.DIRECT] for day in days),
        other_room_nights=sum(rooms[day][ChannelGroup.OTHER] for day in days),
        unknown_room_nights=sum(rooms[day][ChannelGroup.UNKNOWN] for day in days),
        ota_room_revenue_exact=exact_sum(revenue[day][ChannelGroup.OTA] for day in days),
        direct_room_revenue_exact=exact_sum(revenue[day][ChannelGroup.DIRECT] for day in days),
    )


@dataclass(frozen=True, slots=True)
class TargetFacts:
    """Everything the detector needs about the target's own 30-day window, once its snapshot
    coverage is confirmed complete and certain (Parts "TARGET PROVENANCE"/"RECONCILIATION")."""

    reconciled: bool
    observed_day_count: int
    reconstructed_day_count: int
    snapshot_provenance_score_exact: Decimal
    ota_room_nights: int
    direct_room_nights: int
    other_room_nights: int
    unknown_room_nights: int
    ota_room_revenue_exact: Decimal
    direct_room_revenue_exact: Decimal

    @property
    def certain_room_nights(self) -> int:
        return (
            self.ota_room_nights
            + self.direct_room_nights
            + self.other_room_nights
            + self.unknown_room_nights
        )

    @property
    def classified_room_nights(self) -> int:
        return self.ota_room_nights + self.direct_room_nights


def _snapshot_provenance_score(observed_days: int, reconstructed_days: int) -> Decimal:
    """`(observed_days * 100 + reconstructed_days * 60) / 30` (Part "TARGET PROVENANCE")."""
    total = observed_days + reconstructed_days
    weighted = CALCULATION_CONTEXT.add(
        CALCULATION_CONTEXT.multiply(Decimal(observed_days), OBSERVED_DAY_SCORE),
        CALCULATION_CONTEXT.multiply(Decimal(reconstructed_days), RECONSTRUCTED_DAY_SCORE),
    )
    return CALCULATION_CONTEXT.divide(weighted, Decimal(total))


def build_target_facts(rows: Sequence[SnapshotHistoryRow], mix: ChannelMixWindow) -> TargetFacts:
    """Assemble `TargetFacts` from the target's 30 stored snapshots and its independently
    reconstructed channel mix. The caller has already confirmed all 30 exist and none is
    uncertain: this function only checks reconciliation and assembles the rest."""
    reconciled = all(mix.rooms_on_books(row.stay_date) == row.rooms_on_books for row in rows)
    observed_days = sum(1 for row in rows if row.origin == SnapshotOrigin.OBSERVED)
    reconstructed_days = len(rows) - observed_days
    return TargetFacts(
        reconciled=reconciled,
        observed_day_count=observed_days,
        reconstructed_day_count=reconstructed_days,
        snapshot_provenance_score_exact=_snapshot_provenance_score(
            observed_days, reconstructed_days
        ),
        ota_room_nights=mix.ota_room_nights,
        direct_room_nights=mix.direct_room_nights,
        other_room_nights=mix.other_room_nights,
        unknown_room_nights=mix.unknown_room_nights,
        ota_room_revenue_exact=mix.ota_room_revenue_exact,
        direct_room_revenue_exact=mix.direct_room_revenue_exact,
    )
