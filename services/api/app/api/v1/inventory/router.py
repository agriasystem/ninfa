"""Room inventory API: how many rooms a property can sell.

    GET /api/v1/properties/{property_id}/room-inventory
    PUT /api/v1/properties/{property_id}/room-inventory

Thin on purpose: `resolve_property_scope` is the SAME dependency every property route uses (a
missing, archived or foreign property is the same 404) and everything else is
`RoomInventoryService`. A body that is not a whole number within the limits is refused before it
reaches the service; a "valid from" day that cannot be used is refused by the service with the same
422 and its limits in the error's details.
"""

from datetime import date

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.v1.decisions.deps import PropertyScope, resolve_property_scope
from app.db.session import get_session
from app.modules.analysis.room_inventory import (
    MAX_ROOMS,
    MIN_ROOMS,
    RoomInventoryService,
    RoomInventoryState,
)

router = APIRouter(prefix="/properties/{property_id}/room-inventory", tags=["room-inventory"])


class RoomInventoryResponse(BaseModel):
    """The capacity from the property-local today on. The limits are the backend's: a page repeats
    none of them."""

    configured: bool
    rooms_available: int | None
    varies: bool
    first_night: date | None
    last_night: date | None
    # The first night the inventory holds at all (a past one if it was saved from a past day).
    known_since: date | None
    # The property's own today and the oldest day a save may be valid from: the form's limits.
    today: date
    earliest_valid_from: date
    min_rooms: int
    max_rooms: int


class RoomInventorySaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rooms_available: int = Field(ge=MIN_ROOMS, le=MAX_ROOMS)
    # "YYYY-MM-DD", the day the number starts to be true. Missing: the property-local today. A day
    # to come, or older than the limit in `RoomInventoryResponse`, is refused (422).
    valid_from: date | None = Field(default=None, strict=False)


class RoomInventorySavedResponse(RoomInventoryResponse):
    changed_nights: int
    # A refresh of the analysis was asked for: the occupancy follows by itself.
    analysis_requested: bool


def _fields(state: RoomInventoryState) -> dict[str, object]:
    return {
        "configured": state.configured,
        "rooms_available": state.rooms_available,
        "varies": state.varies,
        "first_night": state.first_night,
        "last_night": state.last_night,
        "known_since": state.known_since,
        "today": state.today,
        "earliest_valid_from": state.earliest_valid_from,
        "min_rooms": MIN_ROOMS,
        "max_rooms": MAX_ROOMS,
    }


@router.get("", response_model=RoomInventoryResponse, summary="The rooms a property can sell")
def get_room_inventory(
    response: Response,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> RoomInventoryResponse:
    response.headers["Cache-Control"] = "no-store"
    state = RoomInventoryService(session, scope.tenant).state(scope.property_id)
    return RoomInventoryResponse.model_validate(_fields(state))


@router.put(
    "",
    response_model=RoomInventorySavedResponse,
    summary="Say how many rooms a property can sell, from a day (today when not given) on",
)
def save_room_inventory(
    body: RoomInventorySaveRequest,
    response: Response,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> RoomInventorySavedResponse:
    response.headers["Cache-Control"] = "no-store"
    saved = RoomInventoryService(session, scope.tenant).save(
        scope.property_id, body.rooms_available, valid_from=body.valid_from
    )
    return RoomInventorySavedResponse.model_validate(
        {
            **_fields(saved.state),
            "changed_nights": saved.changed_nights,
            "analysis_requested": saved.analysis_requested,
        }
    )
