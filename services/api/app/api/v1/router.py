from fastapi import APIRouter

from app.api.v1 import health
from app.api.v1.decisions.router import router as decisions_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(decisions_router)
