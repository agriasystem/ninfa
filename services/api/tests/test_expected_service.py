"""BookingExpectedService: OBSERVED target snapshots -> immutable Expected baselines.

Snapshots are inserted directly (Core) so that each test controls exactly which history exists;
the service then reads, calculates and stores through the real repositories and PostgreSQL.
"""

import inspect
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.expected.calculator import (
    CALCULATION_VERSION,
    METHOD,
    ExpectedStatus,
    comparable_fingerprint,
    compute_expected,
)
from app.modules.intelligence.expected.confidence import ConfidenceBand
from app.modules.intelligence.expected.errors import ExpectedError, ExpectedErrorCode
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.intelligence.expected.selection import Candidate, HistoricalTarget
from app.modules.intelligence.expected.service import BookingExpectedService
from app.modules.snapshots.models import BookingSnapshot
from tests.expected_support import (
    ELIGIBLE,
    LEAD,
    OBSERVED,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    Scenario,
    add_snapshots,
    snapshot_row,
)
from tests.support import BookingFactory


@pytest.fixture
def scenario(db_session: Session, factory: BookingFactory) -> Scenario:
    return Scenario.create(db_session, factory)


def count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def comparables_of(scenario: Scenario) -> list[BookingExpectedComparable]:
    baseline = scenario.baseline()
    return list(
        ExpectedRepository(scenario.session, scenario.tenant.context).list_comparables(baseline.id)
    )


def expected_error(scenario: Scenario, **overrides: Any) -> ExpectedError:
    scenario.commit()
    arguments: dict[str, Any] = {
        "property_id": scenario.tenant.property.id,
        "data_source_id": scenario.tenant.data_source.id,
        "target_snapshot_id": scenario.target_id,
    }
    arguments.update(overrides)
    with pytest.raises(ExpectedError) as info:
        scenario.service().calculate_for_target(**arguments)
    return info.value


# --- G. a READY baseline ----------------------------------------------------------------------


def test_six_observed_comparables_give_a_ready_baseline_with_the_expected_numbers(
    scenario: Scenario,
) -> None:
    scenario.add_history(ELIGIBLE[:6], rooms=[10, 12, 14, 16, 18, 20])

    result = scenario.calculate()

    baseline = scenario.baseline()
    assert (result.created, result.unchanged, result.ready, result.insufficient) == (1, 0, 1, 0)
    assert baseline.status == ExpectedStatus.READY
    assert baseline.expected_rooms_on_books == Decimal("15.00")  # the median
    assert (baseline.expected_lower, baseline.expected_upper) == (
        Decimal("12.50"),
        Decimal("17.50"),
    )
    assert baseline.iqr == Decimal("5.00")
    assert (baseline.sample_size, baseline.observed_sample_size) == (6, 6)
    assert (baseline.reconstructed_sample_size, baseline.rejected_uncertain_count) == (0, 0)
    assert baseline.confidence_score == Decimal("75.83")  # 20 + 35 + 0.25 * 83.33
    assert baseline.confidence_band == ConfidenceBand.MEDIUM


def test_the_baseline_records_its_target_method_and_version(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5])

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.target_snapshot_id == scenario.target_id
    assert baseline.target_origin == OBSERVED
    assert (baseline.target_snapshot_local_date, baseline.target_stay_date) == (
        TARGET_SNAPSHOT_DAY,
        TARGET_STAY,
    )
    assert baseline.lead_time_days == LEAD == 14
    assert (baseline.method, baseline.calculation_version) == (METHOD, CALCULATION_VERSION)
    assert baseline.method == "MEDIAN_SAME_DOW_SEASONAL_WINDOW"
    assert baseline.calculation_version == "booking-expected-v1"
    assert baseline.created_at is not None
    assert (baseline.workspace_id, baseline.property_id, baseline.data_source_id) == (
        scenario.tenant.workspace.id,
        scenario.tenant.property.id,
        scenario.tenant.data_source.id,
    )


