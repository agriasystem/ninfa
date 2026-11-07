"""Dati overview: the Distribuzione block (OTA share, outcome, channel weights).

The OTA share is NINFA's own (`OtaDependencyService`, or the run's persisted decision); the channel
weight is a DIFFERENT metric - the share of ALL certain room-nights - and the two are never mixed.
The live OTA evaluation is replaced by a recording stand-in where a test needs to choose its
outcome; the channel weights always come from real bookings, channels and the Gate 3 certainty
rule.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.modules.data_overview.distribution import forward_window
from app.modules.data_overview.types import (
    Availability,
    BookingDateConflicts,
    ChannelGroupName,
    OtaOutcome,
    UnavailableReason,
)
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.intelligence.distribution.types import (
    EvaluationStatus,
    OtaDependencyEvaluation,
    ReasonCode,
)
from tests.ask_home_support import five_triggered_evaluations
from tests.data_overview_support import (
    AS_OF,
    full_coverage,
    overview_of,
    seed_run,
    uniform_nights,
)
from tests.decision_support import CLEAR, INSUFFICIENT, SUPPRESSED, TRIGGERED, ota_evaluation
from tests.distribution_support import CANCELLED, NO_SHOW, DistributionWorld
from tests.support import BookingFactory, Tenant

D = Decimal


class Evaluator:
    """A recording stand-in for the live OTA evaluation: returns (or raises) what a test decides."""

    def __init__(self, result: OtaDependencyEvaluation | Exception) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID, date]] = []

    def __call__(self, property_id: UUID, source_id: UUID, as_of: date) -> OtaDependencyEvaluation:
        self.calls.append((property_id, source_id, as_of))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def tenant(factory: BookingFactory) -> Tenant:
    return factory.tenant()


def _evaluation(
    tenant: Tenant, status: EvaluationStatus, **overrides: Any
) -> OtaDependencyEvaluation:
    evaluation = ota_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=AS_OF,
        status=status,
    )
    return replace(evaluation, **overrides) if overrides else evaluation


def _clean_run(db_session: Session, tenant: Tenant) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40))


# --- the OTA share --------------------------------------------------------------------------------


def test_a_persisted_ota_decision_is_shown_with_its_own_figures_and_no_live_read(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, tenant),
        coverage=full_coverage(),
    )
    evaluator = Evaluator(
        AssertionError("the run is the authority: no live read when it has a decision")
    )

    distribution = overview_of(db_session, tenant, ota_evaluator=evaluator).distribution

    assert distribution.state is Availability.AVAILABLE
    assert distribution.outcome is OtaOutcome.DECISION
    assert distribution.ota_share_pct == D("75.00")
    assert distribution.direct_share_pct == D("25.00")  # the complement on OTA + direct
    assert distribution.reference_ota_share_pct == D("50.00")
    assert distribution.classification_coverage_pct == D("100.00")
    assert distribution.decision_id is not None
    assert evaluator.calls == []


def test_a_clean_live_evaluation_gives_the_observed_share_and_the_reference(
    db_session: Session, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)
    evaluator = Evaluator(_evaluation(tenant, CLEAR))

    distribution = overview_of(db_session, tenant, ota_evaluator=evaluator).distribution

    assert distribution.outcome is OtaOutcome.CLEAR
    assert (distribution.ota_share_pct, distribution.direct_share_pct) == (D("40.00"), D("60.00"))
    assert distribution.reference_ota_share_pct == D("50.00")
    assert distribution.decision_id is None
    # the live read uses the RUN's own booking source and the explicit analysis day
    assert evaluator.calls == [(tenant.property.id, tenant.data_source.id, AS_OF)]


def test_the_two_shares_always_add_up_to_one_hundred(db_session: Session, tenant: Tenant) -> None:
    _clean_run(db_session, tenant)
    evaluator = Evaluator(_evaluation(tenant, CLEAR, ota_share_exact=D("33.335")))

    distribution = overview_of(db_session, tenant, ota_evaluator=evaluator).distribution

    assert distribution.ota_share_pct is not None and distribution.direct_share_pct is not None
    assert distribution.ota_share_pct + distribution.direct_share_pct == D("100.00")


def test_an_insufficient_evaluation_says_why_and_never_looks_fine(
    db_session: Session, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)
    insufficient = _evaluation(
        tenant,
        INSUFFICIENT,
        ota_share_exact=None,
        direct_share_exact=None,
        expected_ota_share_exact=None,
        reason_codes=(ReasonCode.OTA_BOOKING_VOLUME_LOW, ReasonCode.OTA_NO_ON_BOOKS_DEMAND),
    )

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(insufficient)
    ).distribution

    assert distribution.outcome is OtaOutcome.INSUFFICIENT_DATA
    assert distribution.ota_share_pct is None  # never a made-up share
    assert distribution.insufficient_reasons == ("OTA_BOOKING_VOLUME_LOW", "OTA_NO_ON_BOOKS_DEMAND")


def test_a_low_confidence_result_is_marked_and_keeps_the_figure_it_has(
    db_session: Session, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, SUPPRESSED))
    ).distribution

    assert distribution.outcome is OtaOutcome.SUPPRESSED
    assert distribution.ota_share_pct == D("40.00")


def test_a_live_trigger_without_a_run_decision_shows_nothing_the_run_is_the_authority(
    db_session: Session, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, TRIGGERED))
    ).distribution

    assert distribution.outcome is OtaOutcome.CHANGED_AFTER_ANALYSIS
    assert distribution.ota_share_pct is None and distribution.direct_share_pct is None
    assert distribution.decision_id is None


def test_a_failing_live_read_degrades_to_not_available_never_a_guess(
    db_session: Session, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(RuntimeError("database down"))
    ).distribution

    assert distribution.state is Availability.NOT_AVAILABLE
    assert distribution.reason is UnavailableReason.EVALUATION_FAILED
    assert distribution.ota_share_pct is None


# --- states where nothing can be said -------------------------------------------------------------


def test_a_skipped_distribution_area_is_not_analysed_and_nothing_is_read(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        coverage=AnalysisCoverage(
            domains=tuple(
                DomainCoverage(
                    domain,
                    DomainCoverageStatus.SKIPPED
                    if domain is AnalysisDomain.DISTRIBUTION
                    else DomainCoverageStatus.EVALUATED,
                    DomainSkipReason.NOT_REQUESTED
                    if domain is AnalysisDomain.DISTRIBUTION
                    else None,
                )
                for domain in AnalysisDomain
            )
        ),
    )
    evaluator = Evaluator(AssertionError("must not be read"))

    distribution = overview_of(db_session, tenant, ota_evaluator=evaluator).distribution

    assert distribution.state is Availability.NOT_AVAILABLE
    assert distribution.reason is UnavailableReason.NOT_ANALYZED
    assert distribution.channel_mix is None  # no analysed area, no channel breakdown beside it
    assert evaluator.calls == []


def test_no_run_means_no_distribution(db_session: Session, tenant: Tenant) -> None:
    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(AssertionError("no run"))
    ).distribution

    assert distribution.reason is UnavailableReason.NO_ANALYSIS


def test_unrecorded_coverage_means_the_area_is_unknown(db_session: Session, tenant: Tenant) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, 20), unknown_coverage=True)

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(AssertionError("unknown coverage"))
    ).distribution

    assert distribution.reason is UnavailableReason.COVERAGE_UNKNOWN


def test_a_run_without_a_booking_source_has_no_distribution_figure(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, with_provenance=False)

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(AssertionError("no source"))
    ).distribution

    assert distribution.reason is UnavailableReason.NO_BOOKING_SOURCE


# --- the channel weights --------------------------------------------------------------------------


def _world(db_session: Session, factory: BookingFactory, tenant: Tenant) -> DistributionWorld:
    return DistributionWorld(db_session, tenant, factory)


def _book_channels(world: DistributionWorld) -> None:
    """12 rooms booked on every night of the next 30: Booking 5, Expedia 3, Diretto 2, Agency 2."""
    booking = world.channel("Booking.com")
    expedia = world.channel("Expedia")
    direct = world.channel("Diretto")
    agency = world.channel("Agency")
    world.uniform_bookings(
        AS_OF, AS_OF + timedelta(days=29), [(booking, 5), (expedia, 3), (direct, 2), (agency, 2)]
    )


def test_channel_weights_are_a_share_of_all_certain_room_nights(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)
    _book_channels(_world(db_session, factory, tenant))
    stub = Evaluator(_evaluation(tenant, CLEAR))

    distribution = overview_of(db_session, tenant, ota_evaluator=stub).distribution

    mix = distribution.channel_mix
    assert mix is not None
    assert mix.total_room_nights == 360  # 12 rooms x 30 nights
    by_name = {channel.name: channel for channel in mix.channels}
    assert by_name["Booking.com"].share_pct == D("41.67")  # 150 / 360
    assert by_name["Expedia"].share_pct == D("25.00")  # 90 / 360
    assert by_name["Diretto"].share_pct == D("16.67")  # 60 / 360
    assert by_name["Agency"].share_pct == D("16.67")
    assert by_name["Booking.com"].group is ChannelGroupName.OTA
    assert by_name["Diretto"].group is ChannelGroupName.DIRECT
    assert by_name["Agency"].group is ChannelGroupName.OTHER
    # ranked by weight, largest first
    assert [channel.name for channel in mix.channels][:2] == ["Booking.com", "Expedia"]


def test_the_channel_weight_and_the_ota_share_are_different_metrics(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)
    _book_channels(_world(db_session, factory, tenant))
    # The OTA share is over OTA + DIRECT only (other channels are not in its total): 8 / (8 + 2).
    # The Booking weight is over ALL channels (the agency counts): 5 / 12. Never mixed.
    stub = Evaluator(_evaluation(tenant, CLEAR, ota_share_exact=D("80.00")))

    distribution = overview_of(db_session, tenant, ota_evaluator=stub).distribution

    assert distribution.ota_share_pct == D("80.00")
    assert distribution.channel_mix is not None
    booking = next(c for c in distribution.channel_mix.channels if c.name == "Booking.com")
    expedia = next(c for c in distribution.channel_mix.channels if c.name == "Expedia")
    assert booking.share_pct + expedia.share_pct == D("66.67")  # the OTA weight of ALL room-nights
    assert booking.share_pct + expedia.share_pct != distribution.ota_share_pct


def test_a_cancelled_booking_is_not_counted_in_the_weights(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)
    world = _world(db_session, factory, tenant)
    booking = world.channel("Booking.com")
    direct = world.channel("Diretto")
    world.booking(booking, AS_OF, AS_OF + timedelta(days=30), rooms=1)
    world.booking(direct, AS_OF, AS_OF + timedelta(days=30), rooms=1)
    world.booking(
        booking,
        AS_OF,
        AS_OF + timedelta(days=30),
        rooms=4,
        status=CANCELLED,
        cancelled_at=datetime(2026, 7, 20, tzinfo=UTC),
    )

    mix = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution.channel_mix

    assert mix is not None
    assert mix.total_room_nights == 60  # the cancelled 4 rooms are nowhere
    assert {channel.name: channel.share_pct for channel in mix.channels} == {
        "Booking.com": D("50.00"),
        "Diretto": D("50.00"),
    }


def test_the_property_time_zone_decides_what_was_certain_at_the_end_of_the_day(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    """A booking cancelled at 20:00 UTC on the analysis day: in Rome (UTC+2) that is 22:00, already
    cancelled when the local day ends; in Auckland (UTC+12) it is 08:00 the NEXT local day, so the
    booking was still on the books at the end of the analysis day."""
    _clean_run(db_session, tenant)
    world = _world(db_session, factory, tenant)
    booking = world.channel("Booking.com")
    direct = world.channel("Diretto")
    world.booking(direct, AS_OF, AS_OF + timedelta(days=30), rooms=1)
    world.booking(
        booking,
        AS_OF,
        AS_OF + timedelta(days=30),
        rooms=1,
        status=CANCELLED,
        cancelled_at=datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
    )
    stub = Evaluator(_evaluation(tenant, CLEAR))

    rome = overview_of(db_session, tenant, ota_evaluator=stub).distribution.channel_mix
    tenant.property.timezone = "Pacific/Auckland"
    db_session.flush()
    auckland = overview_of(db_session, tenant, ota_evaluator=stub).distribution.channel_mix

    assert rome is not None and auckland is not None
    assert {channel.name for channel in rome.channels} == {"Diretto"}
    assert {channel.name for channel in auckland.channels} == {"Diretto", "Booking.com"}


def test_a_property_without_certain_bookings_has_no_channel_breakdown(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)
    _world(db_session, factory, tenant).channel("Booking.com")  # a channel, but no booking at all

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution

    assert distribution.channel_mix is None  # never an empty breakdown, never 0 %


def test_another_tenants_channels_and_bookings_are_invisible(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _clean_run(db_session, tenant)
    foreign = factory.tenant()
    _book_channels(DistributionWorld(db_session, foreign, factory))

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution

    assert distribution.channel_mix is None


# --- what the weights are a share of, and why it may not be the room-nights on the books ----------
#
# The real demo property of the product review showed "the channel composition does not match the
# registered bookings" beside channel weights. Root cause, measured on its data: some bookings carry
# a booking date AFTER the analysis day, and some are no-shows for stays that had not begun. The
# analysis day's observation counts a booking by its status as it is; Gate 3's certainty rule at
# the end of the day (the OTA check's and the weights' own) asks whether it existed yet and whether
# a no-show could be known. Both rules agree on real dates and disagree only on such dates, so the
# check is right to refuse; the weights now say what they are a share of, and why.

_LATER = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)  # the morning after the analysis day (Rome)


def _observed(db_session: Session, tenant: Tenant, rooms: int, *, days: int = 30) -> None:
    """The analysis day's observation: `rooms` booked on each of `days` nights, no capacity."""
    seed_run(
        db_session, tenant, nights=uniform_nights(AS_OF, rooms=rooms, capacity=None, days=days)
    )


