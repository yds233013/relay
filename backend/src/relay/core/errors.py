"""Structured error hierarchy.

Every error raised deliberately by Relay code is a ``RelayError`` with a stable, dotted ``code``.
The API layer maps these to RFC 9457 ``application/problem+json`` responses. Services must not
raise framework HTTP exceptions.
"""

from __future__ import annotations

from typing import ClassVar


class RelayError(Exception):
    """Base class for all deliberate Relay errors."""

    code: ClassVar[str] = "relay.error"
    title: ClassVar[str] = "Relay error"
    http_status: ClassVar[int] = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidInputError(RelayError, ValueError):
    """Input failed domain validation.

    Also a ``ValueError`` so that Pydantic validators surface it as a validation error rather than
    an unhandled exception.
    """

    code: ClassVar[str] = "input.invalid"
    title: ClassVar[str] = "Invalid input"
    http_status: ClassVar[int] = 422


class NotFoundError(RelayError):
    code: ClassVar[str] = "resource.not_found"
    title: ClassVar[str] = "Not found"
    http_status: ClassVar[int] = 404


class ConfigurationError(RelayError):
    code: ClassVar[str] = "configuration.invalid"
    title: ClassVar[str] = "Invalid configuration"
    http_status: ClassVar[int] = 500
