"""Development entrypoint: `python -m app` (host/port come from the environment)."""

from pathlib import Path

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        reload_dirs=[str(Path(__file__).parent)] if settings.debug else None,
        log_level=settings.log_level.lower(),
        log_config=None,  # logging is configured by app.core.logging
    )


if __name__ == "__main__":
    main()