def _end(days: int = 30) -> date:
    return AS_OF + timedelta(days=days)


def test_consistent_dates_reconcile_and_the_weights_are_the_room_nights_on_the_books(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=2)
    world = _world(db_session, factory, tenant)
    world.booking(world.channel("Booking.com"), AS_OF, _end())
    world.booking(world.channel("Diretto"), AS_OF, _end())

    distribution = overview_of(db_session, tenant).distribution  # the REAL OTA check

    # reconciled: the check goes past it (and stops later, on the missing history)
    assert distribution.insufficient_reasons == ("OTA_COMPARABLE_SAMPLE_INSUFFICIENT",)
    mix = distribution.channel_mix
    assert mix is not None
    assert (mix.total_room_nights, mix.on_books_room_nights, mix.matches_on_books) == (60, 60, True)
    assert distribution.date_conflicts == BookingDateConflicts(0, 0, 0)


def test_a_booking_dated_after_the_analysis_day_fails_the_real_reconciliation_and_says_why(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=2)  # the observation counts it: it is CONFIRMED
    world = _world(db_session, factory, tenant)
    world.booking(world.channel("Booking.com"), AS_OF, _end())
    world.booking(world.channel("Diretto"), AS_OF, _end(), booked_at=_LATER)

    distribution = overview_of(db_session, tenant).distribution

    assert distribution.outcome is OtaOutcome.INSUFFICIENT_DATA
    assert distribution.insufficient_reasons == ("OTA_CHANNEL_MIX_RECONCILIATION_FAILED",)
    assert distribution.ota_share_pct is None  # still not evaluated: the check is right
    assert distribution.date_conflicts == BookingDateConflicts(
        booked_after=1, cancelled_after=0, no_show_before_arrival=0
    )
    mix = distribution.channel_mix
    assert mix is not None
    # the weights are a share of 30 certain room-nights, not of the 60 observed: said, not hidden
    assert (mix.total_room_nights, mix.on_books_room_nights, mix.matches_on_books) == (
        30,
        60,
        False,
    )
    assert [(channel.name, channel.share_pct) for channel in mix.channels] == [
        ("Booking.com", D("100.00"))
    ]


