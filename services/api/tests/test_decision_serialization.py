"""Decision Memory serialization: explicit per-detector serializers and data minimization
(tests 106-123).

The PII tests are a STATIC source scan of `app/modules/decisions/serialization.py` (never a
detector's own `payload()`): the serializer never reads a field by iterating whatever the
evaluation happens to expose, so a scan of ITS OWN source is a direct, permanent guarantee - not
merely "this run's fixture data happened not to contain PII".
"""

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.modules.decisions.serialization import (
    SourceEvaluation,
    reason_codes_of,
    serialize_cost,
    serialize_facts,
    serialize_labor,
    serialize_ota,
    serialize_revenue,
)
from app.modules.intelligence.revenue.types import RevenueDecisionType
from tests.decision_support import (
    cost_evaluation,
    labor_evaluation,
    ota_evaluation,
    revenue_evaluation,
)

SERIALIZATION_FILE = (
    Path(__file__).resolve().parents[1] / "app" / "modules" / "decisions" / "serialization.py"
)

WS, PROP, SRC = uuid4(), uuid4(), uuid4()

FORBIDDEN_TOKENS = {
    "guest",
    "guestname",
    "guestemail",
    "guestphone",
    "email",
    "phone",
    "employee",
    "taxcode",
    "codicefiscale",
    "address",
    "iban",
    "medical",
    "suppliername",
    "legalname",
    "normalizedname",
}


def _identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def _tokens(identifiers: set[str]) -> set[str]:
    return {identifier.lower().replace("_", "") for identifier in identifiers}


# --- 106-109: explicit per-detector serializers exist and dispatch correctly -------------------


def test_revenue_has_its_own_explicit_serializer() -> None:
    evaluation = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
    )
    facts, evidence = serialize_revenue(evaluation)
    assert facts["stay_date"] == "2026-08-15"
    assert "booking_data_source_id" in evidence
    assert serialize_facts(evaluation) == (facts, evidence)


def test_ota_has_its_own_explicit_serializer() -> None:
    evaluation = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        as_of_local_date=date(2026, 8, 1),
    )
    facts, evidence = serialize_ota(evaluation)
    assert facts["window_start"] == "2026-08-01"
    assert evidence["booking_data_source_id"] == str(SRC)
    assert serialize_facts(evaluation) == (facts, evidence)


def test_cost_has_its_own_explicit_serializer() -> None:
    evaluation = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        target_period_start=date(2026, 8, 1),
    )
    facts, evidence = serialize_cost(evaluation)
    assert facts["target_period_start"] == "2026-08-01"
    assert facts["cost_category"] == "LAUNDRY"
    assert serialize_facts(evaluation) == (facts, evidence)


def test_labor_has_its_own_explicit_serializer() -> None:
    evaluation = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        labor_data_source_id=uuid4(),
        target_work_date=date(2026, 8, 1),
    )
    facts, evidence = serialize_labor(evaluation)
    assert facts["work_date"] == "2026-08-01"
    assert facts["labor_category"] == "HOUSEKEEPING"
    assert serialize_facts(evaluation) == (facts, evidence)


# --- 110: no blind asdict/model_dump/__dict__ of the whole evaluation ---------------------------


def test_no_blind_full_evaluation_serialization_is_used() -> None:
    source = SERIALIZATION_FILE.read_text(encoding="utf-8")
    for forbidden in (
        "asdict(evaluation",
        "evaluation.__dict__",
        "evaluation.payload()",
        "evaluation.canonical_payload()",
        "vars(evaluation)",
        "model_dump",
    ):
        assert forbidden not in source, forbidden


# --- 111-119: no PII anywhere in the serializer's own source ------------------------------------


def test_no_pii_identifier_appears_in_the_serializer_source() -> None:
    tokens = _tokens(_identifiers(SERIALIZATION_FILE))
    hits = FORBIDDEN_TOKENS & tokens
    assert hits == set(), hits


# --- 120-123: canonical, JSON-safe payloads -------------------------------------------------------


def test_serialized_payloads_are_canonical_and_json_safe() -> None:
    evaluations: list[SourceEvaluation] = [
        revenue_evaluation(
            workspace_id=WS,
            property_id=PROP,
            data_source_id=SRC,
            stay_date=date(2026, 8, 15),
            snapshot_local_date=date(2026, 8, 1),
            decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
        ),
        ota_evaluation(
            workspace_id=WS,
            property_id=PROP,
            booking_data_source_id=SRC,
            as_of_local_date=date(2026, 8, 1),
        ),
        cost_evaluation(
            workspace_id=WS,
            property_id=PROP,
            booking_data_source_id=SRC,
            target_period_start=date(2026, 8, 1),
        ),
        labor_evaluation(
            workspace_id=WS,
            property_id=PROP,
            booking_data_source_id=SRC,
            labor_data_source_id=uuid4(),
            target_work_date=date(2026, 8, 1),
        ),
    ]
    for evaluation in evaluations:
        facts, evidence = serialize_facts(evaluation)
        # json.dumps raises TypeError on anything not JSON-safe (Decimal, UUID, date, enum, ...)
        encoded_facts = json.dumps(facts, sort_keys=True)
        encoded_evidence = json.dumps(evidence, sort_keys=True)
        assert isinstance(encoded_facts, str)
        assert isinstance(encoded_evidence, str)
        for payload in (facts, evidence):
            for value in payload.values():
                assert not isinstance(value, Decimal)
                assert not hasattr(value, "hex")  # no raw UUID object


def test_decimal_values_are_canonical_text_not_float_or_raw_decimal() -> None:
    evaluation = cost_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        target_period_start=date(2026, 8, 1),
    )
    facts, _ = serialize_cost(evaluation)
    assert facts["actual_cpor_exact"] == "6"  # canonical_text of Decimal("6.00") strips zeros
    assert isinstance(facts["actual_cpor_exact"], str)


def test_uuid_values_serialize_as_plain_strings() -> None:
    evaluation = ota_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        as_of_local_date=date(2026, 8, 1),
    )
    _, evidence = serialize_ota(evaluation)
    assert evidence["booking_data_source_id"] == str(SRC)
    assert isinstance(evidence["booking_data_source_id"], str)


def test_dates_serialize_as_iso_strings() -> None:
    evaluation = labor_evaluation(
        workspace_id=WS,
        property_id=PROP,
        booking_data_source_id=SRC,
        labor_data_source_id=uuid4(),
        target_work_date=date(2026, 8, 1),
    )
    facts, _ = serialize_labor(evaluation)
    assert facts["work_date"] == "2026-08-01"
    date.fromisoformat(facts["work_date"])  # round-trips


def test_reason_codes_of_reads_the_detectors_own_stable_codes() -> None:
    from app.modules.intelligence.revenue.types import ReasonCode

    evaluation = revenue_evaluation(
        workspace_id=WS,
        property_id=PROP,
        data_source_id=SRC,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
        reason_codes=(ReasonCode.TRIGGER_PICKUP_SHORTFALL,),
    )
    assert reason_codes_of(evaluation) == ("TRIGGER_PICKUP_SHORTFALL",)
