"""Dati overview API V1: ONE read-only GET (see docs/architecture/data-ui-v1.md and ADR 0031).

    GET /api/v1/properties/{property_id}/data/overview?as_of=YYYY-MM-DD&period=7|30

Thin on purpose: authentication, authorization and tenant derivation happen in
`resolve_property_scope` (the SAME dependency every property route uses, so a missing, archived or
foreign property is the same 404), the query is validated here, and every read goes through
`DataOverviewService`. No route opens a transaction, runs a detector, calls `DecisionService.sync()`
or touches a language model: the page is a deterministic projection of what NINFA already stores.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.data.errors import InvalidPeriodError
from app.api.v1.data.schemas import DataOverviewResponse
from app.api.v1.data.serializers import data_overview_response_of
from app.api.v1.decisions.deps import PropertyScope, resolve_property_scope
from app.api.v1.decisions.errors import InvalidAsOfDateError, PropertyNotFoundError
from app.db.session import get_session
from app.modules.data_overview.service import DataOverviewError, DataOverviewService
from app.modules.data_overview.types import ALLOWED_PERIOD_DAYS, PERIOD_DAYS_LONG

router = APIRouter(prefix="/properties/{property_id}/data", tags=["data"])


def _parse_as_of(as_of: str) -> date:
    try:
        return date.fromisoformat(as_of)
    except ValueError as exc:
        raise InvalidAsOfDateError() from exc


@router.get("/overview", response_model=DataOverviewResponse, summary="Dati overview")
def get_data_overview(
    as_of: str = Query(..., description="ISO date (YYYY-MM-DD). Mandatory: never a server clock."),
    period: int = Query(PERIOD_DAYS_LONG, description="Stay nights counted from `as_of`: 7 or 30."),
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> DataOverviewResponse:
    as_of_date = _parse_as_of(as_of)
    if period not in ALLOWED_PERIOD_DAYS:
        raise InvalidPeriodError()
    try:
        overview = DataOverviewService(session, scope.tenant).overview(
            scope.property_id, as_of_date, period
        )
    except DataOverviewError as exc:
        # The scope dependency already proved the property is readable: this is a defensive 404 for
        # a property that vanished mid-request, never a way to tell which ids exist.
        raise PropertyNotFoundError() from exc
    return data_overview_response_of(overview)