def test_the_median_can_be_fractional_and_is_stored_without_rounding(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:6], rooms=[10, 11, 10, 11, 10, 11])

    scenario.calculate()

    assert scenario.baseline().expected_rooms_on_books == Decimal("10.50")


def test_zero_room_history_is_a_valid_baseline(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5], rooms=[0, 0, 1, 2, 3])

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.status == ExpectedStatus.READY
    assert baseline.expected_rooms_on_books == Decimal("1.00")
    assert sorted(c.rooms_on_books for c in comparables_of(scenario)) == [0, 0, 1, 2, 3]


def test_a_constant_history_is_a_perfectly_stable_high_confidence_baseline(
    scenario: Scenario,
) -> None:
    scenario.add_history(ELIGIBLE[:12], rooms=15)

    scenario.calculate()

    baseline = scenario.baseline()
    assert (baseline.expected_lower, baseline.expected_upper, baseline.iqr) == (
        Decimal("15.00"),
        Decimal("15.00"),
        Decimal("0.00"),
    )
    assert baseline.confidence_score == Decimal("100.00")
    assert baseline.confidence_band == ConfidenceBand.HIGH


# --- E. NO DATA FABRICATION -------------------------------------------------------------------


def test_four_valid_comparables_are_insufficient_data_and_no_number_is_stored(
    scenario: Scenario,
) -> None:
    scenario.add_history(ELIGIBLE[:4], rooms=[10, 12, 14, 16])  # a median/quartiles would exist

    result = scenario.calculate()

    baseline = scenario.baseline()
    assert (result.created, result.ready, result.insufficient) == (1, 0, 1)
    assert baseline.status == ExpectedStatus.INSUFFICIENT_DATA
    assert baseline.expected_rooms_on_books is None
    assert (baseline.expected_lower, baseline.expected_upper, baseline.iqr) == (None, None, None)
    assert baseline.confidence_score == Decimal("0.00") and baseline.confidence_band is None
    assert baseline.sample_size == 4  # what was found is still on record


def test_no_history_at_all_is_insufficient_data_with_no_comparables(scenario: Scenario) -> None:
    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.status == ExpectedStatus.INSUFFICIENT_DATA and baseline.sample_size == 0
    assert comparables_of(scenario) == []


def test_five_valid_comparables_are_the_minimum_for_ready(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5])

    scenario.calculate()

    assert scenario.baseline().status == ExpectedStatus.READY


def test_a_wrong_weekday_is_not_admitted_to_reach_the_minimum(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:4])
    fridays = [d - timedelta(days=1) for d in ELIGIBLE[:8]]
    scenario.add_history(fridays, rooms=99)

    scenario.calculate()

    assert scenario.baseline().status == ExpectedStatus.INSUFFICIENT_DATA
    assert scenario.baseline().sample_size == 4


# --- A. lead time -----------------------------------------------------------------------------


def test_snapshots_at_another_lead_time_are_never_used(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:8], lead=13, rooms=50)
    scenario.add_history(ELIGIBLE[:8], lead=15, rooms=60)
    scenario.add_history(ELIGIBLE[:5], lead=14, rooms=10)  # only these five are at lead 14

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.status == ExpectedStatus.READY and baseline.sample_size == 5
    assert baseline.expected_rooms_on_books == Decimal("10.00")  # not touched by 50 or 60


def test_there_is_no_interpolation_when_the_exact_lead_time_is_missing(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:10], lead=13)
    scenario.add_history(ELIGIBLE[:10], lead=15)

    scenario.calculate()

    assert scenario.baseline().status == ExpectedStatus.INSUFFICIENT_DATA
    assert scenario.baseline().sample_size == 0


