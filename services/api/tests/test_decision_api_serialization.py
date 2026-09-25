"""Decision API V1: serializer unit tests (Gate 12 review items 79-93).

Unit-level, exactly like Gate 11's own `test_decision_serialization.py`: no HTTP, no database -
`target_of`/`facts_of`/`evidence_of` are pure functions over transient (never persisted) ORM
objects and plain dicts.
"""

import json
from datetime import date
from uuid import uuid4

from app.api.v1.decisions.serializers import evidence_of, facts_of, target_of
from app.modules.decisions.models import Decision
from app.modules.decisions.types import DecisionStatus
from app.modules.intelligence.priority.types import PriorityDecisionType

WS, PROP, SRC, LABOR_SRC = uuid4(), uuid4(), uuid4(), uuid4()


def _decision(decision_type: PriorityDecisionType, identity_payload: dict[str, object]) -> Decision:
    """A transient (never added to a session) `Decision`: `target_of` only ever reads
    `decision_type`/`identity_payload`, so nothing else needs to be realistic here."""
    return Decision(
        workspace_id=WS,
        property_id=PROP,
        decision_type=decision_type,
        identity_version="decision-identity-v1",
        identity_key="a" * 64,
        identity_payload=identity_payload,
        status=DecisionStatus.OPEN,
        first_seen_local_date=date(2026, 8, 1),
        last_seen_local_date=date(2026, 8, 1),
        last_evaluated_local_date=date(2026, 8, 1),
        episode_count=1,
        triggered_observation_count=1,
    )


# --- 79-82: target serializers -------------------------------------------------------------


def test_revenue_target_serializer() -> None:
    decision = _decision(
        PriorityDecisionType.REV_PICKUP_LOW,
        {"booking_data_source_id": str(SRC), "stay_date": "2026-08-15"},
    )
    target = target_of(decision)
    assert target.type == "REV_PICKUP_LOW"
    assert target.booking_data_source_id == SRC
    assert target.stay_date == date(2026, 8, 15)


def test_ota_target_serializer() -> None:
    decision = _decision(
        PriorityDecisionType.REV_OTA_DEPENDENCY, {"booking_data_source_id": str(SRC)}
    )
    target = target_of(decision)
    assert target.type == "REV_OTA_DEPENDENCY"
    assert target.booking_data_source_id == SRC


def test_cost_target_serializer() -> None:
    decision = _decision(
        PriorityDecisionType.COST_CPOR_ANOMALY,
        {
            "booking_data_source_id": str(SRC),
            "target_period_start": "2026-08-01",
            "cost_category": "LAUNDRY",
            "currency": "EUR",
        },
    )
    target = target_of(decision)
    assert target.type == "COST_CPOR_ANOMALY"
    assert target.target_period_start == date(2026, 8, 1)
    assert target.cost_category == "LAUNDRY"
    assert target.currency == "EUR"


def test_labor_target_serializer() -> None:
    decision = _decision(
        PriorityDecisionType.LABOR_OVERSTAFFING,
        {
            "booking_data_source_id": str(SRC),
            "labor_data_source_id": str(LABOR_SRC),
            "work_date": "2026-08-01",
            "labor_category": "HOUSEKEEPING",
        },
    )
    target = target_of(decision)
    assert target.type == "LABOR_OVERSTAFFING"
    assert target.labor_data_source_id == LABOR_SRC
    assert target.work_date == date(2026, 8, 1)
    assert target.labor_category == "HOUSEKEEPING"


# --- 83-90: facts/evidence whitelists (never a blind passthrough) --------------------------


def test_revenue_facts_whitelist_drops_unexpected_keys() -> None:
    raw = {"stay_date": "2026-08-15", "current_rooms_on_books": 20, "guest_name": "Mario Rossi"}
    filtered = facts_of(PriorityDecisionType.REV_PICKUP_LOW, raw)
    assert "guest_name" not in filtered
    assert filtered["stay_date"] == "2026-08-15"


