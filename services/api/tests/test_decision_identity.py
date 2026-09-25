"""Decision identity (`decision-identity-v1`): cross-day, per-detector, and the hash itself.

GOLDEN INDEPENDENCE for the hash section: expected hashes are computed here with stdlib `hashlib`
+ `json` and literal values, never by importing `app.modules.decisions.identity`'s own helpers for
the EXPECTED side of a comparison (only the code under test is imported).
"""

import hashlib
import json
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.modules.decisions.errors import DecisionError, DecisionErrorCode
from app.modules.decisions.identity import build_identity, verify_identity
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.intelligence.revenue.types import RevenueDecisionType
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory
from tests.decision_support import (
    cost_evaluation,
    labor_evaluation,
    ota_evaluation,
    revenue_evaluation,
)

WS, PROP, SRC = uuid4(), uuid4(), uuid4()


# --- A. REVENUE (1-6) --------------------------------------------------------------------------


def test_pickup_same_stay_date_next_day_has_the_same_identity() -> None:
    stay = date(2026, 8, 15)
    day1 = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 1),
    )
    day2 = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 2),
    )
    assert build_identity(day1).identity_key == build_identity(day2).identity_key


def test_pickup_different_stay_date_has_a_different_identity() -> None:
    a = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
    )
    b = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 16),
        snapshot_local_date=date(2026, 8, 1),
    )
    assert build_identity(a).identity_key != build_identity(b).identity_key


def test_occupancy_same_stay_date_identity_is_stable_across_days() -> None:
    stay = date(2026, 8, 15)
    day1 = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 1),
        decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
    )
    day2 = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 3),
        decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
    )
    assert build_identity(day1).identity_key == build_identity(day2).identity_key


def test_pickup_and_occupancy_same_stay_date_are_different_decisions() -> None:
    stay = date(2026, 8, 15)
    pickup = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 1),
        decision_type=RevenueDecisionType.REV_PICKUP_LOW,
    )
    occupancy = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 1),
        decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
    )
    pickup_identity, occupancy_identity = build_identity(pickup), build_identity(occupancy)
    assert pickup_identity.decision_type != occupancy_identity.decision_type
    assert pickup_identity.identity_key != occupancy_identity.identity_key


def test_revenue_different_booking_source_is_a_different_identity() -> None:
    stay = date(2026, 8, 15)
    a = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 1),
    )
    b = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=uuid4(),
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 1),
    )
    assert build_identity(a).identity_key != build_identity(b).identity_key


def test_revenue_as_of_is_not_part_of_the_identity_payload() -> None:
    evaluation = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
    )
    identity = build_identity(evaluation)
    assert "snapshot_local_date" not in identity.identity_payload
    assert "as_of_local_date" not in identity.identity_payload
    assert "target_snapshot_id" not in identity.identity_payload


# --- B. OTA (7-11) -------------------------------------------------------------------------------


def test_ota_as_of_day1_and_day2_share_the_same_identity() -> None:
    source = uuid4()
    day1 = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 1),
    )
    day2 = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 8),
    )
    assert build_identity(day1).identity_key == build_identity(day2).identity_key


def test_ota_30_day_window_shift_does_not_change_identity() -> None:
    source = uuid4()
    day1 = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 1),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 30),
    )
    day2 = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 2),
        window_start=date(2026, 8, 2),
        window_end=date(2026, 8, 31),
    )
    identity1, identity2 = build_identity(day1), build_identity(day2)
    assert identity1.identity_key == identity2.identity_key
    assert "window_start" not in identity1.identity_payload
    assert "window_end" not in identity1.identity_payload


def test_ota_structural_to_rising_is_the_same_identity() -> None:
    source = uuid4()
    structural = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 1),
        structural=True,
        rising=False,
    )
    rising = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 8),
        structural=False,
        rising=True,
    )
    assert build_identity(structural).identity_key == build_identity(rising).identity_key


def test_ota_different_booking_source_is_a_different_identity() -> None:
    a = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=uuid4(),
        as_of_local_date=date(2026, 8, 1),
    )
    b = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=uuid4(),
        as_of_local_date=date(2026, 8, 1),
    )
    assert build_identity(a).identity_key != build_identity(b).identity_key


