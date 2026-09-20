"""Request / correlation ID: propagated via header, contextvar (for logs) and ASGI scope state."""

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
NO_REQUEST_ID = "-"

request_id_var: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)

# Accept a caller-supplied ID only if it is short and boring (avoids log injection).
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware:
    """Pure ASGI middleware: reuse a valid incoming X-Request-ID or generate one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        if incoming and _VALID_REQUEST_ID.match(incoming):
            request_id = incoming
        else:
            request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