def test_ota_facts_whitelist_drops_unexpected_keys() -> None:
    raw = {"window_start": "2026-08-01", "ota_room_nights": 24, "internal_sql_hint": "SELECT *"}
    filtered = facts_of(PriorityDecisionType.REV_OTA_DEPENDENCY, raw)
    assert "internal_sql_hint" not in filtered
    assert filtered["window_start"] == "2026-08-01"


def test_cost_facts_whitelist_drops_unexpected_keys() -> None:
    raw = {"target_period_start": "2026-08-01", "currency": "EUR", "invoice_raw_payload": {"x": 1}}
    filtered = facts_of(PriorityDecisionType.COST_CPOR_ANOMALY, raw)
    assert "invoice_raw_payload" not in filtered
    assert filtered["currency"] == "EUR"


def test_labor_facts_whitelist_drops_unexpected_keys() -> None:
    raw = {"work_date": "2026-08-01", "labor_category": "HOUSEKEEPING", "employee_id": str(uuid4())}
    filtered = facts_of(PriorityDecisionType.LABOR_OVERSTAFFING, raw)
    assert "employee_id" not in filtered
    assert filtered["labor_category"] == "HOUSEKEEPING"


def test_revenue_evidence_whitelist_drops_unexpected_keys() -> None:
    raw = {"booking_data_source_id": str(SRC), "rules_version": "revenue-decisions-v1", "sql": "x"}
    filtered = evidence_of(PriorityDecisionType.REV_OCCUPANCY_RISK, raw)
    assert "sql" not in filtered
    assert filtered["rules_version"] == "revenue-decisions-v1"


def test_ota_evidence_whitelist_drops_unexpected_keys() -> None:
    raw = {"booking_data_source_id": str(SRC), "sample_count": 6, "stack_trace": "..."}
    filtered = evidence_of(PriorityDecisionType.REV_OTA_DEPENDENCY, raw)
    assert "stack_trace" not in filtered
    assert filtered["sample_count"] == 6


def test_cost_evidence_whitelist_drops_unexpected_keys() -> None:
    raw = {
        "booking_data_source_id": str(SRC),
        "confidence_score": "90",
        "supplier_name": "Acme SRL",
    }
    filtered = evidence_of(PriorityDecisionType.COST_CPOR_ANOMALY, raw)
    assert "supplier_name" not in filtered
    assert filtered["confidence_score"] == "90"


def test_labor_evidence_whitelist_drops_unexpected_keys() -> None:
    raw = {
        "booking_data_source_id": str(SRC),
        "labor_data_source_id": str(LABOR_SRC),
        "cost_currency": "EUR",
        "iban": "IT00X0000000000000000000000",
    }
    filtered = evidence_of(PriorityDecisionType.LABOR_OVERSTAFFING, raw)
    assert "iban" not in filtered
    assert filtered["cost_currency"] == "EUR"


# --- 91-93: no float conversion, no Python repr, stable JSON -------------------------------


def test_facts_and_evidence_never_contain_a_float_or_a_python_repr() -> None:
    raw_facts = {
        "target_period_start": "2026-08-01",
        "actual_cpor_exact": "6.00",  # already a canonical string, Gate 11's own contract
        "currency": "EUR",
    }
    raw_evidence = {"booking_data_source_id": str(SRC), "confidence_score": "90.00"}
    facts = facts_of(PriorityDecisionType.COST_CPOR_ANOMALY, raw_facts)
    evidence = evidence_of(PriorityDecisionType.COST_CPOR_ANOMALY, raw_evidence)
    for payload in (facts, evidence):
        for value in payload.values():
            assert not isinstance(value, float)
            assert "Decimal(" not in repr(value)


def test_facts_and_evidence_serialize_to_stable_json() -> None:
    raw_facts = {"target_period_start": "2026-08-01", "currency": "EUR", "cost_category": "LAUNDRY"}
    facts = facts_of(PriorityDecisionType.COST_CPOR_ANOMALY, raw_facts)
    first = json.dumps(facts, sort_keys=True)
    second = json.dumps(facts_of(PriorityDecisionType.COST_CPOR_ANOMALY, raw_facts), sort_keys=True)
    assert first == second
