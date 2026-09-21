"""RevenueDecisionService against PostgreSQL (Gate 5, groups A, P and Q).

Snapshots are inserted directly (Core) so each test controls exactly which history exists; the
Expected baseline is then calculated by the REAL Gate 4 service, and the revenue service reads,
pairs and evaluates through the real repositories.
"""

import inspect
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking
from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.revenue.errors import RevenueDecisionError, RevenueErrorCode
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    OccupancyFacts,
    PickupFacts,
    ReasonCode,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
)
from app.modules.snapshots.models import BookingSnapshot
from tests.revenue_support import (
    ELIGIBLE,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    RevenueWorld,
    snap,
)
from tests.support import BookingFactory

D = Decimal
S = EvaluationStatus
R = ReasonCode
CLEAN_STAYS = ELIGIBLE[2:14]  # 12 Gate 4 comparables whose finals are all known at the target day


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> RevenueWorld:
    """20 of 40 rooms today, 12 a week ago; history: 16 -> 26 (a pickup of 10) -> 34 final."""
    built = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    built.own_prior(12)
    built.curves(CLEAN_STAYS, prior=16, anchor=26, final=34)
    built.calculate()
    return built


def pickup_facts(evaluation: RevenueDecisionEvaluation) -> PickupFacts:
    assert isinstance(evaluation.facts, PickupFacts)
    return evaluation.facts


def occupancy_facts(evaluation: RevenueDecisionEvaluation) -> OccupancyFacts:
    assert isinstance(evaluation.facts, OccupancyFacts)
    return evaluation.facts


def count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def error_of(world: RevenueWorld, target_id: uuid.UUID | None = None) -> RevenueDecisionError:
    with pytest.raises(RevenueDecisionError) as raised:
        world.service().evaluate_revenue_signals(target_id or world.target_id)
    return raised.value


# --- A: the target ---------------------------------------------------------------------------


def test_both_detectors_evaluate_an_observed_target_through_the_real_baseline(
    world: RevenueWorld,
) -> None:
    signals = world.service().evaluate_revenue_signals(world.target_id)
    pickup, occupancy = signals.pickup_low, signals.occupancy_risk

    assert (pickup.status, occupancy.status) == (S.TRIGGERED, S.TRIGGERED)
    assert pickup.reason_codes == (R.TRIGGER_PICKUP_SHORTFALL,)
    assert occupancy.reason_codes == (R.TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL,)
    for evaluation in (pickup, occupancy):
        assert evaluation.workspace_id == world.tenant.workspace.id
        assert evaluation.property_id == world.tenant.property.id
        assert evaluation.data_source_id == world.tenant.data_source.id
        assert evaluation.target_snapshot_id == world.target_id
        assert evaluation.target_baseline_id == world.baseline().id
        assert evaluation.snapshot_local_date == TARGET_SNAPSHOT_DAY
        assert evaluation.stay_date == TARGET_STAY
        assert evaluation.lead_time_days == 14
        assert evaluation.rules_version == "revenue-decisions-v1"
        assert evaluation.confidence_score == D("100.00")


def test_the_pickup_and_occupancy_facts_of_the_reference_world(world: RevenueWorld) -> None:
    pickup = world.service().evaluate_pickup_low(world.target_id)
    occupancy = world.service().evaluate_occupancy_risk(world.target_id)

    facts = pickup_facts(pickup)  # 20 - 12 = 8 actual; each of the 12 nights picked up 26 - 16 = 10
    assert (facts.actual_pickup, facts.expected_pickup) == (8, D("10.00"))
    assert (facts.delta_rooms, facts.missing_rooms, facts.delta_percent) == (
        D("-2.00"),
        D("2.00"),
        D("-20.00"),
    )
    assert pickup.revenue_gap_proxy == D("200.00")  # 2 rooms x the current ADR of 100.00
    assert pickup.reference_adr_source == ReferenceAdrSource.CURRENT_ON_BOOKS_ADR

    other = occupancy_facts(occupancy)  # 20 now + 8 to come = 28; the nights usually end at 34
    assert other.expected_remaining_net_pickup == D("8.00")
    assert other.forecast_rooms == D("28.00")
    assert other.expected_final_rooms == D("34.00")
    assert (other.forecast_occupancy, other.expected_final_occupancy) == (D("70.00"), D("85.00"))
    assert (other.room_shortfall, other.occupancy_gap_pp) == (D("6.00"), D("15.00"))
    assert occupancy.revenue_gap_proxy == D("600.00")


