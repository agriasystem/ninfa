"""Decision API V1 + Recommendation Engine V1, wired together (review items 45-53): the existing
`/decisions/{id}` detail endpoint, unchanged route, now additionally carries a `recommendation`
block. Reuses Gate 12's own `decision_api_support`/`decision_support` helpers unmodified - the
auth boundary itself (401/404) is already exhaustively covered by `test_decision_api_auth.py` and
is NOT re-derived here; these tests only prove the new field's own shape and that it never leaks
through the error path either.

`revenue_evaluation()` (Gate 11's own minimal TRIGGERED fixture) deliberately never sets
`actual_pickup`/`expected_pickup` on `PickupFacts` - it exists to exercise the DECISION LAYER's
own lifecycle concerns, not the detector's full numeric output. Fed straight through the real
pipeline, it genuinely, correctly reaches INSUFFICIENT_CONTEXT here (the rule needs those two
facts specifically - see `rules.pickup_rule`), which is exactly the real-vs-partial-data contrast
this file exploits: item 50 (INSUFFICIENT_CONTEXT) uses that fixture completely UNMODIFIED, while
item 48 (AVAILABLE) needs a fully detector-realistic `PickupFacts` instead - built locally below,
still carried end to end through the real `DecisionService.sync()` and real HTTP. Persisted
Decision Memory rows are DB-enforced immutable (`decisions_forbid_update()`), so there is no
UPDATE-after-the-fact path available even for test setup - confirmed empirically while building
this file.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    PickupFacts,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
)
from tests.decision_api_support import assert_error, authed_tenant, detail_url
from tests.decision_support import CLEAR, Evaluation, RunOutcome, fp, revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def _sync(
    db_session: Session, tenant: Tenant, evaluations: list[Evaluation], as_of: date
) -> RunOutcome:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    return sync_run(db_session, TenantContext(tenant.workspace.id), context, evaluations)


def _open_pickup_decision(db_session: Session, tenant: Tenant, *, as_of: date = D1) -> UUID:
    """A real, persisted, TRIGGERED pickup Decision - via Gate 11's own MINIMAL fixture, which
    never carries `actual_pickup`/`expected_pickup`. Its recommendation is genuinely
    INSUFFICIENT_CONTEXT (see module docstring) - used wherever a test only cares about the
    envelope (auth, leak, presence), never about an AVAILABLE payload."""
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=as_of,
    )
    outcome = _sync(db_session, tenant, [evaluation], as_of)
    [decision_id] = outcome.result.touched_decision_ids
    return decision_id


def _numerically_complete_pickup_evaluation(tenant: Tenant, *, as_of: date) -> Evaluation:
    """A TRIGGERED pickup evaluation with the full numeric `PickupFacts` a real detector run
    would produce (`actual_pickup`/`expected_pickup` set together with `missing_rooms` - see
    `pickup.py`'s own `replace(base, ..., actual_pickup=actual, expected_pickup=expected, ...)`),
    hand-built here (never re-running the real detector algorithm) so the rule under test has
    exactly the facts it needs, still carried through the real `DecisionService.sync()`."""
    facts = PickupFacts(
        current_rooms_on_books=20,
        rooms_available=40,
        actual_pickup=3,
        expected_pickup=Decimal("7.50"),
        delta_rooms=Decimal("-4.50"),
        missing_rooms=Decimal("4.50"),
        delta_percent_exact=Decimal("-60.00"),
        percent_condition=True,
        rooms_condition=True,
    )
    return RevenueDecisionEvaluation(
        decision_type=RevenueDecisionType.REV_PICKUP_LOW,
        status=EvaluationStatus.TRIGGERED,
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        target_snapshot_id=uuid4(),
        target_baseline_id=uuid4(),
        snapshot_local_date=as_of,
        stay_date=STAY,
        lead_time_days=(STAY - as_of).days,
        confidence_score=Decimal("81.23"),
        rules_version="revenue-decisions-v1",
        calculation_fingerprint=fp(f"pickup-full:{as_of}:{uuid4()}"),
        reason_codes=(),
        facts=facts,
        evidence_snapshot_ids=(uuid4(),),
        revenue_gap_proxy=Decimal("500.00"),
        reference_adr=Decimal("100.00"),
        reference_adr_source=ReferenceAdrSource.CURRENT_ON_BOOKS_ADR,
    )


# --- 45: authenticated detail includes a recommendation -----------------------------------------


def test_authenticated_detail_includes_recommendation(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _open_pickup_decision(db_session, at.tenant)

    response = api_client.get(detail_url(at.tenant.property.id, decision_id))
    assert response.status_code == 200, response.text
    assert "recommendation" in response.json()


# --- 46-47: the error path never carries the field either ---------------------------------------


def test_unauthorized_decision_detail_leaks_no_recommendation(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    tenant = factory.tenant()  # never a member here
    authed_tenant(factory, authenticated_as)
    response = api_client.get(detail_url(tenant.property.id, uuid4()))
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")
    assert "recommendation" not in response.json()


def test_unauthenticated_decision_detail_leaks_no_recommendation(
    api_client: TestClient, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    response = api_client.get(detail_url(tenant.property.id, uuid4()))
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")
    assert "recommendation" not in response.json()


# --- 48: AVAILABLE payload shape, via a real, numerically-complete pipeline run ------------------


def test_available_recommendation_shape_via_real_http(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = _numerically_complete_pickup_evaluation(tenant, as_of=D1)
    outcome = _sync(db_session, tenant, [evaluation], D1)
    [decision_id] = outcome.result.touched_decision_ids

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    recommendation = body["recommendation"]
    assert recommendation["status"] == "AVAILABLE"
    assert recommendation["version"] == "recommendation-engine-v1"
    assert recommendation["requires_human_review"] is True
    assert len(recommendation["fingerprint"]) == 64
    assert isinstance(recommendation["confidence"], str)

    primary = recommendation["primary_action"]
    assert primary is not None
    assert primary["action_code"] == "REVIEW_PRICING_AND_AVAILABILITY"
    assert primary["category"] == "REVIEW_PRICING"
    assert primary["requires_human_review"] is True
    assert primary["title_key"] == "recommendation.action.REVIEW_PRICING_AND_AVAILABILITY.title"
    assert isinstance(recommendation["supporting_checks"], list)


# --- 49: NOT_AVAILABLE payload shape, via a real CLEAR pipeline run ------------------------------


def test_not_available_recommendation_shape_via_real_http(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    decision_id = _open_pickup_decision(db_session, tenant, as_of=D1)
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1 + timedelta(days=1),
        status=CLEAR,
    )
    _sync(db_session, tenant, [clear], D1 + timedelta(days=1))

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    recommendation = body["recommendation"]
    assert recommendation["status"] == "NOT_AVAILABLE"
    assert recommendation["primary_action"] is None
    assert recommendation["supporting_checks"] == []
    assert recommendation["confidence"] is None
    assert recommendation["requires_human_review"] is True  # unconditional, even with no action


# --- 50: INSUFFICIENT_CONTEXT payload shape, via a real but numerically-partial pipeline run -----


def test_insufficient_context_recommendation_shape_via_real_http(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _open_pickup_decision(db_session, at.tenant)

    body = api_client.get(detail_url(at.tenant.property.id, decision_id)).json()
    recommendation = body["recommendation"]
    assert recommendation["status"] == "INSUFFICIENT_CONTEXT"
    assert recommendation["primary_action"] is None
    assert recommendation["supporting_checks"] == []


# --- 51: Decimal-as-string, never a float, inside the recommendation block ----------------------


def test_recommendation_decimals_remain_strings(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = _numerically_complete_pickup_evaluation(tenant, as_of=D1)
    outcome = _sync(db_session, tenant, [evaluation], D1)
    [decision_id] = outcome.result.touched_decision_ids

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    recommendation = body["recommendation"]
    assert isinstance(recommendation["confidence"], str)
    for value in recommendation["primary_action"]["supporting_facts"].values():
        assert isinstance(value, str)


# --- 52-53: no internal engine bookkeeping or raw identity leaked --------------------------------


def test_recommendation_leaks_no_internal_engine_bookkeeping(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _open_pickup_decision(db_session, at.tenant)

    body = api_client.get(detail_url(at.tenant.property.id, decision_id)).json()
    recommendation = body["recommendation"]
    assert set(recommendation.keys()) == {
        "status",
        "version",
        "fingerprint",
        "primary_action",
        "supporting_checks",
        "confidence",
        "requires_human_review",
    }
    raw = str(body)
    for forbidden in (
        "generated_from_observation_id",
        "generated_from_evaluation_fingerprint",
        "identity_payload",
        "identity_version",
        "identity_key",
    ):
        assert forbidden not in raw, forbidden
