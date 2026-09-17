"""RFC 9457 problem+json responses.

Responses carry a stable ``code``. They never include stack traces, SQL, or submitted values
(SEC-14): validation errors report the location and message only, not the rejected input.
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from relay.core.errors import RelayError
from relay.core.logging import get_logger

PROBLEM_MEDIA_TYPE = "application/problem+json"

_log = get_logger("relay.api.problems")


def problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, object]] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "type": "about:blank",
        "status": status,
        "code": code,
        "title": title,
    }
    if detail is not None:
        body["detail"] = detail
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


async def _relay_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RelayError):  # registered only for this type
        raise exc
    return problem_response(
        status=exc.http_status, code=exc.code, title=exc.title, detail=exc.detail
    )


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # registered only for this type
        raise exc
    errors: list[dict[str, object]] = [
        {
            "loc": list(error.get("loc", ())),
            "msg": str(error.get("msg", "")),
            "type": error.get("type"),
        }
        for error in exc.errors()
    ]
    return problem_response(
        status=422,
        code="request.validation_failed",
        title="Request validation failed",
        errors=errors,
    )


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # registered only for this type
        raise exc
    phrase = HTTPStatus(exc.status_code).phrase
    code = f"http.{phrase.lower().replace(' ', '_').replace('-', '_')}"
    return problem_response(status=exc.status_code, code=code, title=phrase)


async def _unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
    _log.error("unhandled_exception", error_type=type(exc).__name__)
    return problem_response(
        status=500, code="internal.unexpected_error", title="Internal Server Error"
    )


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RelayError, _relay_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