def test_the_single_calls_agree_with_the_combined_one(world: RevenueWorld) -> None:
    service = world.service()
    signals = service.evaluate_revenue_signals(world.target_id)
    assert service.evaluate_pickup_low(world.target_id) == signals.pickup_low
    assert service.evaluate_occupancy_risk(world.target_id) == signals.occupancy_risk


def test_a_reconstructed_target_is_refused(world: RevenueWorld) -> None:
    row = snap(world.tenant, TARGET_SNAPSHOT_DAY, date(2026, 8, 22), 10, origin=RECONSTRUCTED)
    world.add(row)
    error = error_of(world, row["id"])
    assert error.error_code == RevenueErrorCode.TARGET_NOT_OBSERVED
    assert error.details == {"origin": "RECONSTRUCTED_APPROXIMATE"}


def test_an_unknown_target_is_not_found(world: RevenueWorld) -> None:
    assert error_of(world, uuid.uuid4()).error_code == RevenueErrorCode.TARGET_NOT_FOUND


def test_a_target_whose_night_is_already_over_is_refused(world: RevenueWorld) -> None:
    row = snap(world.tenant, TARGET_SNAPSHOT_DAY, TARGET_SNAPSHOT_DAY - timedelta(days=1), 10)
    world.add(row)
    error = error_of(world, row["id"])
    assert error.error_code == RevenueErrorCode.INVALID_TARGET
    assert error.details == {"reason": "negative_lead_time"}


def test_a_target_on_its_own_stay_date_is_evaluated(world: RevenueWorld) -> None:
    row = snap(world.tenant, TARGET_STAY, TARGET_STAY, 30, available=40)
    world.add(row)
    evaluation = world.service().evaluate_pickup_low(row["id"])
    assert evaluation.lead_time_days == 0
    assert evaluation.status == S.INSUFFICIENT_DATA  # no Expected baseline was calculated for it


def test_a_data_source_of_another_domain_is_refused(
    world: RevenueWorld, factory: BookingFactory
) -> None:
    costs = factory.data_source(world.tenant.property, DataSourceDomain.COSTS)
    row = snap(world.tenant, TARGET_SNAPSHOT_DAY, date(2026, 8, 22), 10, data_source_id=costs.id)
    world.add(row)
    error = error_of(world, row["id"])
    assert error.error_code == RevenueErrorCode.INVALID_DATA_SOURCE
    assert error.details == {"reason": "wrong_domain"}


def test_an_inactive_data_source_or_archived_property_is_refused(world: RevenueWorld) -> None:
    world.tenant.data_source.is_active = False
    assert error_of(world).details == {"reason": "inactive"}
    world.tenant.data_source.is_active = True
    world.tenant.property.is_active = False
    world.tenant.property.archived_at = datetime(2026, 1, 1, tzinfo=UTC)
    error = error_of(world)
    assert error.error_code == RevenueErrorCode.INVALID_PROPERTY
    assert error.details == {"reason": "archived"}


def test_a_missing_baseline_is_insufficient_data_for_both_detectors(
    db_session: Session, factory: BookingFactory
) -> None:
    bare = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    bare.own_prior(12)
    signals = bare.service().evaluate_revenue_signals(bare.target_id)
    for evaluation in (signals.pickup_low, signals.occupancy_risk):
        assert evaluation.status == S.INSUFFICIENT_DATA
        assert evaluation.reason_codes == (R.EXPECTED_BASELINE_MISSING,)
        assert evaluation.target_baseline_id is None


def test_an_insufficient_baseline_is_insufficient_data(
    db_session: Session, factory: BookingFactory
) -> None:
    thin = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    thin.own_prior(12)
    thin.curves(CLEAN_STAYS[:4], prior=16, anchor=26, final=34)  # only 4 comparables
    thin.calculate()
    signals = thin.service().evaluate_revenue_signals(thin.target_id)
    for evaluation in (signals.pickup_low, signals.occupancy_risk):
        assert evaluation.status == S.INSUFFICIENT_DATA
        assert evaluation.reason_codes == (R.EXPECTED_BASELINE_INSUFFICIENT,)
        assert evaluation.target_baseline_id == thin.baseline().id


# --- A: the target's own prior ---------------------------------------------------------------