def test_a_target_at_lead_time_zero_is_valid(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    row = snapshot_row(tenant, TARGET_STAY, TARGET_STAY, rooms=8)  # observed on the stay date
    add_snapshots(db_session, tenant, [row])
    scenario = Scenario(db_session, tenant, row["id"])
    scenario.add_history(ELIGIBLE[:6], lead=0, rooms=7)

    result = scenario.calculate()

    baseline = scenario.baseline()
    assert (result.ready, baseline.lead_time_days) == (1, 0)
    assert baseline.expected_rooms_on_books == Decimal("7.00")


def test_a_target_with_a_negative_lead_time_is_refused(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    row = snapshot_row(tenant, TARGET_STAY, TARGET_STAY - timedelta(days=3))  # night already over
    add_snapshots(db_session, tenant, [row])
    scenario = Scenario(db_session, tenant, row["id"])

    error = expected_error(scenario)

    assert error.error_code == ExpectedErrorCode.INVALID_TARGET
    assert error.details == {"reason": "negative_lead_time"}
    assert count(db_session, BookingExpectedBaseline) == 0


# --- B. temporal leakage, horizon -------------------------------------------------------------


def test_snapshots_that_did_not_exist_yet_are_ignored(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5], rooms=10)
    # the future: later Saturdays, and a snapshot taken after the target's own snapshot day
    scenario.add_history([TARGET_STAY + timedelta(days=7 * k) for k in range(1, 8)], rooms=200)
    scenario.add_history([TARGET_STAY - timedelta(days=7)], lead=3, rooms=200)  # taken 5 Aug

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.sample_size == 5 and baseline.expected_rooms_on_books == Decimal("10.00")
    assert all(c.rooms_on_books == 10 for c in comparables_of(scenario))


def test_history_beyond_730_days_is_ignored_and_728_days_is_used(scenario: Scenario) -> None:
    inside = TARGET_STAY - timedelta(days=728)
    beyond = TARGET_STAY - timedelta(days=735)
    scenario.add_history(ELIGIBLE[:4], rooms=10)
    scenario.add_history([inside], rooms=10)
    scenario.add_history([beyond], rooms=500)

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.sample_size == 5
    used = {c.snapshot_id for c in comparables_of(scenario)}
    assert scenario.history[inside] in used and scenario.history[beyond] not in used


def test_only_comparables_of_the_same_data_source_are_used(
    scenario: Scenario, factory: BookingFactory
) -> None:
    other_source = factory.data_source(scenario.tenant.property)
    scenario.add_history(ELIGIBLE[:4], rooms=10)
    foreign = [
        snapshot_row(
            scenario.tenant,
            stay - timedelta(days=LEAD),
            stay,
            rooms=99,
            data_source_id=other_source.id,
        )
        for stay in ELIGIBLE[:10]
    ]
    add_snapshots(scenario.session, scenario.tenant, foreign)

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.status == ExpectedStatus.INSUFFICIENT_DATA and baseline.sample_size == 4


# --- D. provenance ----------------------------------------------------------------------------


def test_enough_observed_comparables_are_used_alone(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5], rooms=10)
    scenario.add_history(ELIGIBLE[5:15], rooms=90, origin=RECONSTRUCTED)

    scenario.calculate()

    baseline = scenario.baseline()
    assert (baseline.observed_sample_size, baseline.reconstructed_sample_size) == (5, 0)
    assert baseline.expected_rooms_on_books == Decimal("10.00")
    assert {c.origin for c in comparables_of(scenario)} == {OBSERVED}


def test_too_few_observed_comparables_are_completed_with_clean_reconstructions(
    scenario: Scenario,
) -> None:
    scenario.add_history(ELIGIBLE[:3], rooms=10)
    scenario.add_history(ELIGIBLE[3:9], rooms=20, origin=RECONSTRUCTED)

    scenario.calculate()

    baseline = scenario.baseline()
    assert (baseline.observed_sample_size, baseline.reconstructed_sample_size) == (3, 6)
    assert baseline.status == ExpectedStatus.READY and baseline.sample_size == 9
    assert baseline.confidence_score <= Decimal("85.00")  # a reconstruction caps the confidence
    assert {c.origin for c in comparables_of(scenario)} == {OBSERVED, RECONSTRUCTED}


