"""Structured logging shared by api and worker.

Fields on every record: timestamp (UTC, ISO 8601), level, service, message (+ request_id).
Human-readable text in development/test, one JSON object per line in production.
"""

import json
import logging
import logging.config
from datetime import UTC, datetime
from typing import Any, cast

from app.core.request_id import request_id_var


class _ContextRecord(logging.LogRecord):
    """LogRecord as seen after `_ContextFilter` has enriched it."""

    service: str
    request_id: str


class _ContextFilter(logging.Filter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def filter(self, record: logging.LogRecord) -> bool:
        context_record = cast(_ContextRecord, record)
        context_record.service = self._service
        context_record.request_id = request_id_var.get()
        return True


def _iso_utc(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")


class _TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            "%(timestamp)s %(levelname)-8s [%(service)s] %(name)s: %(message)s "
            "(request_id=%(request_id)s)"
        )

    def format(self, record: logging.LogRecord) -> str:
        record.timestamp = _iso_utc(record)
        return super().format(record)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context_record = cast(_ContextRecord, record)
        payload: dict[str, Any] = {
            "timestamp": _iso_utc(record),
            "level": record.levelname,
            "service": context_record.service,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": context_record.request_id,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, service: str, level: str = "INFO", json_output: bool = False) -> None:
    """(Re)configure the root logger. Safe to call more than once."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"context": {"()": _ContextFilter, "service": service}},
            "formatters": {
                "default": {"()": _JsonFormatter if json_output else _TextFormatter},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["context"],
                },
            },
            "root": {"level": level, "handlers": ["console"]},
        }
    )