def test_the_prior_must_be_exactly_seven_snapshot_days_earlier(
    db_session: Session, factory: BookingFactory
) -> None:
    near = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    for days in (6, 8):  # a day too late and a day too early are not "7 days earlier"
        near.add(snap(near.tenant, TARGET_SNAPSHOT_DAY - timedelta(days=days), TARGET_STAY, 12))
    near.curves(CLEAN_STAYS, prior=16, anchor=26, final=34)
    near.calculate()
    evaluation = near.service().evaluate_pickup_low(near.target_id)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.PICKUP_PRIOR_OBSERVATION_MISSING,)


def test_a_reconstructed_prior_is_not_enough(db_session: Session, factory: BookingFactory) -> None:
    rebuilt = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    rebuilt.own_prior(12, origin=RECONSTRUCTED)
    rebuilt.curves(CLEAN_STAYS, prior=16, anchor=26, final=34)
    rebuilt.calculate()
    evaluation = rebuilt.service().evaluate_pickup_low(rebuilt.target_id)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.PICKUP_PRIOR_OBSERVATION_MISSING,)
    # the occupancy risk does not need the prior at all
    assert rebuilt.service().evaluate_occupancy_risk(rebuilt.target_id).status == S.TRIGGERED


# --- B (database): the pairs are the Gate 4 comparables --------------------------------------


def pair_days(evaluation: RevenueDecisionEvaluation) -> list[date]:
    facts = evaluation.facts
    assert facts.pattern is not None
    return [pair.stay_date for pair in facts.pattern.pairs]


def test_the_pairs_are_the_stored_gate_4_comparables_and_nothing_else(world: RevenueWorld) -> None:
    saturday_in_winter = date(2026, 1, 10)  # a Saturday, but far outside the seasonal window
    friday_in_season = date(2026, 7, 24)  # inside the window, but another weekday
    world.curve(saturday_in_winter, prior=1, anchor=1, final=1)
    world.curve(friday_in_season, prior=1, anchor=1, final=1)
    world.curve(ELIGIBLE[14], prior=1, anchor=1, final=1)  # a good candidate that arrived LATER
    world.curve(date(2026, 7, 25) - timedelta(days=28), prior=1, anchor=1, final=1, lead=13)
    stored = {
        row.snapshot_id
        for row in world.session.scalars(
            select(BookingExpectedComparable).where(
                BookingExpectedComparable.baseline_id == world.baseline().id
            )
        )
    }
    evaluation = world.service().evaluate_pickup_low(world.target_id)
    anchors = {
        pair.anchor_snapshot_id
        for pair in (evaluation.facts.pattern.pairs if evaluation.facts.pattern else ())
    }
    assert anchors == stored
    assert sorted(pair_days(evaluation), reverse=True) == pair_days(evaluation)
    assert saturday_in_winter not in pair_days(evaluation)
    assert friday_in_season not in pair_days(evaluation)
    assert ELIGIBLE[14] not in pair_days(evaluation)  # the stored baseline is the only authority


def test_each_detector_uses_its_own_endpoints(db_session: Session, factory: BookingFactory) -> None:
    # a comparable without a prior loses only its PICKUP pair; without a final, only its REMAINING
    fresh = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    fresh.own_prior(12)
    stays = CLEAN_STAYS
    fresh.curve(stays[0], prior=None, anchor=26, final=34)
    fresh.curve(stays[1], prior=16, anchor=26, final=None)
    fresh.curves(stays[2:], prior=16, anchor=26, final=34)
    fresh.calculate()
    pickup = pickup_facts(fresh.service().evaluate_pickup_low(fresh.target_id))
    occupancy = occupancy_facts(fresh.service().evaluate_occupancy_risk(fresh.target_id))
    assert pickup.pattern is not None and occupancy.pattern is not None
    assert (pickup.pattern.pair_count, pickup.pattern.missing_endpoint_count) == (11, 1)
    assert (occupancy.pattern.pair_count, occupancy.pattern.missing_endpoint_count) == (11, 1)
    assert stays[0] not in [p.stay_date for p in pickup.pattern.pairs]
    assert stays[1] in [p.stay_date for p in pickup.pattern.pairs]
    assert stays[0] in [p.stay_date for p in occupancy.pattern.pairs]
    assert stays[1] not in [p.stay_date for p in occupancy.pattern.pairs]