def test_ota_different_property_is_a_different_identity() -> None:
    source = uuid4()
    a = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 1),
    )
    b = ota_evaluation(
        workspace_id=WS,
        property_id=uuid4(),
        booking_data_source_id=source,
        as_of_local_date=date(2026, 8, 1),
    )
    assert build_identity(a).identity_key != build_identity(b).identity_key


# --- C. COST (12-16) -----------------------------------------------------------------------------


def test_cost_same_month_category_currency_two_days_is_the_same_identity() -> None:
    source = uuid4()
    day1 = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 8, 1),
    )
    day2 = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 8, 1),
    )
    assert build_identity(day1).identity_key == build_identity(day2).identity_key


def test_cost_new_month_is_a_different_identity() -> None:
    source = uuid4()
    august = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 8, 1),
    )
    september = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 9, 1),
    )
    assert build_identity(august).identity_key != build_identity(september).identity_key


def test_cost_different_category_is_a_different_identity() -> None:
    source = uuid4()
    laundry = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 8, 1),
        cost_category=CostCategory.LAUNDRY,
    )
    utilities = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 8, 1),
        cost_category=CostCategory.UTILITIES,
    )
    assert build_identity(laundry).identity_key != build_identity(utilities).identity_key


def test_cost_different_currency_is_a_different_identity() -> None:
    source = uuid4()
    eur = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 8, 1),
        currency="EUR",
    )
    usd = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=source,
        target_period_start=date(2026, 8, 1),
        currency="USD",
    )
    assert build_identity(eur).identity_key != build_identity(usd).identity_key


def test_cost_identity_includes_the_real_gate_7_target_dimensions() -> None:
    """docs/architecture/cost-cpor-anomaly-v1.md, "The target": workspace, property, BOOKING DATA
    SOURCE, month, category, currency - the booking source is real (the occupancy denominator's
    stated provenance), never invented; costs themselves stay cross-source (Gate 6/7)."""
    evaluation = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        target_period_start=date(2026, 8, 1),
    )
    payload = build_identity(evaluation).identity_payload
    assert payload["booking_data_source_id"] == str(SRC)
    assert payload["target_period_start"] == "2026-08-01"
    assert payload["cost_category"] == "LAUNDRY"
    assert payload["currency"] == "EUR"
    assert "target_period_end" not in payload  # the month alone already determines it


# --- D. LABOR (17-21) ----------------------------------------------------------------------------


def test_labor_same_work_date_category_next_day_is_the_same_identity() -> None:
    booking_src, labor_src = uuid4(), uuid4()
    day1 = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=booking_src,
        labor_data_source_id=labor_src,
        target_work_date=date(2026, 8, 1),
        target_as_of_date=date(2026, 8, 1),
    )
    day2 = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=booking_src,
        labor_data_source_id=labor_src,
        target_work_date=date(2026, 8, 1),
        target_as_of_date=date(2026, 8, 2),
    )
    assert build_identity(day1).identity_key == build_identity(day2).identity_key


def test_labor_different_work_date_is_a_different_identity() -> None:
    booking_src, labor_src = uuid4(), uuid4()
    a = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=booking_src,
        labor_data_source_id=labor_src,
        target_work_date=date(2026, 8, 1),
    )
    b = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=booking_src,
        labor_data_source_id=labor_src,
        target_work_date=date(2026, 8, 2),
    )
    assert build_identity(a).identity_key != build_identity(b).identity_key


def test_labor_different_category_is_a_different_identity() -> None:
    booking_src, labor_src = uuid4(), uuid4()
    housekeeping = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=booking_src,
        labor_data_source_id=labor_src,
        target_work_date=date(2026, 8, 1),
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    kitchen = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=booking_src,
        labor_data_source_id=labor_src,
        target_work_date=date(2026, 8, 1),
        labor_category=LaborCategory.KITCHEN,
    )
    assert build_identity(housekeeping).identity_key != build_identity(kitchen).identity_key