def test_a_no_show_before_its_arrival_is_a_date_conflict(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=1)  # the observation never counts a no-show
    world = _world(db_session, factory, tenant)
    booking = world.channel("Booking.com")
    world.booking(booking, AS_OF, _end())
    world.booking(booking, AS_OF + timedelta(days=5), AS_OF + timedelta(days=7), status=NO_SHOW)

    distribution = overview_of(db_session, tenant).distribution

    assert distribution.insufficient_reasons == ("OTA_CHANNEL_MIX_RECONCILIATION_FAILED",)
    assert distribution.date_conflicts == BookingDateConflicts(0, 0, 1)
    mix = distribution.channel_mix
    assert mix is not None
    assert (mix.total_room_nights, mix.on_books_room_nights, mix.matches_on_books) == (
        32,
        30,
        False,
    )


def test_a_no_show_whose_stay_has_begun_is_no_conflict(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=1)
    world = _world(db_session, factory, tenant)
    booking = world.channel("Booking.com")
    world.booking(booking, AS_OF, _end())
    world.booking(booking, AS_OF, AS_OF + timedelta(days=2), status=NO_SHOW)  # arrival: today

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution

    assert distribution.date_conflicts == BookingDateConflicts(0, 0, 0)
    assert distribution.channel_mix is not None
    assert distribution.channel_mix.matches_on_books is True