def test_a_reconstruction_with_uncertainty_is_counted_but_never_used(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:3], rooms=10)
    scenario.add_history(ELIGIBLE[3:6], rooms=999, origin=RECONSTRUCTED, uncertain_rooms=2)
    scenario.add_history(ELIGIBLE[6:9], rooms=20, origin=RECONSTRUCTED)

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.rejected_uncertain_count == 3
    assert (baseline.observed_sample_size, baseline.reconstructed_sample_size) == (3, 3)
    assert 999 not in [c.rooms_on_books for c in comparables_of(scenario)]


def test_a_baseline_made_only_of_reconstructions_is_capped_at_65(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:14], rooms=20, origin=RECONSTRUCTED)

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.observed_sample_size == 0 and baseline.reconstructed_sample_size == 14
    assert baseline.confidence_score == Decimal("65.00")
    assert baseline.confidence_band == ConfidenceBand.MEDIUM


def test_a_mixed_baseline_is_capped_at_85(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:4], rooms=20)
    scenario.add_history(ELIGIBLE[4:14], rooms=20, origin=RECONSTRUCTED)

    scenario.calculate()

    baseline = scenario.baseline()
    assert baseline.confidence_score == Decimal("85.00")
    assert baseline.confidence_band == ConfidenceBand.HIGH


# --- J. traceability --------------------------------------------------------------------------


def test_every_comparable_used_is_persisted_with_its_snapshot_value_origin_and_rank(
    scenario: Scenario, db_session: Session
) -> None:
    scenario.add_history(ELIGIBLE[:3], rooms=[11, 12, 13])
    scenario.add_history(ELIGIBLE[3:6], rooms=[4, 5, 6], origin=RECONSTRUCTED)

    scenario.calculate()

    rows = comparables_of(scenario)
    assert [r.recency_rank for r in rows] == [1, 2, 3, 4, 5, 6]
    assert [r.snapshot_id for r in rows] == [
        scenario.history[d] for d in ELIGIBLE[:6]
    ]  # newest first
    snapshots = {s.id: s for s in db_session.scalars(select(BookingSnapshot))}
    for row in rows:
        stored = snapshots[row.snapshot_id]
        assert (row.rooms_on_books, row.origin) == (stored.rooms_on_books, stored.origin)
    assert [r.origin for r in rows] == [OBSERVED] * 3 + [RECONSTRUCTED] * 3
    assert len(rows) == scenario.baseline().sample_size


def test_the_order_of_the_comparables_is_deterministic_recency(scenario: Scenario) -> None:
    scenario.add_history(
        list(reversed(ELIGIBLE[:7])), rooms=list(range(7))
    )  # inserted oldest first

    scenario.calculate()

    rows = comparables_of(scenario)
    stays = [
        next(d for d, sid in scenario.history.items() if sid == row.snapshot_id) for row in rows
    ]
    assert stays == ELIGIBLE[:7]
    assert [r.recency_rank for r in rows] == list(range(1, 8))


def test_rejected_candidates_are_not_saved_as_comparables(
    scenario: Scenario, db_session: Session
) -> None:
    scenario.add_history(ELIGIBLE[:5], rooms=10)
    rejected_ids = set()
    rejected_ids |= set(scenario.add_history(ELIGIBLE[:5], lead=13, rooms=70))  # wrong lead
    rejected_ids |= set(
        scenario.add_history([d - timedelta(days=1) for d in ELIGIBLE[:5]], rooms=70)  # weekday
    )
    rejected_ids |= set(
        scenario.add_history(ELIGIBLE[5:7], rooms=70, origin=RECONSTRUCTED, uncertain_rooms=1)
    )
    rejected_ids |= set(
        scenario.add_history(ELIGIBLE[7:9], rooms=70, origin=RECONSTRUCTED)
    )  # unneeded

    scenario.calculate()

    saved = {c.snapshot_id for c in comparables_of(scenario)}
    assert len(saved) == 5 and not saved & rejected_ids
    assert count(db_session, BookingExpectedComparable) == 5


