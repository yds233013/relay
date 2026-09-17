"""Request correlation, request logging and baseline security headers (pure ASGI)."""

from __future__ import annotations

import re
import time
from typing import Final

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from relay.core.ids import uuid7
from relay.core.logging import get_logger

REQUEST_ID_HEADER: Final = "x-request-id"
_SAFE_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9._\-]{8,128}")
_SECURITY_HEADERS: Final = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cache-control": "no-store",
    # SEC-15: the API answers with JSON only. Nothing it returns may load or embed anything, and
    # nothing may embed it. The web app sets its own nonce-based policy for rendered pages.
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
}

_log = get_logger("relay.api.request")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode("latin-1"), b"")
        candidate = incoming.decode("latin-1")
        # Untrusted header: accept only a safe, bounded token; otherwise mint our own.
        request_id = candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else str(uuid7())
        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                # Path only: query strings can carry data values and are never logged.
                _log.info(
                    "http_request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