def test_a_pair_with_an_uncertain_endpoint_is_excluded_and_counted(
    db_session: Session, factory: BookingFactory
) -> None:
    fresh = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    fresh.own_prior(12)
    fresh.curve(
        CLEAN_STAYS[0], prior=16, anchor=26, final=34, prior_origin=RECONSTRUCTED, prior_uncertain=3
    )
    fresh.curves(CLEAN_STAYS[1:], prior=16, anchor=26, final=34)
    fresh.calculate()
    facts = pickup_facts(fresh.service().evaluate_pickup_low(fresh.target_id))
    assert facts.pattern is not None
    assert facts.pattern.pair_count == 11
    assert facts.pattern.rejected_uncertain_count == 1


def test_a_reconstructed_endpoint_makes_an_approximate_pair_used_only_below_five_observed(
    db_session: Session, factory: BookingFactory
) -> None:
    mixed = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    mixed.own_prior(12)
    mixed.curves(CLEAN_STAYS[:3], prior=16, anchor=26, final=34)  # 3 observed pairs
    mixed.curves(CLEAN_STAYS[3:9], prior=16, anchor=26, final=34, prior_origin=RECONSTRUCTED)
    mixed.calculate()
    pattern = pickup_facts(mixed.service().evaluate_pickup_low(mixed.target_id)).pattern
    assert pattern is not None
    assert (pattern.observed_pair_count, pattern.approximate_pair_count) == (3, 6)
    assert pattern.pattern_confidence is not None and pattern.pattern_confidence <= D(85)

    enough = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    enough.own_prior(12)
    enough.curves(CLEAN_STAYS[:5], prior=16, anchor=26, final=34)
    enough.curves(CLEAN_STAYS[5:9], prior=16, anchor=26, final=34, prior_origin=RECONSTRUCTED)
    enough.calculate()
    pattern = pickup_facts(enough.service().evaluate_pickup_low(enough.target_id)).pattern
    assert pattern is not None
    assert (pattern.observed_pair_count, pattern.approximate_pair_count) == (5, 0)


# --- no temporal leakage (database) ----------------------------------------------------------


def test_a_comparable_whose_final_is_not_yet_known_never_enters_the_remaining_pairs(
    db_session: Session, factory: BookingFactory
) -> None:
    # 2026-08-08 and 2026-08-01 are Gate 4 comparables (their anchors are before the target day)
    # but their FINAL snapshots (on 08-08 and on 08-01) are not known at the target day 08-01.
    fresh = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    fresh.own_prior(12)
    fresh.curves(ELIGIBLE[2:14], prior=16, anchor=26, final=34)
    fresh.curves(ELIGIBLE[:2], prior=16, anchor=26, final=999)  # a wild future
    fresh.calculate()
    facts = occupancy_facts(fresh.service().evaluate_occupancy_risk(fresh.target_id))
    assert facts.pattern is not None
    assert facts.pattern.excluded_future_count == 2
    assert facts.pattern.pair_count == 12
    assert facts.expected_final_rooms == D("34.00")  # the 999s left no trace
    assert facts.expected_remaining_net_pickup == D("8.00")
    for future in ELIGIBLE[:2]:
        assert future not in [pair.stay_date for pair in facts.pattern.pairs]


def test_the_pickup_pairs_of_those_same_comparables_are_kept(
    db_session: Session, factory: BookingFactory
) -> None:
    fresh = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    fresh.own_prior(12)
    fresh.curves(ELIGIBLE[:14], prior=16, anchor=26, final=999)
    fresh.calculate()
    facts = pickup_facts(fresh.service().evaluate_pickup_low(fresh.target_id))
    assert facts.pattern is not None
    assert facts.pattern.pair_count == 14  # the pickup only needs snapshots before the target day
    assert facts.pattern.excluded_future_count == 0


# --- Q: tenant, property and data-source isolation -------------------------------------------


def test_the_service_needs_a_tenant_context(db_session: Session) -> None:
    with pytest.raises(TypeError):
        RevenueDecisionService(db_session, uuid.uuid4())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RevenueDecisionService(db_session, None)  # type: ignore[arg-type]


def test_a_target_of_another_workspace_is_indistinguishable_from_a_missing_one(
    world: RevenueWorld, db_session: Session, factory: BookingFactory
) -> None:
    foreign = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    foreign_error = error_of(world, foreign.target_id)
    unknown_error = error_of(world, uuid.uuid4())
    assert foreign_error.error_code == unknown_error.error_code == RevenueErrorCode.TARGET_NOT_FOUND
    assert foreign_error.message == unknown_error.message
    assert foreign_error.status_code == unknown_error.status_code