def test_a_baseline_can_be_fully_explained_from_its_stored_rows(scenario: Scenario) -> None:
    """Target, lead time, method, expected, range, IQR, samples, confidence and the comparables."""
    scenario.add_history(ELIGIBLE[:6], rooms=[10, 12, 14, 16, 18, 20])
    scenario.calculate()

    baseline = scenario.baseline()
    rows = comparables_of(scenario)
    explanation = {
        "target": (baseline.target_snapshot_id, baseline.target_stay_date),
        "lead_time_days": baseline.lead_time_days,
        "method": baseline.method,
        "expected": baseline.expected_rooms_on_books,
        "range": (baseline.expected_lower, baseline.expected_upper),
        "iqr": baseline.iqr,
        "samples": (
            baseline.sample_size,
            baseline.observed_sample_size,
            baseline.reconstructed_sample_size,
        ),
        "confidence": (baseline.confidence_score, baseline.confidence_band),
        "comparables": [(r.recency_rank, r.snapshot_id, r.rooms_on_books, r.origin) for r in rows],
    }
    assert explanation["samples"] == (6, 6, 0) and len(explanation["comparables"]) == 6  # type: ignore[arg-type]
    # ...and the stored numbers are reproducible from the stored comparables alone
    assert sorted(r.rooms_on_books for r in rows) == [10, 12, 14, 16, 18, 20]
    assert baseline.expected_rooms_on_books == Decimal("15.00")


# --- I. idempotency, immutability, conflict ---------------------------------------------------


def test_the_same_calculation_twice_is_an_idempotent_no_op(
    scenario: Scenario, db_session: Session
) -> None:
    scenario.add_history(ELIGIBLE[:6], rooms=[10, 12, 14, 16, 18, 20])
    first = scenario.calculate()
    stored = scenario.baseline()
    before = (stored.id, stored.comparable_fingerprint, stored.created_at)

    second = scenario.calculate()

    assert (first.created, first.unchanged) == (1, 0)
    assert (second.created, second.unchanged) == (0, 1)
    assert second.baseline_ids == first.baseline_ids
    again = scenario.baseline()
    assert (again.id, again.comparable_fingerprint, again.created_at) == before
    assert count(db_session, BookingExpectedBaseline) == 1
    assert count(db_session, BookingExpectedComparable) == 6


def test_a_different_comparable_set_for_the_same_target_is_a_conflict_and_nothing_is_overwritten(
    scenario: Scenario, db_session: Session
) -> None:
    scenario.add_history(ELIGIBLE[:5], rooms=10)
    scenario.calculate()
    before = scenario.baseline()
    snapshot = (before.id, before.comparable_fingerprint, before.sample_size)

    scenario.add_history(ELIGIBLE[5:7], rooms=40)  # history that arrived AFTER the baseline

    error = expected_error(scenario)

    assert error.error_code == ExpectedErrorCode.BASELINE_CONFLICT
    assert error.code == "EXPECTED_BASELINE_CONFLICT" and error.status_code == 409
    assert error.details == {
        "conflict_count": 1,
        "conflicts": [
            {"target_snapshot_id": str(scenario.target_id), "reason": "different_comparables"}
        ],
        "calculation_version": CALCULATION_VERSION,
    }
    after = scenario.baseline()
    assert (after.id, after.comparable_fingerprint, after.sample_size) == snapshot
    assert count(db_session, BookingExpectedBaseline) == 1
    assert count(db_session, BookingExpectedComparable) == 5


def test_an_insufficient_baseline_is_not_silently_upgraded_when_history_arrives(
    scenario: Scenario,
) -> None:
    scenario.add_history(ELIGIBLE[:4])
    scenario.calculate()
    scenario.add_history(ELIGIBLE[4:6])  # now 6 would be READY

    error = expected_error(scenario)

    assert error.error_code == ExpectedErrorCode.BASELINE_CONFLICT
    assert scenario.baseline().status == ExpectedStatus.INSUFFICIENT_DATA  # the record stands


