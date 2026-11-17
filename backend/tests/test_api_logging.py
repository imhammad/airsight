import json
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from airsight.api.main import create_app
from airsight.api.store import MemoryStore
from airsight.core.logging import JsonFormatter


class Lines(logging.Handler):
    """Formats each record as it is logged, inside the request, as the real handler does."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.entries: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(self.format(record)))

    def messages(self, logger: str) -> list[dict[str, object]]:
        return [entry for entry in self.entries if entry["logger"] == logger]


@pytest.fixture
def lines() -> Iterator[Lines]:
    handler = Lines()
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield handler
    root.removeHandler(handler)
    root.setLevel(level)


def app_with_test_routes(limit: int = 0) -> FastAPI:
    """The API plus two routes that need no database: one that works and one that fails."""
    app = create_app(store=MemoryStore(), rate_limit_per_minute=limit)

    @app.get("/v1/where")
    def where(lat: float) -> dict[str, float]:
        return {"lat": lat}

    @app.get("/v1/boom")
    def boom() -> None:
        raise RuntimeError("database fell over")

    return app


def test_every_response_has_a_new_request_id() -> None:
    client = TestClient(create_app(store=MemoryStore(), rate_limit_per_minute=0))

    first = client.get("/v1/health").headers["X-Request-ID"]
    second = client.get("/v1/health").headers["X-Request-ID"]

    assert len(first) == 32 and first != second


def test_a_callers_request_id_is_kept_if_it_is_plain() -> None:
    client = TestClient(create_app(store=MemoryStore(), rate_limit_per_minute=0))

    kept = client.get("/v1/health", headers={"X-Request-ID": "checkout-42.a_b"})
    replaced = client.get("/v1/health", headers={"X-Request-ID": 'x"\n{"level": "ERROR"}'})

    assert kept.headers["X-Request-ID"] == "checkout-42.a_b"
    assert len(replaced.headers["X-Request-ID"]) == 32


def test_each_request_is_logged_once_without_its_query(lines: Lines) -> None:
    client = TestClient(app_with_test_routes())

    response = client.get("/v1/where?lat=37.80")

    [entry] = lines.messages("airsight.api.access")
    assert entry["message"] == "GET /v1/where 200"
    assert entry["status"] == 200
    assert entry["request_id"] == response.headers["X-Request-ID"]
    assert isinstance(entry["duration_ms"], float)
    assert "37.80" not in json.dumps(lines.entries)  # a person's location stays out of logs


def test_health_checks_are_logged_quietly(lines: Lines) -> None:
    TestClient(create_app(store=MemoryStore(), rate_limit_per_minute=0)).get("/v1/health")

    [entry] = lines.messages("airsight.api.access")
    assert entry["level"] == "DEBUG"


def test_an_unexpected_error_can_be_found_by_its_request_id(lines: Lines) -> None:
    client = TestClient(app_with_test_routes(), raise_server_exceptions=False)

    response = client.get("/v1/boom")

    rid = response.headers["X-Request-ID"]
    assert response.status_code == 500
    [error] = lines.messages("airsight.api.problems")
    assert error["request_id"] == rid
    assert "RuntimeError: database fell over" in str(error["exception"])
    [access] = lines.messages("airsight.api.access")
    assert (access["status"], access["request_id"]) == (500, rid)


def test_refused_requests_get_an_id_and_a_line_too(lines: Lines) -> None:
    client = TestClient(app_with_test_routes(limit=1), raise_server_exceptions=False)

    client.get("/v1/boom")
    refused = client.get("/v1/boom")

    assert refused.status_code == 429
    assert [e["status"] for e in lines.messages("airsight.api.access")] == [500, 429]
    assert lines.messages("airsight.api.access")[1]["request_id"] == refused.headers["X-Request-ID"]
