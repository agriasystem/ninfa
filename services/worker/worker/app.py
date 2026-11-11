"""The Procrastinate application: a PostgreSQL-backed job queue (no Redis, no extra broker)."""

import procrastinate

from app.core.config import get_settings
from worker.connector import QueueConnector

DEFAULT_QUEUE = "default"

app = procrastinate.App(
    # `QueueConnector`: a queueing lock already taken is `AlreadyEnqueued` whatever language
    # PostgreSQL speaks (worker/connector.py), not a worker that stops.
    connector=QueueConnector(conninfo=get_settings().libpq_conninfo),
    # Task modules are imported when the worker starts; new gates add their modules here.
    import_paths=["worker.tasks", "worker.daily"],
)
