"""The Procrastinate application: a PostgreSQL-backed job queue (no Redis, no extra broker)."""

import procrastinate

from app.core.config import get_settings

DEFAULT_QUEUE = "default"

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().libpq_conninfo),
    # Task modules are imported when the worker starts; new gates add their modules here.
    import_paths=["worker.tasks"],
)