def test_another_workspace_with_identical_dates_never_leaks_into_the_pairs(
    world: RevenueWorld, db_session: Session, factory: BookingFactory
) -> None:
    before = world.service().evaluate_revenue_signals(world.target_id)
    other = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    other.own_prior(1)
    other.curves(CLEAN_STAYS, prior=0, anchor=1, final=2)  # same dates, wildly different rooms
    other.calculate()
    after = world.service().evaluate_revenue_signals(world.target_id)
    assert after == before
    # and the other workspace sees only its own history
    theirs = other.service().evaluate_pickup_low(other.target_id)
    assert pickup_facts(theirs).expected_pickup == D("1.00")


def test_another_data_source_of_the_same_property_is_never_mixed_in(
    world: RevenueWorld, factory: BookingFactory
) -> None:
    before = world.service().evaluate_revenue_signals(world.target_id)
    second = factory.data_source(world.tenant.property)
    rows = []
    for stay in CLEAN_STAYS:
        for day, rooms in (
            (stay - timedelta(days=21), 0),
            (stay - timedelta(days=14), 1),
            (stay, 2),
        ):
            rows.append(snap(world.tenant, day, stay, rooms, data_source_id=second.id))
    world.add(*rows)
    assert world.service().evaluate_revenue_signals(world.target_id) == before


def test_another_property_of_the_same_workspace_is_never_mixed_in(
    world: RevenueWorld, factory: BookingFactory
) -> None:
    before = world.service().evaluate_revenue_signals(world.target_id)
    other_property = factory.property(world.tenant.workspace)
    other_source = factory.data_source(other_property)
    rows = []
    for stay in CLEAN_STAYS:
        for day, rooms in (
            (stay - timedelta(days=21), 0),
            (stay - timedelta(days=14), 1),
            (stay, 2),
        ):
            row = snap(world.tenant, day, stay, rooms, data_source_id=other_source.id)
            row["property_id"] = other_property.id
            rows.append(row)
    world.add(*rows)
    assert world.service().evaluate_revenue_signals(world.target_id) == before


# --- P: read-only ----------------------------------------------------------------------------


def test_evaluating_writes_nothing(world: RevenueWorld) -> None:
    session = world.session
    tables = (BookingSnapshot, BookingExpectedBaseline, BookingExpectedComparable, Booking)
    before = [count(session, model) for model in tables]
    baseline = world.baseline()
    fingerprint = baseline.comparable_fingerprint
    session.expire_all()

    world.service().evaluate_revenue_signals(world.target_id)

    assert [count(session, model) for model in tables] == before
    assert not (session.new or session.dirty or session.deleted)
    assert world.baseline().comparable_fingerprint == fingerprint


def test_the_service_only_reads_and_never_commits_locks_or_rolls_back(world: RevenueWorld) -> None:
    session = world.session
    statements: list[str] = []
    events: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", record)
    event.listen(session, "after_commit", lambda s: events.append("commit"))
    event.listen(session, "after_rollback", lambda s: events.append("rollback"))
    try:
        world.service().evaluate_revenue_signals(world.target_id)
    finally:
        event.remove(connection, "before_cursor_execute", record)

    assert statements
    for statement in statements:
        lowered = statement.lstrip().lower()
        assert lowered.startswith("select"), statement
        assert "pg_advisory" not in lowered
        assert "for update" not in lowered
    assert events == []


def test_the_service_has_no_clock_and_no_writer_in_its_interface() -> None:
    assert "clock" not in inspect.signature(RevenueDecisionService.__init__).parameters
    public = {name for name in dir(RevenueDecisionService) if not name.startswith("_")}
    assert public == {
        "evaluate_pickup_low",
        "evaluate_occupancy_risk",
        "evaluate_revenue_signals",
        "evaluate_snapshot_date",
    }


def test_repeating_an_evaluation_gives_the_same_result(world: RevenueWorld) -> None:
    service = world.service()
    first = service.evaluate_revenue_signals(world.target_id)
    world.session.expire_all()
    second = service.evaluate_revenue_signals(world.target_id)
    assert first == second
    assert first.pickup_low.calculation_fingerprint == second.pickup_low.calculation_fingerprint


