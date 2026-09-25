"""Decision API V1: runtime PII scan of the 4 endpoints' JSON responses (see ADR 0018 and Gate
11's own `test_decision_memory_privacy.py`, whose philosophy this reuses at the HTTP boundary).

Gate 11's own reflection test already proves NONE of the four detector evaluation types (or the
facts/metric value objects one level in) has ANY field capable of holding guest data, employee
identity, a tax code, an address, an IBAN, medical data or a supplier free-text name - so there is
nowhere in the real pipeline to inject them, and this module does not force them into types that
cannot structurally hold them (the review's own instruction). What IS a genuine open string
(`rules_version`, `currency`, `cost_currency` - never PII) is marked with a distinct, obviously-
not-PII probe to prove the scan below actually reaches the response bodies.
"""

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_api_support import authed_tenant, detail_url, feed_url, history_url, list_url
from tests.decision_support import cost_evaluation, labor_evaluation, sync_run
from tests.support import BookingFactory

D1 = date(2026, 8, 1)
D1_ISO = "2026-08-01"

_OPEN_FIELD_PROBE = "OPEN_STRING_FIELD_PROBE_NOT_PII"

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


def test_no_pii_sentinel_anywhere_in_the_four_endpoints_json_responses(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
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
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [cost, labor])
    decision_ids = list(outcome.result.touched_decision_ids)

    bodies = [
        api_client.get(feed_url(tenant.property.id, D1_ISO)).json(),
        api_client.get(list_url(tenant.property.id)).json(),
        *(api_client.get(detail_url(tenant.property.id, did)).json() for did in decision_ids),
        *(api_client.get(history_url(tenant.property.id, did)).json() for did in decision_ids),
    ]

    all_strings: list[str] = []
    for body in bodies:
        all_strings.extend(_flatten_strings(body))

    # Sanity: the probe IS found somewhere - proves the scan reaches real response content.
    assert any(_OPEN_FIELD_PROBE in value for value in all_strings)

    for sentinel in _FORBIDDEN_PII_SENTINELS:
        hits = [value for value in all_strings if sentinel in value]
        assert hits == [], (sentinel, hits)
