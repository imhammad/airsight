"""Every error the API returns is Problem Details, RFC 9457 (ADR 0008)."""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from airsight.api.schemas import Problem

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"

# What each error means on this API, for the OpenAPI contract
DESCRIPTIONS = {
    400: "Bad request, such as a cursor this API did not return",
    404: "No sensor with this id",
    422: "Invalid parameters; errors lists each one",
    429: "More than the rate limit; wait for Retry-After seconds",
    500: "Unexpected server error",
    503: "No model has been promoted yet",
}


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
    """Answer every error with Problem Details, and say so in the OpenAPI schema."""
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(Exception, _unexpected)

    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            # responses() refers to Problem; FastAPI only adds models it sees itself
            generate()["components"]["schemas"]["Problem"] = Problem.model_json_schema()
        return app.openapi_schema  # type: ignore[return-value]

    app.openapi = openapi  # type: ignore[method-assign]


def responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entries saying these statuses answer with Problem Details."""
    schema = {"$ref": "#/components/schemas/Problem"}
    return {
        status: {"description": DESCRIPTIONS[status], "content": {PROBLEM_JSON: {"schema": schema}}}
        for status in statuses
    }
