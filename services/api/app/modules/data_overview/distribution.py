"""The Distribuzione block of the Dati overview: the OTA share, the channel weights, the outcome.

Nothing is defined here. The OTA share is `OtaDependencyService`'s own `ota_share_exact` (OTA /
(OTA + direct) room-nights over the next 30 nights) or, when the run already holds an OTA decision,
that decision's own PERSISTED figures - the run is the authority, a live read only ADDS a figure and
never contradicts a decision. The channel weights are the certain room-nights of each channel over
the same 30 nights, by Gate 3's own `booking_certainty_at` rule, as a share of ALL channels: a
different metric from the OTA share (a different denominator), and the two are never mixed.

The weights say what they are a share of, and whether that is the room-nights the analysis day
observed (`ChannelMix`). When it is not, the reason is in the bookings' own dates: a booking date
or a cancellation date after the analysis day, or a no-show for a stay not yet begun
(`BookingDateConflicts`). Those are the very bookings that make the OTA check's reconciliation
fail; they are counted, never corrected.

Read-only. The booking data source is the run's own (provenance), never inferred.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import BookingStatus
from app.modules.bookings.repository import BookingChannelRepository
from app.modules.data_overview.metrics import percent_of, to_cents
from app.modules.data_overview.types import (
    Availability,
    BookingDateConflicts,
    ChannelGroupName,
    ChannelMix,
    ChannelWeight,
    DistributionOverview,
    DomainState,
    OtaOutcome,
    UnavailableReason,
)
from app.modules.decision_memory.types import FeedItem
from app.modules.intelligence.distribution.channels import ChannelRow, classify_channels
from app.modules.intelligence.distribution.repository import DistributionRepository
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.temporal import (
    OBSERVED_STATUSES,
    BookingCertainty,
    StayRecord,
    booking_certainty_at,
    stay_night_overlap,
)
from app.modules.intelligence.distribution.types import (
    FORWARD_STAY_WINDOW_DAYS,
    ChannelGroup,
    EvaluationStatus,
    OtaDependencyEvaluation,
)
from app.modules.snapshots.localtime import end_of_local_day

logger = logging.getLogger(__name__)

OtaEvaluator = Callable[[UUID, UUID, date], OtaDependencyEvaluation]

_HUNDRED = Decimal(100)
_GROUP_OF: dict[ChannelGroup, ChannelGroupName] = {
    ChannelGroup.OTA: ChannelGroupName.OTA,
    ChannelGroup.DIRECT: ChannelGroupName.DIRECT,
    ChannelGroup.OTHER: ChannelGroupName.OTHER,
    ChannelGroup.UNKNOWN: ChannelGroupName.UNKNOWN,
}


def _unavailable(
    reason: UnavailableReason,
    *,
    window: tuple[date, date] | None = None,
    state: Availability = Availability.NOT_AVAILABLE,
) -> DistributionOverview:
    return DistributionOverview(
        state=state,
        reason=reason,
        window_start=None if window is None else window[0],
        window_end=None if window is None else window[1],
        outcome=None,
        ota_share_pct=None,
        direct_share_pct=None,
        reference_ota_share_pct=None,
        classification_coverage_pct=None,
        insufficient_reasons=(),
        decision_id=None,
        channel_mix=None,
        date_conflicts=None,
    )


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def forward_window(as_of: date) -> tuple[date, date]:
    return as_of, as_of + timedelta(days=FORWARD_STAY_WINDOW_DAYS - 1)


def date_conflicts_of(
    stays: Sequence[tuple[StayRecord, UUID]],
    as_of: date,
    cutoff: datetime,
    window: tuple[date, date],
) -> BookingDateConflicts:
    """Count the bookings of `window` that the analysis day's observation and Gate 3's certainty
    rule at `cutoff` (the end of that day) read differently - and why, from their own dates.

    The observation counts a booking by its status as it is; the certainty rule also asks whether
    it already existed (`booked_at`), when it was cancelled (`cancelled_at`) and whether a no-show
    could be known yet (its arrival). For a status that is on the books, the two disagree only
    when the booking date is after the day; for one that is not, only when the cancellation is
    after it or the no-show's stay had not begun. Pure: no database, no clock."""
    booked_after = cancelled_after = no_show_before_arrival = 0
    for stay, _ in stays:
        if not stay_night_overlap(stay, *window):
            continue
        certain = booking_certainty_at(stay, as_of, cutoff) is BookingCertainty.CERTAIN
        observed = stay.status in OBSERVED_STATUSES
        if observed and not certain:
            booked_after += 1
        elif certain and not observed:
            if stay.status is BookingStatus.NO_SHOW:
                no_show_before_arrival += 1
            else:
                cancelled_after += 1
    return BookingDateConflicts(
        booked_after=booked_after,
        cancelled_after=cancelled_after,
        no_show_before_arrival=no_show_before_arrival,
    )


