"""Mia routes: `POST /messages`, `GET /conversations`, `GET /conversations/{id}`, `DELETE ...`.

Thin on purpose, like every route here: authentication, tenancy and the property are resolved by
dependencies BEFORE a handler body runs (`resolve_mia_scope`); the question is understood and
answered by the bounded orchestrator over the closed, read-only tool catalog; the conversation is
NINFA's own (`MiaConversationService`), never a history the browser sends.

Read-only with respect to NINFA's business data, despite being a POST: nothing here calls
`DecisionService.sync()`, a detector's write path, `PriorityService`, or writes a business row. The
ONLY thing written is the person's own conversation text (ADR 0055). `Cache-Control: no-store`
everywhere: a question, an answer and a conversation are never safe to cache or replay.

A failure of Mia - the provider down, an invalid answer, a missed deadline - is an `UNAVAILABLE`
answer with HTTP 200 and nothing recorded; NINFA's other screens do not depend on this route at all.
"""

import logging
from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.v1.decisions.errors import InvalidAsOfDateError
from app.api.v1.mia.deps import (
    MiaScope,
    get_access_policy,
    get_mia_provider,
    get_registry,
    get_tool_catalog,
    resolve_mia_scope,
)
from app.api.v1.mia.errors import MiaConversationNotFoundError
from app.api.v1.mia.schemas import (
    MiaAnswerResponse,
    MiaConversationListResponse,
    MiaConversationResponse,
    MiaConversationSummary,
    MiaMessageRequest,
    MiaStoredMessage,
)
from app.core.clock import Clock, get_clock
from app.db.session import get_session
from app.modules.ai.ask_ninfa.guardrails import REFUSAL_COPY, classify_refusal
from app.modules.ai.ask_ninfa.question import validate_question
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.tool_protocol import ToolCallingProvider
from app.modules.ai.mia.access import DomainAccessPolicy
from app.modules.ai.mia.conversation import MiaConversationService
from app.modules.ai.mia.knowledge.registry import KnowledgeRegistry
from app.modules.ai.mia.orchestrator import MiaOrchestrator
from app.modules.ai.mia.tools.base import ToolCatalog, ToolRuntime
from app.modules.ai.mia.ui_context import build_page_context
from app.modules.properties.models import Property

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/properties/{property_id}/mia", tags=["mia"])


