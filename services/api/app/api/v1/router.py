from fastapi import APIRouter

from app.api.v1 import health
from app.api.v1.auth.router import router as auth_router
from app.api.v1.data.router import router as data_router
from app.api.v1.decisions.router import router as decisions_router
from app.api.v1.sources.router import router as sources_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(decisions_router)
api_v1_router.include_router(data_router)
api_v1_router.include_router(sources_router)
