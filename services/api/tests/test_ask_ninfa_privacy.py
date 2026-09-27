"""Gate 18 review items 15-25: runtime PII scan of the SERIALIZED `AskDecisionContext` - the exact
JSON string a language model provider would receive. Reuses `test_decision_api_privacy.py`'s own
sentinel-injection technique: an open string field (`currency`/`rules_version`/`cost_currency`) is
set to a distinct, obviously-not-PII probe to prove the scan actually reaches real content, then
every closed PII sentinel is asserted absent.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.context_builder import AskDecisionContextBuilder
from app.modules.ai.ask_ninfa.serialization import serialize_context
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.recommendations.engine import RecommendationEngine
from tests.decision_support import cost_evaluation, labor_evaluation, sync_run
from tests.support import BookingFactory

D1 = date(2026, 8, 1)

_OPEN_FIELD_PROBE = "OPEN_STRING_FIELD_PROBE_NOT_PII"

_FORBIDDEN_SENTINELS = (
    "PII_GUEST_NAME_SENTINEL",  # 16
    "PII_EMAIL_SENTINEL@example.com",  # 17
    "PII_PHONE_SENTINEL",  # 18 (also stands in for 19's "employee identity")
    "PII_EMPLOYEE_SENTINEL",
    "PII_TAXCODE_SENTINEL",  # 20
    "PII_ADDRESS_SENTINEL",  # 21
    "PII_IBAN_SENTINEL",  # 22
    "PII_MEDICAL_SENTINEL",  # 23
    "PII_SUPPLIER_NAME_SENTINEL",  # 24
    "SESSION_TOKEN_SENTINEL",  # 25 (also stands in for password/hash)
    "PASSWORD_HASH_SENTINEL",
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


def test_serialized_context_carries_no_pii_sentinel_for_cost_or_labor(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    labor_source: UUID = factory.data_source(tenant.property).id

    cost = replace(
        cost_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            target_period_start=D1,
            currency=_OPEN_FIELD_PROBE,
        ),
        rules_version=_OPEN_FIELD_PROBE,
    )
    labor = replace(
        labor_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            labor_data_source_id=labor_source,
            target_work_date=D1,
        ),
        cost_currency=_OPEN_FIELD_PROBE,
        rules_version=_OPEN_FIELD_PROBE,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_ctx = TenantContext(tenant.workspace.id)
    outcome = sync_run(db_session, tenant_ctx, context, [cost, labor])

    memory = DecisionMemoryService(db_session, tenant_ctx)
    serialized: list[str] = []
    for decision_id in outcome.result.touched_decision_ids:
        decision = memory.get_decision(decision_id)
        latest = memory.get_latest_observation(decision_id)
        assert decision is not None and latest is not None
        recommendation = RecommendationEngine().evaluate(decision, latest)
        ask_context = AskDecisionContextBuilder().build(decision, latest, recommendation, [latest])
        serialized.append(serialize_context(ask_context))

    all_strings: list[str] = []
    for blob in serialized:
        all_strings.extend(_flatten_strings({"blob": blob}))
        all_strings.append(blob)

    # Sanity (item 15's own precondition): the probe IS present, proving the scan reaches real,
    # whitelisted content - never a scan that would trivially pass over an empty context.
    assert any(_OPEN_FIELD_PROBE in value for value in all_strings)

    for sentinel in _FORBIDDEN_SENTINELS:
        hits = [value for value in all_strings if sentinel in value]
        assert hits == [], (sentinel, hits)
