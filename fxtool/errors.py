"""The error contract.

Every failure leaves this service the same way: a non-2xx status and a body of
exactly {"error": "<code>", "message": "<a sentence a person could read>"}.

The caller is a language model talking to a paying customer. It needs a stable
code to branch on and a sentence it can repeat. It must never receive a 200 with
a made-up number instead of an error, and it must never receive a stack trace.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("fxtool")

# The single source of truth for our error codes. The README table is this table.
# Adding a code here is deliberate; tool_error() refuses anything not listed.
STATUS: dict[str, int] = {
    # the caller asked for something we will not answer
    "invalid_amount": 422,
    "invalid_currency": 422,
    "unknown_currency": 422,
    "same_currency": 400,
    "invalid_date": 422,
    "date_in_future": 422,
    "date_before_series": 422,
    "invalid_request": 422,
    # we asked upstream and could not get an honest answer
    "no_rate_for_date": 404,
    "upstream_timeout": 504,
    "upstream_unavailable": 502,
    "upstream_invalid_response": 502,
    # everything else
    "not_found": 404,
    "method_not_allowed": 405,
    "internal_error": 500,
}

# Which code a framework-level validation failure belongs to, by parameter name.
_CODE_BY_PARAM = {
    "amount": "invalid_amount",
    "from": "invalid_currency",
    "to": "invalid_currency",
    "date": "invalid_date",
}


class ToolError(Exception):
    """A failure the caller is allowed to see, in full."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = STATUS[code]
        self.message = message


def tool_error(code: str, message: str) -> ToolError:
    if code not in STATUS:
        raise KeyError(f"unknown error code: {code!r}")
    return ToolError(code, message)


def error_body(code: str, message: str) -> dict[str, str]:
    return {"error": code, "message": message}


def _json(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=STATUS[code], content=error_body(code, message))


def install_error_handlers(app: FastAPI) -> None:
    """Route every kind of failure through the one envelope."""

    @app.exception_handler(ToolError)
    async def _tool_error(_: Request, exc: ToolError) -> JSONResponse:
        return _json(exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        param = str(first["loc"][-1]) if first.get("loc") else ""
        code = _CODE_BY_PARAM.get(param, "invalid_request")
        detail = str(first.get("msg", "")).rstrip(".")
        message = f"The '{param}' parameter is not usable: {detail}." if param else f"{detail}."
        return _json(code, message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code)
        if code is None:
            return _json("internal_error", "The service could not handle this request.")
        return _json(code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Logged in full for us, described in one flat sentence for the caller:
        # an internal detail is not something a customer should ever be read.
        log.exception("unhandled error on %s", request.url.path, exc_info=exc)
        return _json("internal_error", "The service hit an unexpected error and returned no rate.")