def test_a_cancellation_dated_after_the_analysis_day_is_a_date_conflict(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=1)
    world = _world(db_session, factory, tenant)
    booking = world.channel("Booking.com")
    world.booking(booking, AS_OF, _end())
    world.booking(booking, AS_OF, _end(), status=CANCELLED, cancelled_at=_LATER)

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution

    assert distribution.date_conflicts == BookingDateConflicts(0, 1, 0)
    assert distribution.channel_mix is not None
    assert distribution.channel_mix.matches_on_books is False


def test_cancellations_dated_in_time_or_undated_are_in_neither_count_and_no_conflict(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=1)
    world = _world(db_session, factory, tenant)
    booking = world.channel("Booking.com")
    world.booking(booking, AS_OF, _end())
    world.booking(
        booking, AS_OF, _end(), status=CANCELLED, cancelled_at=datetime(2026, 7, 20, tzinfo=UTC)
    )
    world.booking(booking, AS_OF, _end(), status=CANCELLED)  # no cancellation date: uncertain

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution

    assert distribution.date_conflicts == BookingDateConflicts(0, 0, 0)
    mix = distribution.channel_mix
    assert mix is not None
    assert (mix.total_room_nights, mix.matches_on_books) == (30, True)


def test_unclassified_channels_stay_in_the_total_and_are_counted_apart(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=4)
    world = _world(db_session, factory, tenant)
    world.booking(world.channel("Booking.com"), AS_OF, _end())
    world.booking(world.channel("Sito diretto"), AS_OF, _end())
    world.booking(world.channel("Agency"), AS_OF, _end())
    world.booking(world.channel("Telefono / Email"), AS_OF, _end())

    mix = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution.channel_mix

    assert mix is not None
    # every weight is over ALL 120 room-nights: the unclassified 30 are in it, and counted apart
    assert (mix.total_room_nights, mix.classified_room_nights, mix.unclassified_room_nights) == (
        120,
        60,
        30,
    )
    assert {channel.name: channel.group for channel in mix.channels} == {
        "Booking.com": ChannelGroupName.OTA,
        "Sito diretto": ChannelGroupName.DIRECT,
        "Agency": ChannelGroupName.OTHER,
        "Telefono / Email": ChannelGroupName.UNKNOWN,
    }
    assert all(channel.share_pct == D("25.00") for channel in mix.channels)
    assert mix.matches_on_books is True