def test_the_stored_fingerprint_is_reproducible_from_the_stored_comparables(
    scenario: Scenario, db_session: Session
) -> None:
    scenario.add_history(ELIGIBLE[:4], rooms=[10, 12, 14, 16])
    scenario.add_history(ELIGIBLE[4:7], rooms=[5, 6, 7], origin=RECONSTRUCTED)
    scenario.calculate()
    baseline = scenario.baseline()
    snapshots = {s.id: s for s in db_session.scalars(select(BookingSnapshot))}
    candidates = [
        Candidate(
            snapshot_id=row.snapshot_id,
            snapshot_local_date=snapshots[row.snapshot_id].snapshot_local_date,
            stay_date=snapshots[row.snapshot_id].stay_date,
            origin=row.origin,
            rooms_on_books=row.rooms_on_books,
            uncertain_rooms=0,
        )
        for row in comparables_of(scenario)
    ]

    recomputed = comparable_fingerprint(
        data_source_id=scenario.tenant.data_source.id,
        target_snapshot_id=scenario.target_id,
        target=HistoricalTarget(TARGET_STAY, LEAD),
        computation=compute_expected(HistoricalTarget(TARGET_STAY, LEAD), candidates),
    )

    assert recomputed == baseline.comparable_fingerprint


def test_the_session_is_usable_after_a_conflict(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5])
    scenario.calculate()
    scenario.add_history(ELIGIBLE[5:6])
    expected_error(scenario)

    other = snapshot_row(scenario.tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY + timedelta(days=7))
    add_snapshots(scenario.session, scenario.tenant, [other])

    result = scenario.calculate(other["id"])  # a different target is fine

    assert result.created == 1


# --- K. target rules --------------------------------------------------------------------------


def test_an_observed_target_is_accepted(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5])

    assert scenario.calculate().created == 1


def test_a_reconstructed_target_is_refused(scenario: Scenario, db_session: Session) -> None:
    stay = TARGET_STAY + timedelta(days=1)
    row = snapshot_row(scenario.tenant, TARGET_SNAPSHOT_DAY, stay, origin=RECONSTRUCTED)
    add_snapshots(db_session, scenario.tenant, [row])

    error = expected_error(scenario, target_snapshot_id=row["id"])

    assert error.error_code == ExpectedErrorCode.TARGET_NOT_OBSERVED
    assert error.code == "EXPECTED_TARGET_NOT_OBSERVED"
    assert error.details == {"origin": "RECONSTRUCTED_APPROXIMATE"}
    assert count(db_session, BookingExpectedBaseline) == 0


def test_a_target_of_another_data_source_is_refused(
    scenario: Scenario, factory: BookingFactory, db_session: Session
) -> None:
    other_source = factory.data_source(scenario.tenant.property)
    row = snapshot_row(
        scenario.tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY, data_source_id=other_source.id
    )
    add_snapshots(db_session, scenario.tenant, [row])

    error = expected_error(scenario, target_snapshot_id=row["id"])  # asked for the first source

    assert error.error_code == ExpectedErrorCode.INVALID_TARGET
    assert error.details == {"reason": "data_source_mismatch"}


def test_a_target_of_another_workspace_is_not_found(
    scenario: Scenario, db_session: Session, factory: BookingFactory
) -> None:
    foreign = Scenario.create(db_session, factory)  # another tenant with its own target snapshot

    error = expected_error(scenario, target_snapshot_id=foreign.target_id)
    unknown = expected_error(scenario, target_snapshot_id=uuid.uuid4())

    assert error.error_code == unknown.error_code == ExpectedErrorCode.TARGET_NOT_FOUND
    assert error.message == unknown.message  # indistinguishable from a missing one


