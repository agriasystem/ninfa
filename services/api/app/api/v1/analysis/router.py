"""Analysis status API: where a property's analysis stands against its data.

    GET  /api/v1/properties/{property_id}/analysis/status
    POST /api/v1/properties/{property_id}/analysis/refresh

Thin on purpose: `resolve_property_scope` is the SAME dependency every property route uses (a
missing, archived or foreign property is the same 404) and everything else is
`AnalysisStatusService`. A refresh is requested by the import itself; the POST is only the
recovery when one failed or never reached the queue, and in any other state it changes nothing.
No route runs a detector.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.v1.analysis.schemas import AnalysisStatusResponse
from app.api.v1.decisions.deps import PropertyScope, resolve_property_scope
from app.db.session import get_session
from app.modules.analysis.status import AnalysisStatus, AnalysisStatusService

router = APIRouter(prefix="/properties/{property_id}/analysis", tags=["analysis"])


def _response_of(status: AnalysisStatus) -> AnalysisStatusResponse:
    return AnalysisStatusResponse(
        state=status.state.value,
        imported_domains=[domain.value for domain in status.imported_domains],
        latest_import_at=status.latest_import_at,
        last_analysis_at=status.last_analysis_at,
        next_attempt_at=status.next_attempt_at,
        can_retry=status.can_retry,
    )


@router.get("/status", response_model=AnalysisStatusResponse, summary="Analysis status")
def get_analysis_status(
    response: Response,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> AnalysisStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return _response_of(AnalysisStatusService(session, scope.tenant).status(scope.property_id))


@router.post("/refresh", response_model=AnalysisStatusResponse, summary="Ask for a refresh again")
def request_analysis_refresh(
    response: Response,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> AnalysisStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return _response_of(AnalysisStatusService(session, scope.tenant).retry(scope.property_id))
