"""The Distribuzione block of the Dati overview: the OTA share, the channel weights, the outcome.

Nothing is defined here. The OTA share is `OtaDependencyService`'s own `ota_share_exact` (OTA /
(OTA + direct) room-nights over the next 30 nights) or, when the run already holds an OTA decision,
that decision's own PERSISTED figures - the run is the authority, a live read only ADDS a figure and
never contradicts a decision. The channel weights are the certain room-nights of each channel over
the same 30 nights, by Gate 3's own `booking_certainty_at` rule, as a share of ALL channels: a
different metric from the OTA share (a different denominator), and the two are never mixed.

Read-only. The booking data source is the run's own (provenance), never inferred.
"""

import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.repository import BookingChannelRepository
from app.modules.data_overview.metrics import percent_of, to_cents
from app.modules.data_overview.types import (
    Availability,
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
    BookingCertainty,
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
    ) -> DistributionOverview:
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

        mix = self._channel_mix(property_id, source_id, as_of, timezone)
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
        self, property_id: UUID, source_id: UUID, as_of: date, timezone: ZoneInfo
    ) -> ChannelMix | None:
        """Certain room-nights per channel over the next 30 nights, as a share of all channels.
        `None` when the property has no channel or no certain booking in the window."""
        window_start, window_end = forward_window(as_of)
        channels = list(self._channels.list_for_property(property_id))
        if not channels:
            return None
        groups = classify_channels(
            [ChannelRow(c.id, c.normalized_name, c.channel_type, c.is_verified) for c in channels]
        )
        stays = self._distribution.list_stays_with_channel(
            property_id, source_id, window_start, window_end
        )
        cutoff = end_of_local_day(as_of, timezone)
        room_nights: dict[UUID, int] = {}
        for stay, channel_id in stays:
            if booking_certainty_at(stay, as_of, cutoff) is not BookingCertainty.CERTAIN:
                continue
            nights = sum(1 for _ in stay_night_overlap(stay, window_start, window_end))
            if nights:
                room_nights[channel_id] = room_nights.get(channel_id, 0) + stay.rooms * nights
        total = sum(room_nights.values())
        if total == 0:
            return None

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
        return ChannelMix(total_room_nights=total, channels=tuple(weights))


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


__all__ = ["DistributionReader", "OtaEvaluator", "forward_window"]
