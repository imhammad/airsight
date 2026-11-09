"""Every error the API returns is Problem Details, RFC 9457 (ADR 0008)."""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


def problem(
    status: int, detail: str, headers: Mapping[str, str] | None = None, **extra: Any
) -> JSONResponse:
    """A Problem Details response. "about:blank" means the status code says it all."""
    body = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        **extra,
    }
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


async def _http_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)
    return problem(error.status_code, str(error.detail), headers=error.headers)


async def _invalid_request(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    errors = [
        {"field": ".".join(str(part) for part in e["loc"]), "message": e["msg"]}
        for e in error.errors()
    ]
    return problem(422, "Some parameters are invalid; see errors", errors=errors)


async def _unexpected(request: Request, error: Exception) -> JSONResponse:
    # The details go to our logs, never to the client: no stack traces or SQL in responses
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return problem(500, "Something went wrong on our side")


def install(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(Exception, _unexpected)
