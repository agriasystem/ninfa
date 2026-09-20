from fastapi import APIRouter

from app.core.meta import SERVICE_NAME, get_version
from app.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME, version=get_version())
