"""Runtime privacy/data-minimization proof for the Decision Layer, on top of (never instead of)
`test_decision_serialization.py`'s own static AST scan of `serialization.py`'s source.

Two complementary checks:

* `test_no_evaluation_field_is_an_unconstrained_free_text_string` - RUNTIME REFLECTION over the
  four detector evaluation types (and the two facts/metric value objects the serializer reads one
  level into): every field is either a structured value (UUID, date, Decimal, bool, int, one of
  this codebase's own closed `StrEnum`s, or a tuple of one) or one of a small, audited set of
  non-PII open-string fields (an ISO currency code, a hand-written rules/metric version constant).
  This is a WHITELIST over the UPSTREAM types themselves, not the serializer's own source: if a
  future detector change ever added a free-text field (a name, a note, a label) to one of these
  dataclasses, this test - not only the serializer's source scan - would fail, even before anyone
  wired it into `serialize_facts()`.

* `test_pii_sentinels_never_reach_persisted_decision_memory` - a REAL run: real evaluations, a
  real `DecisionService.sync()` against a real Postgres session, real persisted `Decision` and
  `DecisionObservation` rows read back and walked recursively. The reflection test above already
  establishes that NONE of the nine PII categories below (guest, email, phone, employee, tax code,
  address, IBAN, medical, supplier free-text name) has ANY field to be written into anywhere in the
  real pipeline - so this test does not force them into types that cannot structurally hold them
  (the Gate 11 review explicitly asked not to). Instead it marks the small number of fields that
  ARE genuine open strings (`currency`, `cost_currency`, `rules_version` - never PII, always a
  currency code or a version constant) with a distinct, non-PII probe token to prove the scan
  itself actually reaches persisted data, then asserts zero occurrences of the nine PII sentinels
  anywhere in the recursively-flattened `facts_payload`/`evidence_payload`/`source_reason_codes`/
  `identity_payload` of every persisted row.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.costs.types import CostDecisionEvaluation, CostPeriodMetric
from app.modules.intelligence.distribution.types import OtaDependencyEvaluation
from app.modules.intelligence.labor.types import LaborDecisionEvaluation
from app.modules.intelligence.priority.types import PriorityContext, PriorityDecisionType
from app.modules.intelligence.revenue.types import (
    OccupancyFacts,
    PickupFacts,
    RevenueDecisionEvaluation,
)
from tests.decision_support import (
    Evaluation,
    cost_evaluation,
    labor_evaluation,
    ota_evaluation,
    sync_run,
)
from tests.decision_support import revenue_evaluation as _revenue_evaluation
from tests.support import BookingFactory

# --- A: runtime reflection over the upstream evaluation types themselves -------------------------

_EVALUATION_CLASSES = (
    RevenueDecisionEvaluation,
    PickupFacts,
    OccupancyFacts,
    OtaDependencyEvaluation,
    CostDecisionEvaluation,
    CostPeriodMetric,
    LaborDecisionEvaluation,
)

# The ONLY fields, anywhere in the four detectors' own evaluation/facts/metric types, whose type
# is (or includes) a bare `str`: an ISO currency code or a hand-written `*_version` constant.
# Audited by hand against every one of `_EVALUATION_CLASSES`' real fields - see the Gate 11 final
# identity & privacy integrity review.
_ALLOWED_OPEN_STRING_FIELDS = {
    "currency",
    "cost_currency",
    "rules_version",
    "metric_version",
    "expected_method",
    "calculation_version",
    "pattern_version",
    "calculation_fingerprint",
}


def _mentions_str(annotation: object) -> bool:
    if annotation is str:
        return True
    args = getattr(annotation, "__args__", None)
    if not isinstance(args, tuple):
        return False
    return any(_mentions_str(arg) for arg in args)


def test_no_evaluation_field_is_an_unconstrained_free_text_string() -> None:
    offenders = [
        f"{cls.__name__}.{field.name}"
        for cls in _EVALUATION_CLASSES
        for field in dataclasses.fields(cls)
        if _mentions_str(field.type) and field.name not in _ALLOWED_OPEN_STRING_FIELDS
    ]
    assert offenders == []


# --- B: a real run, real persisted rows, walked for nine PII categories --------------------------

# A distinct, obviously-not-PII marker: proves the walk below actually reaches the persisted
# `currency`/`cost_currency`/`rules_version` fields, so an empty result cannot be mistaken for a
# scan that silently found nothing.
_OPEN_FIELD_PROBE = "OPEN_STRING_FIELD_PROBE_NOT_PII"

# The nine categories the Gate 11 review asked to prove absent. None of them names a field that
# exists anywhere in `_EVALUATION_CLASSES` (test A above) - there is nowhere in the real pipeline
# to place them, which is the finding itself, not merely something this test constructs.
_FORBIDDEN_PII_SENTINELS = (
    "PII_GUEST_NAME_SENTINEL",
    "PII_EMAIL_SENTINEL@example.com",
    "PII_PHONE_SENTINEL",
    "PII_EMPLOYEE_SENTINEL",
    "PII_TAXCODE_SENTINEL",
    "PII_ADDRESS_SENTINEL",
    "PII_IBAN_SENTINEL",
    "PII_MEDICAL_SENTINEL",
    "PII_SUPPLIER_NAME_SENTINEL",
)


def _flatten_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _flatten_strings(item)


def test_pii_sentinels_never_reach_persisted_decision_memory(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)
    labor_source = uuid4()
    d1 = date(2026, 8, 1)

    revenue = dataclasses.replace(
        _revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=date(2026, 8, 15),
            snapshot_local_date=d1,
        ),
        rules_version=_OPEN_FIELD_PROBE,
    )
    ota = dataclasses.replace(
        ota_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=d1,
        ),
        rules_version=_OPEN_FIELD_PROBE,
    )
    # `currency` is threaded through to BOTH the evaluation and its nested `target_metric` by the
    # factory itself, so passing it here marks both real open-string channels at once.
    cost = dataclasses.replace(
        cost_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            target_period_start=d1,
            currency=_OPEN_FIELD_PROBE,
        ),
        rules_version=_OPEN_FIELD_PROBE,
    )
    labor = dataclasses.replace(
        labor_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            labor_data_source_id=labor_source,
            target_work_date=d1,
        ),
        cost_currency=_OPEN_FIELD_PROBE,
        rules_version=_OPEN_FIELD_PROBE,
    )

    context = PriorityContext(tenant.workspace.id, tenant.property.id, d1)
    outcome = sync_run(db_session, tenant_context, context, [revenue, ota, cost, labor])
    assert outcome.result.created_decision_count == 4

    memory = DecisionMemoryService(db_session, tenant_context)
    open_decisions = memory.list_open_decisions(tenant.property.id)
    assert len(open_decisions) == 4
    assert {d.decision_type for d in open_decisions} == {
        PriorityDecisionType.REV_PICKUP_LOW,
        PriorityDecisionType.REV_OTA_DEPENDENCY,
        PriorityDecisionType.COST_CPOR_ANOMALY,
        PriorityDecisionType.LABOR_OVERSTAFFING,
    }

    all_strings: list[str] = []
    for decision in open_decisions:
        all_strings.extend(_flatten_strings(decision.identity_payload))
        for observation in memory.get_history(decision.id):
            all_strings.extend(_flatten_strings(observation.facts_payload))
            all_strings.extend(_flatten_strings(observation.evidence_payload))
            all_strings.extend(_flatten_strings(list(observation.source_reason_codes)))

    # Sanity: the probe IS found somewhere (currency/cost_currency/rules_version really are
    # serialized) - an empty `all_strings` would make the assertion below vacuous.
    assert any(_OPEN_FIELD_PROBE in value for value in all_strings)

    for sentinel in _FORBIDDEN_PII_SENTINELS:
        hits = [value for value in all_strings if sentinel in value]
        assert hits == [], (sentinel, hits)


# --- identity_payload privacy: only the documented, real target dimensions -----------------------

_EXPECTED_IDENTITY_KEYS = {
    PriorityDecisionType.REV_PICKUP_LOW: {
        "identity_version",
        "decision_type",
        "workspace_id",
        "property_id",
        "booking_data_source_id",
        "stay_date",
    },
    PriorityDecisionType.REV_OTA_DEPENDENCY: {
        "identity_version",
        "decision_type",
        "workspace_id",
        "property_id",
        "booking_data_source_id",
    },
    PriorityDecisionType.COST_CPOR_ANOMALY: {
        "identity_version",
        "decision_type",
        "workspace_id",
        "property_id",
        "booking_data_source_id",
        "target_period_start",
        "cost_category",
        "currency",
    },
    PriorityDecisionType.LABOR_OVERSTAFFING: {
        "identity_version",
        "decision_type",
        "workspace_id",
        "property_id",
        "booking_data_source_id",
        "labor_data_source_id",
        "work_date",
        "labor_category",
    },
}


def test_identity_payload_has_no_keys_beyond_the_documented_target_dimensions(
    db_session: Session, factory: BookingFactory
) -> None:
    """No guest data, no employee identity, no supplier free-text name, no invoice number/raw
    data: `identity_payload` can only ever hold the exact key set `identity.py` documents per
    detector - never an extra key a future change might accidentally add."""
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)
    d1 = date(2026, 8, 1)

    evaluations: list[Evaluation] = [
        _revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=date(2026, 8, 15),
            snapshot_local_date=d1,
        ),
        ota_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=d1,
        ),
        cost_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            target_period_start=d1,
        ),
        labor_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            labor_data_source_id=uuid4(),
            target_work_date=d1,
        ),
    ]
    context = PriorityContext(tenant.workspace.id, tenant.property.id, d1)
    sync_run(db_session, tenant_context, context, evaluations)

    memory = DecisionMemoryService(db_session, tenant_context)
    for decision in memory.list_open_decisions(tenant.property.id):
        expected_keys = _EXPECTED_IDENTITY_KEYS[decision.decision_type]
        assert set(decision.identity_payload.keys()) == expected_keys