def test_the_order_in_which_history_was_stored_does_not_change_the_evaluation(
    db_session: Session, factory: BookingFactory
) -> None:
    results = []
    for stays in (CLEAN_STAYS, list(reversed(CLEAN_STAYS))):
        built = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
        built.own_prior(12)
        built.curves(stays, prior=16, anchor=26, final=34)
        built.calculate()
        signals = built.service().evaluate_revenue_signals(built.target_id)
        results.append(
            (
                signals.pickup_low.status,
                pickup_facts(signals.pickup_low).expected_pickup,
                signals.occupancy_risk.status,
                signals.occupancy_risk.revenue_gap_proxy,
                pair_days(signals.pickup_low),
            )
        )
    assert results[0] == results[1]


# --- the optional batch ----------------------------------------------------------------------


def test_the_batch_evaluates_every_observed_target_of_a_snapshot_day(
    world: RevenueWorld,
) -> None:
    second_stay = TARGET_STAY + timedelta(days=1)  # the Sunday after, seen 15 days before
    second = snap(world.tenant, TARGET_SNAPSHOT_DAY, second_stay, 25, available=40)
    world.add(second)
    world.add(snap(world.tenant, TARGET_SNAPSHOT_DAY - timedelta(days=7), second_stay, 20))
    sundays = [stay + timedelta(days=1) for stay in CLEAN_STAYS]
    world.curves(sundays, prior=16, anchor=26, final=34, lead=15)
    world.calculate(second["id"])
    world.add(snap(world.tenant, TARGET_SNAPSHOT_DAY, date(2026, 8, 29), 5, origin=RECONSTRUCTED))
    world.add(snap(world.tenant, TARGET_SNAPSHOT_DAY, TARGET_SNAPSHOT_DAY - timedelta(days=1), 5))
    world.session.commit()

    batch = world.service().evaluate_snapshot_date(
        property_id=world.tenant.property.id,
        data_source_id=world.tenant.data_source.id,
        snapshot_local_date=TARGET_SNAPSHOT_DAY,
        stay_date_start=TARGET_SNAPSHOT_DAY - timedelta(days=30),
        stay_date_end=TARGET_SNAPSHOT_DAY + timedelta(days=60),
    )

    assert [s.pickup_low.stay_date for s in batch] == [TARGET_STAY, second_stay]  # earliest first
    assert [s.pickup_low.target_snapshot_id for s in batch] == [world.target_id, second["id"]]
    service = world.service()
    assert batch[0] == service.evaluate_revenue_signals(world.target_id)
    assert batch[1] == service.evaluate_revenue_signals(second["id"])  # batch == one by one


def test_an_empty_batch_is_an_empty_result(world: RevenueWorld) -> None:
    assert (
        world.service().evaluate_snapshot_date(
            property_id=world.tenant.property.id,
            data_source_id=world.tenant.data_source.id,
            snapshot_local_date=date(2030, 1, 1),
            stay_date_start=date(2030, 1, 1),
            stay_date_end=date(2030, 1, 31),
        )
        == ()
    )


def test_batch_arguments_are_validated(world: RevenueWorld, factory: BookingFactory) -> None:
    service = world.service()
    base: dict[str, Any] = {
        "property_id": world.tenant.property.id,
        "data_source_id": world.tenant.data_source.id,
        "snapshot_local_date": TARGET_SNAPSHOT_DAY,
        "stay_date_start": TARGET_STAY,
        "stay_date_end": TARGET_STAY,
    }
    with pytest.raises(RevenueDecisionError) as reversed_range:
        service.evaluate_snapshot_date(**{**base, "stay_date_end": TARGET_STAY - timedelta(days=1)})
    assert reversed_range.value.error_code == RevenueErrorCode.INVALID_RANGE
    with pytest.raises(RevenueDecisionError) as too_long:
        service.evaluate_snapshot_date(
            **{**base, "stay_date_end": TARGET_STAY + timedelta(days=800)}
        )
    assert too_long.value.details is not None and too_long.value.details["reason"] == "too_long"
    with pytest.raises(TypeError):
        service.evaluate_snapshot_date(**{**base, "snapshot_local_date": datetime(2026, 8, 1)})
    foreign = factory.tenant()
    with pytest.raises(RevenueDecisionError) as wrong_source:
        service.evaluate_snapshot_date(**{**base, "data_source_id": foreign.data_source.id})
    assert wrong_source.value.error_code == RevenueErrorCode.INVALID_DATA_SOURCE
    with pytest.raises(RevenueDecisionError) as wrong_property:
        service.evaluate_snapshot_date(**{**base, "property_id": foreign.property.id})
    assert wrong_property.value.error_code == RevenueErrorCode.INVALID_PROPERTY
