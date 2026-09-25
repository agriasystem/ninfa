"""Decision API V1 routes: four GET endpoints, read-only (see ADR 0018).

Every route is thin on purpose: authentication + authorization + tenant derivation happen in
`resolve_property_scope` (a dependency, so FastAPI resolves and rejects BEFORE a handler body ever
runs), query semantics are validated here, and every actual read goes through
`DecisionMemoryService` - no route ever opens a transaction, calls `DecisionService.sync()`,
`PriorityService` or a detector.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.decisions.cursor import (
    DecisionHistoryCursor,
    DecisionListCursor,
    decode_decision_history_cursor,
    decode_decision_list_cursor,
    encode_decision_history_cursor,
    encode_decision_list_cursor,
)
from app.api.v1.decisions.deps import PropertyScope, resolve_property_scope
from app.api.v1.decisions.errors import (
    DecisionNotFoundError,
    InvalidAsOfDateError,
    InvalidDecisionStatusError,
    InvalidDecisionTypeError,
    InvalidLimitError,
)
from app.api.v1.decisions.schemas import (
    DecisionDetailResponse,
    DecisionFeedResponse,
    DecisionHistoryResponse,
    DecisionListResponse,
)
from app.api.v1.decisions.serializers import (
    decision_detail_of,
    decision_list_item_of,
    feed_item_of,
    observation_detail_of,
)
from app.db.session import get_session
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.models import Decision
from app.modules.decisions.types import DecisionStatus
from app.modules.intelligence.priority.types import PriorityDecisionType

router = APIRouter(prefix="/properties/{property_id}", tags=["decisions"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _parse_as_of(as_of: str) -> date:
    try:
        return date.fromisoformat(as_of)
    except ValueError as exc:
        raise InvalidAsOfDateError() from exc


def _parse_status(status: str | None) -> DecisionStatus | None:
    if status is None:
        return None
    try:
        return DecisionStatus(status)
    except ValueError as exc:
        raise InvalidDecisionStatusError(status) from exc


def _parse_decision_type(decision_type: str | None) -> PriorityDecisionType | None:
    if decision_type is None:
        return None
    try:
        return PriorityDecisionType(decision_type)
    except ValueError as exc:
        raise InvalidDecisionTypeError(decision_type) from exc


def _validated_limit(limit: int) -> int:
    if not (1 <= limit <= _MAX_LIMIT):
        raise InvalidLimitError()
    return limit


@router.get("/decision-feed", response_model=DecisionFeedResponse, summary="Decision feed")
def get_decision_feed(
    as_of: str = Query(..., description="ISO date (YYYY-MM-DD). Mandatory: never a server clock."),
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> DecisionFeedResponse:
    as_of_date = _parse_as_of(as_of)
    memory = DecisionMemoryService(session, scope.tenant)
    feed = memory.get_feed(scope.property_id, as_of_date)
    run = feed.run
    return DecisionFeedResponse(
        property_id=feed.property_id,
        as_of_local_date=feed.as_of_local_date,
        feed_state=feed.state.value,
        decision_run_id=None if run is None else run.id,
        run_sequence=None if run is None else run.run_sequence,
        triggered_count=None if run is None else run.triggered_count,
        clear_count=None if run is None else run.clear_count,
        insufficient_count=None if run is None else run.insufficient_count,
        not_applicable_count=None if run is None else run.not_applicable_count,
        suppressed_count=None if run is None else run.suppressed_count,
        items=[feed_item_of(item) for item in feed.items],
    )


@router.get("/decisions", response_model=DecisionListResponse, summary="Decision list")
def list_decisions(
    status: str | None = Query(None),
    decision_type: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT),
    cursor: str | None = Query(None),
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> DecisionListResponse:
    parsed_status = _parse_status(status)
    parsed_type = _parse_decision_type(decision_type)
    parsed_limit = _validated_limit(limit)
    after: tuple[date, date, PriorityDecisionType, UUID] | None = None
    if cursor is not None:
        decoded = decode_decision_list_cursor(cursor)
        after = (
            decoded.last_evaluated_local_date,
            decoded.last_seen_local_date,
            decoded.decision_type,
            decoded.decision_id,
        )

    memory = DecisionMemoryService(session, scope.tenant)
    page = memory.list_decisions_page(
        scope.property_id,
        status=parsed_status,
        decision_type=parsed_type,
        limit=parsed_limit,
        after=after,
    )
    items = [
        decision_list_item_of(decision, page.latest_observations[decision.id])
        for decision in page.decisions
    ]
    next_cursor = None
    if page.has_more and page.decisions:
        last = page.decisions[-1]
        next_cursor = encode_decision_list_cursor(
            DecisionListCursor(
                last_evaluated_local_date=last.last_evaluated_local_date,
                last_seen_local_date=last.last_seen_local_date,
                decision_type=last.decision_type,
                decision_id=last.id,
            )
        )
    return DecisionListResponse(items=items, next_cursor=next_cursor)


def _decision_in_scope(
    memory: DecisionMemoryService, decision_id: UUID, scope: PropertyScope
) -> Decision:
    decision = memory.get_decision(decision_id)
    if decision is None or decision.property_id != scope.property_id:
        raise DecisionNotFoundError()
    return decision


@router.get(
    "/decisions/{decision_id}", response_model=DecisionDetailResponse, summary="Decision detail"
)
def get_decision_detail(
    decision_id: UUID,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> DecisionDetailResponse:
    memory = DecisionMemoryService(session, scope.tenant)
    decision = _decision_in_scope(memory, decision_id, scope)
    latest_observation = memory.get_latest_observation(decision_id)
    assert latest_observation is not None  # Gate 11 invariant: a Decision always has >= 1 row
    return decision_detail_of(decision, latest_observation)


@router.get(
    "/decisions/{decision_id}/history",
    response_model=DecisionHistoryResponse,
    summary="Decision history",
)
def get_decision_history(
    decision_id: UUID,
    limit: int = Query(_DEFAULT_LIMIT),
    cursor: str | None = Query(None),
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> DecisionHistoryResponse:
    parsed_limit = _validated_limit(limit)
    memory = DecisionMemoryService(session, scope.tenant)
    decision = _decision_in_scope(memory, decision_id, scope)

    after: tuple[date, int, UUID] | None = None
    if cursor is not None:
        decoded = decode_decision_history_cursor(cursor)
        after = (decoded.as_of_local_date, decoded.run_sequence, decoded.observation_id)

    page = memory.get_history_page_desc(decision_id, limit=parsed_limit, after=after)
    items = [observation_detail_of(decision.decision_type, row.observation) for row in page.items]
    next_cursor = None
    if page.has_more and page.items:
        last = page.items[-1]
        next_cursor = encode_decision_history_cursor(
            DecisionHistoryCursor(
                as_of_local_date=last.observation.as_of_local_date,
                run_sequence=last.run_sequence,
                observation_id=last.observation.id,
            )
        )
    return DecisionHistoryResponse(items=items, next_cursor=next_cursor)


__all__ = ["router"]
