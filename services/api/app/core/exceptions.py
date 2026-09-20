"""Application exceptions. Framework-free: services and repositories import from here.

`app.core.errors` turns them into HTTP responses; nothing in this module knows about HTTP
beyond a status code suggestion carried for that translation.
"""

from http import HTTPStatus
from typing import Any


class AppError(Exception):
    """Base class for expected, client-facing errors raised by application code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = HTTPStatus.BAD_REQUEST,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = int(status_code)
        self.details = details


class NotFoundError(AppError):
    """An entity does not exist *for the current tenant*.

    Missing and "belongs to another workspace" are deliberately indistinguishable.
    """

    def __init__(self, entity: str) -> None:
        super().__init__("not_found", f"{entity} not found", status_code=HTTPStatus.NOT_FOUND)
