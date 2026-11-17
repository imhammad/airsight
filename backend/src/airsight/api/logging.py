"""A request ID on every request, and one log line for each (ADR 0013)."""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from airsight.core.logging import request_id

logger = logging.getLogger("airsight.api.access")

HEADER = "X-Request-ID"
# A caller's own ID is kept only if it is short and plain, so it can't forge log lines
VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
QUIET_PATHS = {"/v1/health"}  # polled by Docker every few seconds


def incoming_id(scope: Scope) -> str:
    """The caller's X-Request-ID if it is safe to keep, otherwise a new one."""
    for name, value in scope.get("headers", []):
        if name.decode("latin-1").lower() == HEADER.lower():
            candidate: str = value.decode("latin-1")
            if VALID_ID.fullmatch(candidate):
                return candidate
    return uuid.uuid4().hex


class RequestLogMiddleware:
    """Outermost middleware: gives each request an ID, returns it, and logs the outcome.

    A plain ASGI middleware rather than BaseHTTPMiddleware, so the ID set here is seen by
    everything the request runs, including the error handler for a 500.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Each request runs in its own task with its own copy of the context, so the ID
        # doesn't leak into another request. It is not reset: the 500 handler, which runs
        # outside this middleware, still needs it.
        rid = incoming_id(scope)
        request_id.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[HEADER] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            path = scope["path"]
            # The path only: a query can hold a person's location (lat, lon)
            logger.log(
                logging.DEBUG if path in QUIET_PATHS else logging.INFO,
                "%s %s %d",
                scope["method"],
                path,
                status,
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