def test_the_weights_and_the_room_nights_on_the_books_cover_the_same_thirty_nights(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=1)
    world = _world(db_session, factory, tenant)
    booking = world.channel("Booking.com")
    world.booking(booking, AS_OF, _end())
    world.booking(booking, _end(), _end() + timedelta(days=3))  # after the 30th night: in neither

    overview = overview_of(
        db_session, tenant, period=7, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    )

    month = overview.occupancy.days_30
    assert month is not None
    assert forward_window(AS_OF) == (month.start_date, month.end_date)
    mix = overview.distribution.channel_mix
    assert mix is not None
    # the period shown (7 nights) never changes the 30 nights the weights are checked against
    assert (mix.total_room_nights, mix.on_books_room_nights) == (30, month.room_nights)


def test_an_observation_missing_a_night_gives_no_total_to_check_the_weights_against(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _observed(db_session, tenant, rooms=1, days=29)
    world = _world(db_session, factory, tenant)
    world.booking(world.channel("Booking.com"), AS_OF, _end())

    mix = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(_evaluation(tenant, CLEAR))
    ).distribution.channel_mix

    assert mix is not None
    assert (mix.on_books_room_nights, mix.matches_on_books) == (None, None)  # a part is no total


def test_an_area_that_was_not_read_has_no_date_conflicts(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, with_provenance=False)

    distribution = overview_of(
        db_session, tenant, ota_evaluator=Evaluator(AssertionError("no source"))
    ).distribution

    assert distribution.date_conflicts is None
