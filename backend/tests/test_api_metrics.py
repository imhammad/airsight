import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from airsight.api.main import create_app
from airsight.api.metrics import RouteTemplates
from airsight.api.store import MemoryStore


def scrape(client: TestClient) -> dict[tuple[str, frozenset[tuple[str, str]]], float]:
    """Every sample on /metrics, keyed by name and labels."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
    }


def requests(samples: dict[tuple[str, frozenset[tuple[str, str]]], float], **labels: str) -> float:
    return samples.get(("airsight_api_requests_total", frozenset(labels.items())), 0.0)


def app_with_test_routes(limit: int = 0) -> FastAPI:
    """The API plus routes that need no database, one of them cached like a real data route."""
    app = create_app(store=MemoryStore(), rate_limit_per_minute=limit)

    @app.get("/v1/sensors/{sensor_id}/where")
    def where(sensor_id: str) -> dict[str, str]:
        return {"sensor": sensor_id}

    @app.get("/v1/model")  # cached for an hour by the middleware; replaces the real route here
    def model() -> dict[str, str]:
        return {"model": "test"}

    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the real /v1/model
    return app


def test_the_real_routes_map_to_their_templates() -> None:
    templates = RouteTemplates(create_app(store=MemoryStore(), rate_limit_per_minute=0))

    assert templates("/v1/health") == "/v1/health"
    assert templates("/v1/readings/latest") == "/v1/readings/latest"
    assert templates("/v1/sensors/pa-27359") == "/v1/sensors/{sensor_id}"
    assert templates("/v1/sensors/pa-27359/forecast") == "/v1/sensors/{sensor_id}/forecast"
    assert templates("/v1/accuracy/forecast") == "/v1/accuracy/forecast"
    assert templates("/metrics") == "/metrics"
    assert templates("/v1/sensors/pa-1/forecast/extra") == "unmatched"
    assert templates("/openapiXjson") == "unmatched"  # a dot in a path is not a wildcard


def test_requests_are_counted_by_route_template_not_by_url() -> None:
    client = TestClient(app_with_test_routes())

    client.get("/v1/sensors/pa-1/where")
    client.get("/v1/sensors/pa-2/where")
    client.get("/no/such/page")

    samples = scrape(client)
    assert requests(samples, method="GET", route="/v1/sensors/{sensor_id}/where", status="200") == 2
    assert requests(samples, method="GET", route="unmatched", status="404") == 1
    assert not any("pa-1" in json.dumps(sorted(labels)) for _, labels in samples)


def test_request_times_are_recorded() -> None:
    client = TestClient(app_with_test_routes())

    client.get("/v1/sensors/pa-1/where")

    samples = scrape(client)
    count = (
        "airsight_api_request_duration_seconds_count",
        frozenset({"method": "GET", "route": "/v1/sensors/{sensor_id}/where"}.items()),
    )
    assert samples[count] == 1


def test_cache_hits_and_misses_are_counted() -> None:
    client = TestClient(app_with_test_routes())

    client.get("/v1/model")
    client.get("/v1/model")
    client.get("/v1/model")

    samples = scrape(client)
    assert samples[("airsight_api_cache_total", frozenset({"result": "miss"}.items()))] == 1
    assert samples[("airsight_api_cache_total", frozenset({"result": "hit"}.items()))] == 2
    # A cache hit never reaches the route, but is still counted under it
    assert requests(samples, method="GET", route="/v1/model", status="200") == 3


def test_refused_requests_are_counted_and_metrics_are_never_refused() -> None:
    client = TestClient(app_with_test_routes(limit=1))

    client.get("/v1/sensors/pa-1/where")
    client.get("/v1/sensors/pa-1/where")
    client.get("/metrics")

    samples = scrape(client)  # over the limit by now, and still answered
    assert requests(samples, method="GET", route="/v1/sensors/{sensor_id}/where", status="429") == 1


def test_metrics_stay_out_of_the_public_contract() -> None:
    schema = create_app(store=MemoryStore(), rate_limit_per_minute=0).openapi()

    assert "/metrics" not in schema["paths"]


def test_each_app_starts_from_zero() -> None:
    first = TestClient(app_with_test_routes())
    first.get("/v1/sensors/pa-1/where")

    second = TestClient(app_with_test_routes())

    route = "/v1/sensors/{sensor_id}/where"
    assert requests(scrape(second), method="GET", route=route, status="200") == 0
