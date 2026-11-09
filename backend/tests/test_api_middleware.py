from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from airsight.api.deps import get_champion
from airsight.api.main import create_app
from airsight.api.middleware import LATEST_TTL, MODEL_TTL, PAST_TTL, cache_ttl, normalized_query
from airsight.api.schemas import ModelInfo
from airsight.api.store import MemoryStore

START = 1_800_000_000.0  # a whole minute, so windows are easy to reason about
NOW = datetime.fromtimestamp(START, UTC)
CHAMPION_INFO = ModelInfo(
    name="airsight-correction",
    version=1,
    model_version="airsight-correction/1",
    dataset="abc123",
    trained_before=NOW,
    promoted_at=NOW,
    final_test=None,
    model_card="https://example.com/card",
)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


class BrokenStore:
    """Redis that is down."""

    async def get(self, key: str) -> bytes | None:
        raise RedisConnectionError("down")

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        raise RedisConnectionError("down")

    async def incr(self, key: str, ttl_seconds: int) -> int:
        raise RedisConnectionError("down")


def model_app(clock: Clock, calls: list[int], limit: int = 0) -> FastAPI:
    """An app whose /v1/model counts how often it is really computed."""
    app = create_app(store=MemoryStore(clock), rate_limit_per_minute=limit, clock=clock)

    def champion() -> ModelInfo:
        calls.append(1)
        return CHAMPION_INFO

    app.dependency_overrides[get_champion] = champion
    return app


# Errors: Problem Details (RFC 9457)


def test_unknown_path_is_a_problem() -> None:
    response = TestClient(create_app(store=MemoryStore())).get("/v1/nothing-here")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Not Found",
    }


def test_invalid_parameters_list_each_field() -> None:
    client = TestClient(create_app(store=MemoryStore()))

    response = client.get("/v1/readings/nearest", params={"lat": 100})

    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert body["title"] == "Unprocessable Entity"
    assert {e["field"] for e in body["errors"]} == {"query.lat", "query.lon"}


def test_unexpected_errors_reveal_nothing() -> None:
    app = create_app(store=MemoryStore())

    def broken() -> ModelInfo:
        raise RuntimeError("SELECT secret FROM internals")

    app.dependency_overrides[get_champion] = broken

    response = TestClient(app, raise_server_exceptions=False).get("/v1/model")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert "secret" not in response.text
    assert response.json()["detail"] == "Something went wrong on our side"


# Rate limiting


def test_rate_limit_allows_the_limit_then_answers_429() -> None:
    clock = Clock()
    client = TestClient(model_app(clock, [], limit=3))

    remaining = [client.get("/v1/model").headers["RateLimit-Remaining"] for _ in range(3)]
    blocked = client.get("/v1/model")

    assert remaining == ["2", "1", "0"]
    assert blocked.status_code == 429
    assert blocked.headers["content-type"] == "application/problem+json"
    assert blocked.headers["Retry-After"] == "60"
    assert blocked.headers["RateLimit-Limit"] == "3"


def test_rate_limit_resets_each_minute() -> None:
    clock = Clock()
    client = TestClient(model_app(clock, [], limit=1))
    client.get("/v1/model")
    clock.now += 45

    blocked = client.get("/v1/model")
    clock.now += 15
    allowed = client.get("/v1/model")

    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "15"
    assert allowed.status_code == 200


def test_health_is_never_rate_limited() -> None:
    client = TestClient(create_app(store=MemoryStore(), rate_limit_per_minute=1))

    statuses = {client.get("/v1/health").status_code for _ in range(5)}

    assert statuses == {200}


# Caching


def test_repeated_requests_are_served_from_the_cache() -> None:
    clock, calls = Clock(), list[int]()
    client = TestClient(model_app(clock, calls))

    first = client.get("/v1/model")
    clock.now += 600
    second = client.get("/v1/model")

    assert len(calls) == 1
    assert (first.headers["X-Cache"], second.headers["X-Cache"]) == ("MISS", "HIT")
    assert second.json() == first.json()
    assert first.headers["Cache-Control"] == f"public, max-age={MODEL_TTL}"
    assert second.headers["Cache-Control"] == f"public, max-age={MODEL_TTL - 600}"


def test_cache_entries_expire() -> None:
    clock, calls = Clock(), list[int]()
    client = TestClient(model_app(clock, calls))
    client.get("/v1/model")
    clock.now += MODEL_TTL

    response = client.get("/v1/model")

    assert len(calls) == 2
    assert response.headers["X-Cache"] == "MISS"


def test_errors_are_not_cached() -> None:
    clock, calls = Clock(), list[int]()
    app = model_app(clock, calls)

    def not_promoted() -> ModelInfo:
        calls.append(1)
        raise HTTPException(status_code=503, detail="No model has been promoted yet")

    app.dependency_overrides[get_champion] = not_promoted
    client = TestClient(app)

    statuses = [client.get("/v1/model").status_code for _ in range(2)]

    assert statuses == [503, 503]
    assert len(calls) == 2


def test_the_api_works_while_redis_is_down() -> None:
    calls: list[int] = []
    app = create_app(store=BrokenStore(), rate_limit_per_minute=60)

    def champion() -> ModelInfo:
        calls.append(1)
        return CHAMPION_INFO

    app.dependency_overrides[get_champion] = champion
    client = TestClient(app)

    responses = [client.get("/v1/model") for _ in range(2)]

    assert [r.status_code for r in responses] == [200, 200]
    assert len(calls) == 2  # computed every time, but answered
    assert "RateLimit-Limit" not in responses[0].headers


def test_nearby_coordinates_share_a_cache_entry() -> None:
    a = normalized_query("lon=-122.27271&lat=37.87161&limit=3")
    b = normalized_query("lat=37.87158&limit=3&lon=-122.27268")

    assert a == b == "lat=37.872&limit=3&lon=-122.273"


@pytest.mark.parametrize(
    ("path", "query", "ttl"),
    [
        ("/v1/readings/nearest", "lat=1&lon=2", LATEST_TTL),
        ("/v1/sensors", "", LATEST_TTL),
        ("/v1/sensors/pa-1", "", LATEST_TTL),
        (
            "/v1/sensors/pa-1/history",
            "start=2027-01-01T00:00:00Z&end=2027-01-02T00:00:00Z",
            PAST_TTL,
        ),
        (
            "/v1/sensors/pa-1/history",
            "start=2027-01-14T00:00:00Z&end=2027-01-15T06:00:00Z",
            LATEST_TTL,
        ),
        ("/v1/sensors/pa-1/history", "start=x&end=y", None),
        ("/v1/model", "", MODEL_TTL),
        ("/v1/accuracy", "days=7", 15 * 60),
        ("/v1/health", "", None),
    ],
)
def test_each_kind_of_answer_has_its_own_lifetime(path: str, query: str, ttl: int | None) -> None:
    now = datetime(2027, 1, 15, 12, tzinfo=UTC)

    assert cache_ttl(path, query, now) == ttl
