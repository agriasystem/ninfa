from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.meta import SERVICE_NAME, get_version
from app.core.request_id import REQUEST_ID_HEADER, RequestIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        service=SERVICE_NAME, level=settings.log_level, json_output=settings.is_production
    )

    app = FastAPI(
        title="NINFA API",
        version=get_version(),
        debug=settings.debug,
        # Interactive docs are a development aid only.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    # The THIS-APP settings instance (not necessarily the same object `get_settings()` would
    # return - tests build an app from an overridden `Settings`, e.g. `session_cookie_secure`):
    # `app.core.config.get_request_settings` reads it back for anything that must honour what
    # THIS app was actually configured with, not the process-wide cached settings.
    app.state.settings = settings

    # Middleware added last is outermost: RequestId must wrap CORS so every response carries the ID.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)
    app.include_router(api_v1_router)
    return app