def test_a_data_source_of_another_domain_or_inactive_is_refused(
    scenario: Scenario, factory: BookingFactory
) -> None:
    costs = factory.data_source(scenario.tenant.property, DataSourceDomain.COSTS)
    scenario.tenant.data_source.is_active = False

    wrong_domain = expected_error(scenario, data_source_id=costs.id)
    inactive = expected_error(scenario)

    assert wrong_domain.error_code == ExpectedErrorCode.INVALID_DATA_SOURCE
    assert wrong_domain.details == {"reason": "wrong_domain"}
    assert inactive.details == {"reason": "inactive"}


def test_a_property_of_another_workspace_or_archived_is_refused(
    scenario: Scenario, db_session: Session, factory: BookingFactory
) -> None:
    foreign = factory.tenant()
    unknown_property = expected_error(scenario, property_id=foreign.property.id)
    scenario.tenant.property.is_active = False
    scenario.tenant.property.archived_at = datetime(2026, 1, 1, tzinfo=UTC)
    archived = expected_error(scenario)

    assert unknown_property.error_code == ExpectedErrorCode.INVALID_PROPERTY
    assert unknown_property.details == {"reason": "not_found"}
    assert archived.details == {"reason": "archived"}


def test_a_data_source_of_another_property_is_refused(
    scenario: Scenario, factory: BookingFactory
) -> None:
    other_property = factory.property(scenario.tenant.workspace)
    other_source = factory.data_source(other_property)

    error = expected_error(scenario, data_source_id=other_source.id)

    assert error.details == {"reason": "property_mismatch"}


def test_the_service_needs_a_tenant_context(db_session: Session) -> None:
    with pytest.raises(TypeError):
        BookingExpectedService(db_session, uuid.uuid4())  # type: ignore[arg-type]
    assert "clock" not in inspect.signature(BookingExpectedService.__init__).parameters


# --- the optional batch -----------------------------------------------------------------------


def observed_targets(scenario: Scenario, stays: list[date]) -> list[uuid.UUID]:
    rows = [snapshot_row(scenario.tenant, TARGET_SNAPSHOT_DAY, stay, rooms=12) for stay in stays]
    add_snapshots(scenario.session, scenario.tenant, rows)
    return [row["id"] for row in rows]