def _parse_as_of(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidAsOfDateError() from exc


@router.post(
    "/messages",
    response_model=MiaAnswerResponse,
    summary="Send a message to Mia about one property",
)
def post_message(
    payload: MiaMessageRequest,
    response: Response,
    scope: MiaScope = Depends(resolve_mia_scope),
    session: Session = Depends(get_session),
    provider: ToolCallingProvider = Depends(get_mia_provider),
    catalog: ToolCatalog = Depends(get_tool_catalog),
    registry: KnowledgeRegistry = Depends(get_registry),
    access: DomainAccessPolicy = Depends(get_access_policy),
    clock: Clock = Depends(get_clock),
) -> MiaAnswerResponse:
    """One grounded answer to one message, in the person's conversation about this property.

    Mia reaches NINFA only through the closed tool catalog, under the person's own access, with a
    bounded number of tool rounds; every answer is validated and its numbers checked against what
    the tools returned before it leaves (anything else is `UNAVAILABLE`, never a guess). A refused
    message (an action, personal data, an injection attempt) never reaches the model and never
    enters the conversation; neither does an `UNAVAILABLE` turn.
    """
    response.headers["Cache-Control"] = "no-store"

    # Property-not-found (404) already happened inside `resolve_property_scope`.
    as_of = _parse_as_of(payload.as_of_local_date)
    question = validate_question(payload.message)

    conversations = MiaConversationService(session, scope.tenant, clock=clock)
    conversation = None
    if payload.conversation_id is not None:
        conversation = conversations.get_owned(
            payload.conversation_id, scope.property_id, scope.user.user_id
        )
        if conversation is None:
            raise MiaConversationNotFoundError()

    refusal = classify_refusal(question)
    if refusal is not None:
        return MiaAnswerResponse(
            status=AskStatus.REFUSED.value,
            answer=None,
            limitations=[REFUSAL_COPY[refusal]],
            grounding_refs=[],
            conversation_id=None if conversation is None else conversation.id,
        )

    prop = session.get(Property, scope.property_id)
    assert prop is not None  # `resolve_property_scope` just loaded this exact row
    page = build_page_context(
        session, scope.tenant, scope.property_id, payload.ui_context, registry
    )
    runtime = ToolRuntime(
        session=session,
        tenant=scope.tenant,
        property_id=scope.property_id,
        property_name=prop.name,
        timezone=ZoneInfo(prop.timezone),
        currency=prop.currency,
        as_of=as_of,
        user=scope.user,
        access=access,
        registry=registry,
        page=page,
    )
    context = conversations.model_context(conversation)
    result = MiaOrchestrator(provider, catalog).run(
        runtime, question, history=context.history, summary=context.summary
    )

    recorded: UUID | None = None if conversation is None else conversation.id
    if result.status in (AskStatus.ANSWERED, AskStatus.INSUFFICIENT_CONTEXT):
        if conversation is None:
            conversation = conversations.create(scope.property_id, scope.user.user_id, question)
        conversations.record_exchange(conversation, question=question, result=result)
        recorded = conversation.id
        # The one write of this route: the person's own conversation (no business row is touched).
        session.commit()
    metrics = result.metrics
    # The observability record of the turn: what it cost and how it went, never what was said (no
    # question, no answer, no argument, no tool payload, no chain of thought).
    logger.info(
        "mia_turn conversation=%s status=%s model_calls=%d tool_calls=%d tool_failures=%d "
        "corrected=%s reasoning=%s input_tokens=%d output_tokens=%d reasoning_tokens=%d "
        "elapsed_ms=%d failure_kind=%s",
        recorded or "-",
        result.status.value,
        metrics.model_calls,
        metrics.tool_calls,
        metrics.tool_failures,
        metrics.corrected,
        ",".join(metrics.reasoning) or "-",
        metrics.input_tokens,
        metrics.output_tokens,
        metrics.reasoning_tokens,
        metrics.elapsed_ms,
        metrics.failure_kind or "-",
    )
    return MiaAnswerResponse(
        status=result.status.value,
        answer=result.answer,
        limitations=list(result.limitations),
        grounding_refs=list(result.grounding_refs),
        conversation_id=recorded,
    )


@router.get(
    "/conversations",
    response_model=MiaConversationListResponse,
    summary="The person's recent conversations with Mia about one property",
)
def list_conversations(
    response: Response,
    scope: MiaScope = Depends(resolve_mia_scope),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> MiaConversationListResponse:
    response.headers["Cache-Control"] = "no-store"
    service = MiaConversationService(session, scope.tenant, clock=clock)
    rows = service.list_recent(scope.property_id, scope.user.user_id)
    return MiaConversationListResponse(
        conversations=[
            MiaConversationSummary(
                id=row.id,
                title=row.title,
                updated_at=row.last_message_at,
                message_count=len(service.messages_of(row)),
            )
            for row in rows
        ]
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=MiaConversationResponse,
    summary="One conversation with Mia, to restore it after a refresh",
)
def get_conversation(
    conversation_id: UUID,
    response: Response,
    scope: MiaScope = Depends(resolve_mia_scope),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> MiaConversationResponse:
    response.headers["Cache-Control"] = "no-store"
    service = MiaConversationService(session, scope.tenant, clock=clock)
    row = service.get_owned(conversation_id, scope.property_id, scope.user.user_id)
    if row is None:
        raise MiaConversationNotFoundError()
    return MiaConversationResponse(
        id=row.id,
        title=row.title,
        updated_at=row.last_message_at,
        messages=[
            MiaStoredMessage(
                role="user" if message.role == "user" else "assistant",
                content=message.content,
                created_at=message.at,
                status=message.status,
                limitations=list(message.limitations),
            )
            for message in service.messages_of(row)
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    summary="Delete one of the person's conversations with Mia",
)
def delete_conversation(
    conversation_id: UUID,
    response: Response,
    scope: MiaScope = Depends(resolve_mia_scope),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> None:
    response.headers["Cache-Control"] = "no-store"
    service = MiaConversationService(session, scope.tenant, clock=clock)
    row = service.get_owned(conversation_id, scope.property_id, scope.user.user_id)
    if row is None:
        raise MiaConversationNotFoundError()
    service.delete(row)
    session.commit()


__all__ = ["router"]