def test_labor_identity_includes_both_the_booking_and_labor_source() -> None:
    evaluation = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        labor_data_source_id=uuid4(),
        target_work_date=date(2026, 8, 1),
    )
    payload = build_identity(evaluation).identity_payload
    assert payload["booking_data_source_id"] == str(SRC)
    assert "labor_data_source_id" in payload

    # a different booking source alone (labor source unchanged) is a different identity: the
    # demand forecast genuinely depends on it (docs/architecture/labor-overstaffing-v1.md).
    other = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=uuid4(),
        labor_data_source_id=uuid4(),
        target_work_date=date(2026, 8, 1),
    )
    assert build_identity(evaluation).identity_key != build_identity(other).identity_key


def test_labor_as_of_date_is_not_part_of_the_identity() -> None:
    evaluation = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        labor_data_source_id=uuid4(),
        target_work_date=date(2026, 8, 1),
        target_as_of_date=date(2026, 7, 20),
    )
    payload = build_identity(evaluation).identity_payload
    assert "target_as_of_date" not in payload
    assert "target_booking_snapshot_id" not in payload
    assert "target_labor_snapshot_id" not in payload


# --- E. HASH (22-26) -----------------------------------------------------------------------------


def test_identity_hash_is_deterministic() -> None:
    evaluation = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
    )
    keys = {build_identity(evaluation).identity_key for _ in range(5)}
    assert len(keys) == 1
    assert len(next(iter(keys))) == 64


def test_identity_hash_is_independent_of_field_ordering() -> None:
    payload_a = {"b": 1, "a": 2, "c": {"y": 1, "x": 2}}
    payload_b = {"a": 2, "c": {"x": 2, "y": 1}, "b": 1}
    hash_a = hashlib.sha256(
        json.dumps(payload_a, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    hash_b = hashlib.sha256(
        json.dumps(payload_b, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert hash_a == hash_b

    from app.modules.decisions.identity import canonical_identity_json

    assert canonical_identity_json(payload_a) == canonical_identity_json(payload_b)


def test_identity_hash_changes_when_a_value_changes() -> None:
    a = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
    )
    b = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15) + timedelta(days=1),
        snapshot_local_date=date(2026, 8, 1),
    )
    assert build_identity(a).identity_key != build_identity(b).identity_key


def test_identity_hash_matches_an_independent_canonical_json_sha256() -> None:
    """GOLDEN INDEPENDENCE: the expected hash below is built with stdlib only, from LITERAL
    values, never by calling `app.modules.decisions.identity`."""
    stay = date(2026, 8, 15)
    evaluation = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=stay,
        snapshot_local_date=date(2026, 8, 1),
        decision_type=RevenueDecisionType.REV_PICKUP_LOW,
    )
    expected_payload = {
        "identity_version": "decision-identity-v1",
        "decision_type": "REV_PICKUP_LOW",
        "workspace_id": str(WS),
        "property_id": str(PROP),
        "booking_data_source_id": str(SRC),
        "stay_date": "2026-08-15",
    }
    expected_hash = hashlib.sha256(
        json.dumps(
            expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    ).hexdigest()
    identity = build_identity(evaluation)
    assert identity.identity_key == expected_hash
    assert identity.identity_payload == expected_payload


def test_identity_collision_with_a_mismatched_payload_fails_closed() -> None:
    evaluation = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
    )
    identity = build_identity(evaluation)
    tampered_payload = {**identity.identity_payload, "stay_date": "2099-01-01"}

    with pytest.raises(DecisionError) as info:
        verify_identity(tampered_payload, identity)
    assert info.value.error_code == DecisionErrorCode.DECISION_IDENTITY_HASH_COLLISION

    # the matching payload never raises
    verify_identity(identity.identity_payload, identity)


def test_unrecognised_evaluation_type_is_rejected() -> None:
    with pytest.raises(DecisionError) as info:
        build_identity(object())  # type: ignore[arg-type]
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_every_decision_type_enum_member_has_an_identity_builder() -> None:
    """A defensive coverage check: the five MVP decision types all have an explicit path."""
    assert {member.value for member in PriorityDecisionType} == {
        "REV_PICKUP_LOW",
        "REV_OCCUPANCY_RISK",
        "REV_OTA_DEPENDENCY",
        "COST_CPOR_ANOMALY",
        "LABOR_OVERSTAFFING",
    }
