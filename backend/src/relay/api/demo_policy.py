"""What an anonymous visitor may do in the public demo (``RELAY_ENV=demo``).

The demo is one shared migration that strangers explore over the internet. Roles already
limit the visitor (``demo_visitor`` holds only READ and REQUEST_INVESTIGATION), but a role table is
the wrong place to rely on for this: it is written per role, and a new route inherits whatever
permission its author chose. This module is the other way round — it refuses **every** request that
could change anything unless its exact method and path shape are on one short list, so a route
added tomorrow is denied in the demo until someone deliberately adds it here.

Two controls, deliberately independent:

1. this policy, keyed on method and path, applied before routing;
2. the role check inside each route's ``require(...)`` dependency.

Either alone would refuse a stranger's attempt to approve a change request. Hiding a button in the
web app is not a control at all and is not counted.

The allowlist is intentionally tiny. Everything a visitor needs to understand Relay is a GET; the
one exception is starting an investigation, which is what makes the AI story clickable rather than
a screenshot. It writes an investigation, its transcript and audit events, and nothing else: no
accounting value, reconciliation, gate, exposure figure or readiness verdict can move, because the
only writes the investigation path performs are its own records. It cannot cost money either — the
demo environment refuses any provider but ``demo``/``disabled`` at startup (``relay.core.config``).
"""

from __future__ import annotations

import re
from typing import Final

from starlette.types import ASGIApp, Receive, Scope, Send

from relay.core.config import Settings

SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})

_UUID = r"[0-9a-fA-F-]{36}"

# (method, compiled path) pairs a demo visitor may call despite not being a safe method.
# Keep this list as short as the demo can bear, and justify every entry.
_ALLOWED_WRITES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    # The hero interaction: run the deterministic demo investigator over real evidence. Bounded by
    # per-issue reuse, by the 20-per-hour limit every caller shares, and by the provider guard.
    ("POST", re.compile(rf"^/api/v1/migrations/{_UUID}/investigations$")),
)

DEMO_READ_ONLY_CODE: Final = "demo.read_only"
DEMO_READ_ONLY_DETAIL: Final = (
    "This is a public read-only demo of Relay. Exploring is unrestricted, and the AI "
    "investigation can be run, but changes that would alter the shared demo - uploads, mappings, "
    "corrections, approvals, policy, waivers and sign-off - are refused here. Every one of them "
    "works in a real deployment."
)


def is_allowed(method: str, path: str) -> bool:
    """Whether the public demo permits this request. Deny by default."""
    if method.upper() in SAFE_METHODS:
        return True
    return any(
        method.upper() == allowed_method and pattern.match(path)
        for allowed_method, pattern in _ALLOWED_WRITES
    )


class DemoReadOnlyMiddleware:
    """Refuse mutating requests when the process is a public demo.

    Applied as raw ASGI rather than a route dependency on purpose: dependencies are opt-in per
    route, and the point of this is that forgetting it is impossible.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self._app = app
        self._enabled = settings.public_demo

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._enabled or scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if is_allowed(scope.get("method", ""), scope.get("path", "")):
            await self._app(scope, receive, send)
            return
        await self._refuse(scope, send)

    async def _refuse(self, scope: Scope, send: Send) -> None:
        # problem+json, the same shape every other refusal uses, so the web app renders it with
        # the machinery it already has instead of showing a bare failure.
        body = (
            b'{"type":"about:blank","title":"View-only in public demo",'
            b'"status":403,"code":"' + DEMO_READ_ONLY_CODE.encode() + b'",'
            b'"detail":"' + DEMO_READ_ONLY_DETAIL.encode() + b'"}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