class DistributionReader:
    """Read-only. Pass any session: it neither commits nor rolls back, and reads no clock."""

    def __init__(
        self,
        session: Session,
        tenant: TenantContext,
        *,
        ota_evaluator: OtaEvaluator | None = None,
    ) -> None:
        self._session = session
        self._tenant = tenant
        self._distribution = DistributionRepository(session, tenant)
        self._channels = BookingChannelRepository(session, tenant)
        self._evaluate_ota: OtaEvaluator = ota_evaluator or self._live_evaluation

    def read(
        self,
        *,
        property_id: UUID,
        as_of: date,
        timezone: ZoneInfo,
        run_exists: bool,
        source_id: UUID | None,
        state: DomainState,
        ota_decision: FeedItem | None,
        on_books_room_nights: int | None = None,
    ) -> DistributionOverview:
        """`on_books_room_nights`: the room-nights the analysis day observed over the same 30
        nights (`None` unless it holds every night) - what the channel weights are checked
        against."""
        window = forward_window(as_of)
        if not run_exists:
            return _unavailable(UnavailableReason.NO_ANALYSIS)
        if state is DomainState.UNKNOWN:
            return _unavailable(UnavailableReason.COVERAGE_UNKNOWN)
        if state is DomainState.NOT_ANALYZED:
            return _unavailable(
                UnavailableReason.NOT_ANALYZED, window=window, state=Availability.NOT_AVAILABLE
            )
        if source_id is None:
            return _unavailable(UnavailableReason.NO_BOOKING_SOURCE)

        if ota_decision is not None:
            overview = self._from_decision(ota_decision, window)
        else:
            overview = self._from_evaluation(property_id, source_id, as_of, window)

        mix, conflicts = self._channel_mix(
            property_id, source_id, as_of, timezone, on_books_room_nights
        )
        return DistributionOverview(
            state=overview.state,
            reason=overview.reason,
            window_start=overview.window_start,
            window_end=overview.window_end,
            outcome=overview.outcome,
            ota_share_pct=overview.ota_share_pct,
            direct_share_pct=overview.direct_share_pct,
            reference_ota_share_pct=overview.reference_ota_share_pct,
            classification_coverage_pct=overview.classification_coverage_pct,
            insufficient_reasons=overview.insufficient_reasons,
            decision_id=overview.decision_id,
            channel_mix=mix,
            date_conflicts=conflicts,
        )

    # --- the OTA share -----------------------------------------------------------------------

    @staticmethod
    def _from_decision(item: FeedItem, window: tuple[date, date]) -> DistributionOverview:
        """The decision's own persisted figures: the run is the authority."""
        facts = item.observation.facts_payload
        evidence = item.observation.evidence_payload
        ota = _decimal(facts.get("ota_share_exact"))
        ota_pct = None if ota is None else to_cents(ota)
        start = _iso(facts.get("window_start")) or window[0]
        end = _iso(facts.get("window_end")) or window[1]
        return DistributionOverview(
            state=Availability.AVAILABLE,
            reason=None,
            window_start=start,
            window_end=end,
            outcome=OtaOutcome.DECISION,
            ota_share_pct=ota_pct,
            direct_share_pct=None if ota_pct is None else to_cents(_HUNDRED - ota_pct),
            reference_ota_share_pct=_pct(facts.get("expected_ota_share_exact")),
            classification_coverage_pct=_pct(evidence.get("classification_coverage_pct_exact")),
            insufficient_reasons=(),
            decision_id=item.decision.id,
            channel_mix=None,
            date_conflicts=None,
        )

    def _from_evaluation(
        self, property_id: UUID, source_id: UUID, as_of: date, window: tuple[date, date]
    ) -> DistributionOverview:
        try:
            evaluation = self._evaluate_ota(property_id, source_id, as_of)
        except Exception as error:  # a read-only enrichment: "not available", never a guess
            logger.warning("data overview ota unavailable error_type=%s", type(error).__name__)
            return _unavailable(UnavailableReason.EVALUATION_FAILED, window=window)

        status = evaluation.status
        if status is EvaluationStatus.TRIGGERED:
            # TRIGGERED on the data as they are NOW while the persisted run produced no decision:
            # the bookings changed after the analysis. The run is the authority - nothing is shown.
            return DistributionOverview(
                state=Availability.AVAILABLE,
                reason=None,
                window_start=evaluation.window_start,
                window_end=evaluation.window_end,
                outcome=OtaOutcome.CHANGED_AFTER_ANALYSIS,
                ota_share_pct=None,
                direct_share_pct=None,
                reference_ota_share_pct=None,
                classification_coverage_pct=None,
                insufficient_reasons=(),
                decision_id=None,
                channel_mix=None,
                date_conflicts=None,
            )

        outcome = {
            EvaluationStatus.CLEAR: OtaOutcome.CLEAR,
            EvaluationStatus.INSUFFICIENT_DATA: OtaOutcome.INSUFFICIENT_DATA,
            EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE: OtaOutcome.SUPPRESSED,
            EvaluationStatus.NOT_APPLICABLE: OtaOutcome.NOT_APPLICABLE,
        }[status]
        ota = evaluation.ota_share_exact
        ota_pct = None if ota is None else to_cents(ota)
        coverage = evaluation.classification_coverage_pct_exact
        reasons = (
            tuple(code.value for code in evaluation.reason_codes)
            if status is EvaluationStatus.INSUFFICIENT_DATA
            else ()
        )
        return DistributionOverview(
            state=Availability.AVAILABLE,
            reason=None,
            window_start=evaluation.window_start,
            window_end=evaluation.window_end,
            outcome=outcome,
            ota_share_pct=ota_pct,
            direct_share_pct=None if ota_pct is None else to_cents(_HUNDRED - ota_pct),
            reference_ota_share_pct=(
                None
                if evaluation.expected_ota_share_exact is None
                else to_cents(evaluation.expected_ota_share_exact)
            ),
            classification_coverage_pct=None if coverage is None else to_cents(coverage),
            insufficient_reasons=reasons,
            decision_id=None,
            channel_mix=None,
            date_conflicts=None,
        )

    def _live_evaluation(
        self, property_id: UUID, source_id: UUID, as_of: date
    ) -> OtaDependencyEvaluation:
        return OtaDependencyService(self._session, self._tenant).evaluate(
            property_id=property_id,
            booking_data_source_id=source_id,
            as_of_local_date=as_of,
        )

    # --- the channel weights -----------------------------------------------------------------

    def _channel_mix(
        self,
        property_id: UUID,
        source_id: UUID,
        as_of: date,
        timezone: ZoneInfo,
        on_books_room_nights: int | None,
    ) -> tuple[ChannelMix | None, BookingDateConflicts]:
        """Certain room-nights per channel over the next 30 nights, as a share of all channels, and
        the window's date conflicts (from the same bookings). The mix is `None` when the property
        has no channel or no certain booking in the window."""
        window = forward_window(as_of)
        channels = list(self._channels.list_for_property(property_id))
        if not channels:  # every booking has a channel: no channel, no booking, no conflict
            return None, BookingDateConflicts(0, 0, 0)
        groups = classify_channels(
            [ChannelRow(c.id, c.normalized_name, c.channel_type, c.is_verified) for c in channels]
        )
        stays = self._distribution.list_stays_with_channel(property_id, source_id, *window)
        cutoff = end_of_local_day(as_of, timezone)
        conflicts = date_conflicts_of(stays, as_of, cutoff, window)
        room_nights: dict[UUID, int] = {}
        for stay, channel_id in stays:
            if booking_certainty_at(stay, as_of, cutoff) is not BookingCertainty.CERTAIN:
                continue
            nights = len(stay_night_overlap(stay, *window))
            if nights:
                room_nights[channel_id] = room_nights.get(channel_id, 0) + stay.rooms * nights
        total = sum(room_nights.values())
        if total == 0:
            return None, conflicts

        by_id = {channel.id: channel for channel in channels}
        ranked = sorted(room_nights.items(), key=lambda item: (-item[1], by_id[item[0]].name))
        weights = []
        for channel_id, nights in ranked:
            share = percent_of(nights, total)
            assert share is not None  # total > 0
            weights.append(
                ChannelWeight(
                    name=by_id[channel_id].name,
                    group=_GROUP_OF[groups[channel_id].group],
                    room_nights=nights,
                    share_pct=share,
                )
            )
        classified = sum(
            weight.room_nights
            for weight in weights
            if weight.group in (ChannelGroupName.OTA, ChannelGroupName.DIRECT)
        )
        unclassified = sum(
            weight.room_nights for weight in weights if weight.group is ChannelGroupName.UNKNOWN
        )
        mix = ChannelMix(
            total_room_nights=total,
            classified_room_nights=classified,
            unclassified_room_nights=unclassified,
            on_books_room_nights=on_books_room_nights,
            matches_on_books=(
                None if on_books_room_nights is None else on_books_room_nights == total
            ),
            channels=tuple(weights),
        )
        return mix, conflicts


def _iso(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _pct(value: object) -> Decimal | None:
    number = _decimal(value)
    return None if number is None else to_cents(number)


__all__ = ["DistributionReader", "OtaEvaluator", "date_conflicts_of", "forward_window"]
