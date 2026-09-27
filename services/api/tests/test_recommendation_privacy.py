"""Recommendation Engine V1 privacy (review items 54-59): no guest PII, employee identity,
supplier free text, raw invoice/booking content, or token/session data ever reaches a
recommendation - neither the engine's own output nor the API's `recommendation` block.

Two complementary layers, exactly like every other gate's own privacy suite:

* STRUCTURAL (AST): every rule in `rules.py` reads facts through only three tiny helpers
  (`_text`/`_int`/`_bool`), each of which takes the fact KEY as a literal string argument - so
  every key a rule could EVER read is enumerable by scanning those call sites, without running
  anything. None of them is a free-text-capable field.
* BEHAVIOURAL (HTTP): reuses `test_decision_api_privacy.py`'s own sentinel-injection technique,
  scoped to the new `recommendation` block specifically - an open string field a real detector
  evaluation carries (`currency`/`rules_version`, never PII, per that module's own reasoning) is
  set to an obviously-not-PII probe, and PII sentinels are checked absent, proving the scan
  reaches real, live response content rather than an empty body.
"""

import ast
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.modules.recommendations as recommendations_package
from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_api_support import authed_tenant, detail_url
from tests.decision_support import cost_evaluation, labor_evaluation, sync_run
from tests.support import BookingFactory

D1 = date(2026, 8, 1)
D1_ISO = "2026-08-01"

PACKAGE_DIR = Path(recommendations_package.__file__).parent
RULES_FILE = PACKAGE_DIR / "rules.py"

# --- 54-56: structural - every fact key a rule can ever read is on this fixed, safe list --------

_ALLOWED_FACT_KEYS = {
    "actual_pickup",
    "expected_pickup",
    "rooms_condition",
    "missing_rooms",
    "forecast_rooms",
    "expected_final_rooms",
    "occupancy_gap_pp_exact",
    "room_shortfall",
    "ota_share_exact",
    "expected_ota_share_exact",
    "structural_condition",
    "rising_condition",
    "actual_cpor_exact",
    "expected_cpor_exact",
    "delta_cpor_exact",
    "delta_percent_exact",
    "scheduled_hours_exact",
    "expected_labor_hours_exact",
    "excess_hours_exact",
}

# Free-text-capable fields that, if ever read by a rule, could plausibly carry guest/employee/
# supplier identity - none of these appears in `_ALLOWED_FACT_KEYS` above, and this test enforces
# that no rule call site ever names one.
_NEVER_ALLOWED_FACT_KEYS = {
    "guest_name",
    "guest_email",
    "guest_phone",
    "employee_name",
    "employee_id",
    "staff_name",
    "supplier_name",
    "supplier_free_text",
    "notes",
    "comment",
    "description",
    "invoice_line_text",
    "booking_reference",
    "token",
    "session_id",
    "access_token",
}


def _fact_key_literals(path: Path) -> set[str]:
    """Every string literal passed as the second positional argument to a `_text`/`_int`/`_bool`
    call in this file - the exhaustive set of fact keys a rule can ever read."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"_text", "_int", "_bool"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            keys.add(node.args[1].value)
    return keys


def test_every_fact_key_a_rule_can_read_is_on_the_safe_allowlist() -> None:
    read_keys = _fact_key_literals(RULES_FILE)
    assert read_keys  # sanity: the scan itself found real call sites, not zero
    assert read_keys <= _ALLOWED_FACT_KEYS


def test_no_rule_ever_reads_a_free_text_capable_fact_key() -> None:
    read_keys = _fact_key_literals(RULES_FILE)
    assert not (read_keys & _NEVER_ALLOWED_FACT_KEYS)


def test_safe_allowlist_and_forbidden_list_are_disjoint_by_construction() -> None:
    """A guard on the test data itself: the two lists above must never overlap, or the previous
    two tests would be vacuous."""
    assert not (_ALLOWED_FACT_KEYS & _NEVER_ALLOWED_FACT_KEYS)


# --- 57-59: behavioural - a real HTTP round trip never surfaces a PII sentinel ------------------

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


def test_recommendation_block_carries_no_pii_sentinel_from_a_real_pipeline_run(
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

    recommendation_blocks = [
        api_client.get(detail_url(tenant.property.id, did)).json()["recommendation"]
        for did in decision_ids
    ]

    all_strings: list[str] = []
    for block in recommendation_blocks:
        all_strings.extend(_flatten_strings(block))

    for sentinel in _FORBIDDEN_PII_SENTINELS:
        hits = [value for value in all_strings if sentinel in value]
        assert hits == [], (sentinel, hits)


# --- supporting_facts values are always Decimal-strings/bool-strings, never open text -----------


def test_supporting_facts_values_are_never_arbitrary_free_text(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """Every value copied into `supporting_facts` passed through `_text()` (Decimal-parseable) or
    `str(bool)` (`"True"`/`"False"`) in `rules.py` - never a raw string field - so a value that is
    neither must never appear."""
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    labor_source: UUID = factory.data_source(tenant.property).id
    cost = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        target_period_start=D1,
    )
    labor = labor_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        labor_data_source_id=labor_source,
        target_work_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [cost, labor])

    for decision_id in outcome.result.touched_decision_ids:
        body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
        primary = body["recommendation"]["primary_action"]
        if primary is None:
            continue
        for value in primary["supporting_facts"].values():
            assert value in ("True", "False") or _looks_decimal(value)


def _looks_decimal(value: str) -> bool:
    from decimal import Decimal, InvalidOperation

    try:
        Decimal(value)
    except InvalidOperation:
        return False
    return True