def test_a_batch_calculates_every_observed_target_of_a_snapshot_day(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    scenario = Scenario(db_session, tenant, uuid.uuid4())
    # three Saturdays as targets, each seen on 1 August: leads 14, 21 and 28
    stays = [TARGET_STAY, TARGET_STAY + timedelta(days=7), TARGET_STAY + timedelta(days=14)]
    observed_targets(scenario, stays)
    for stay in stays:
        lead = (stay - TARGET_SNAPSHOT_DAY).days
        scenario.add_history(eligible_stay_dates(stay)[:6], lead=lead)
    scenario.commit()

    result = scenario.service().calculate_for_snapshot_date(
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        snapshot_local_date=TARGET_SNAPSHOT_DAY,
        stay_date_start=stays[0],
        stay_date_end=stays[-1],
    )

    baselines = ExpectedRepository(db_session, tenant.context).list_for_snapshot_date(
        tenant.data_source.id, TARGET_SNAPSHOT_DAY
    )
    assert result.total == len(baselines) == 3
    assert [b.target_stay_date for b in baselines] == stays
    assert [b.lead_time_days for b in baselines] == [14, 21, 28]


def test_a_batch_skips_targets_whose_night_was_already_over_and_counts_them(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    scenario = Scenario(db_session, tenant, uuid.uuid4())
    past = TARGET_SNAPSHOT_DAY - timedelta(days=3)
    observed_targets(scenario, [past, TARGET_STAY])
    scenario.add_history(ELIGIBLE[:5])
    scenario.commit()

    result = scenario.service().calculate_for_snapshot_date(
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        snapshot_local_date=TARGET_SNAPSHOT_DAY,
        stay_date_start=past,
        stay_date_end=TARGET_STAY,
    )

    assert (result.created, result.skipped_negative_lead_time) == (1, 1)


def test_a_batch_only_considers_observed_targets(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    scenario = Scenario(db_session, tenant, uuid.uuid4())
    observed_targets(scenario, [TARGET_STAY])
    reconstructed = snapshot_row(
        tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY + timedelta(days=1), origin=RECONSTRUCTED
    )
    add_snapshots(db_session, tenant, [reconstructed])
    scenario.commit()

    result = scenario.service().calculate_for_snapshot_date(
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        snapshot_local_date=TARGET_SNAPSHOT_DAY,
        stay_date_start=TARGET_STAY,
        stay_date_end=TARGET_STAY + timedelta(days=1),
    )

    assert result.total == 1


def test_rerunning_a_batch_is_a_no_op_and_a_conflict_stores_nothing_of_the_batch(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    scenario = Scenario(db_session, tenant, uuid.uuid4())
    stays = [TARGET_STAY, TARGET_STAY + timedelta(days=7)]
    observed_targets(scenario, stays)
    scenario.add_history(ELIGIBLE[:6], lead=14)
    scenario.add_history(ELIGIBLE[:6], lead=21)
    scenario.commit()
    service = scenario.service()
    arguments: dict[str, Any] = {
        "property_id": tenant.property.id,
        "data_source_id": tenant.data_source.id,
        "snapshot_local_date": TARGET_SNAPSHOT_DAY,
        "stay_date_start": stays[0],
        "stay_date_end": stays[-1],
    }
    first = service.calculate_for_snapshot_date(**arguments)
    second = service.calculate_for_snapshot_date(**arguments)
    assert (first.created, second.created, second.unchanged) == (2, 0, 2)

    # new history for the FIRST target only, plus a brand-new third target in the same range
    scenario.add_history([ELIGIBLE[6]], lead=14, rooms=90)
    observed_targets(scenario, [TARGET_STAY + timedelta(days=14)])
    scenario.commit()
    with pytest.raises(ExpectedError) as info:
        service.calculate_for_snapshot_date(
            **{**arguments, "stay_date_end": stays[-1] + timedelta(days=7)}
        )

    assert info.value.error_code == ExpectedErrorCode.BASELINE_CONFLICT
    assert count(db_session, BookingExpectedBaseline) == 2  # the third target was rolled back too


def test_the_batch_range_is_validated(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    service = BookingExpectedService(db_session, tenant.context)
    arguments: dict[str, Any] = {
        "property_id": tenant.property.id,
        "data_source_id": tenant.data_source.id,
        "snapshot_local_date": TARGET_SNAPSHOT_DAY,
    }

    with pytest.raises(ExpectedError) as info:
        service.calculate_for_snapshot_date(
            stay_date_start=TARGET_STAY + timedelta(days=1), stay_date_end=TARGET_STAY, **arguments
        )
    assert info.value.details == {"reason": "start_after_end"}
    with pytest.raises(ExpectedError) as too_long:
        service.calculate_for_snapshot_date(
            stay_date_start=TARGET_STAY,
            stay_date_end=TARGET_STAY + timedelta(days=731),
            **arguments,
        )
    assert too_long.value.details == {"reason": "too_long", "max_days": 731}
    with pytest.raises(TypeError):
        service.calculate_for_snapshot_date(
            stay_date_start=datetime(2026, 8, 15, 12, 0),
            stay_date_end=TARGET_STAY,
            **arguments,
        )


def test_the_tenant_of_the_service_is_the_only_one_it_can_write_for(
    scenario: Scenario, db_session: Session, factory: BookingFactory
) -> None:
    scenario.add_history(ELIGIBLE[:5])
    foreign = factory.tenant()
    scenario.commit()

    with pytest.raises(ExpectedError) as info:
        BookingExpectedService(
            db_session, TenantContext(foreign.workspace.id)
        ).calculate_for_target(
            property_id=scenario.tenant.property.id,
            data_source_id=scenario.tenant.data_source.id,
            target_snapshot_id=scenario.target_id,
        )

    assert info.value.error_code == ExpectedErrorCode.INVALID_PROPERTY
    assert count(db_session, BookingExpectedBaseline) == 0
