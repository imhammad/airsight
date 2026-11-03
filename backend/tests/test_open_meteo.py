import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2

from airsight.ingestion.open_meteo import OpenMeteoClient, Point

FIXTURES = Path(__file__).parent / "fixtures"
SAN_FRANCISCO = Point(37.77, -122.42)
SAN_JOSE = Point(37.34, -121.89)


def client_serving(body: Any) -> tuple[OpenMeteoClient, list[httpx2.Request]]:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=body)

    return OpenMeteoClient(httpx2.Client(transport=httpx2.MockTransport(handler))), requests


def location(times: list[int], humidity: list[float | None]) -> dict[str, Any]:
    n = len(times)
    return {
        "hourly": {
            "time": times,
            "temperature_2m": [15.0] * n,
            "relative_humidity_2m": humidity,
            "wind_speed_10m": [10.0] * n,
            "wind_direction_10m": [270.0] * n,
            "precipitation": [0.0] * n,
        }
    }


def test_single_point_is_parsed_with_utc_times() -> None:
    client, requests = client_serving(location([1767268800, 1767272400], [80.0, None]))

    result = client.recent([SAN_FRANCISCO])

    hours = result[SAN_FRANCISCO]
    assert [h.time for h in hours] == [
        datetime(2026, 1, 1, 12, tzinfo=UTC),
        datetime(2026, 1, 1, 13, tzinfo=UTC),
    ]
    assert [h.relative_humidity for h in hours] == [80.0, None]  # gaps stay gaps
    assert requests[0].url.params["timeformat"] == "unixtime"


def test_several_points_keep_their_order() -> None:
    body = [location([1767268800], [50.0]), location([1767268800], [90.0])]
    client, requests = client_serving(body)

    result = client.recent([SAN_FRANCISCO, SAN_JOSE])

    assert result[SAN_FRANCISCO][0].relative_humidity == 50.0
    assert result[SAN_JOSE][0].relative_humidity == 90.0
    assert requests[0].url.params["latitude"] == "37.77,37.34"


def test_no_points_means_no_request() -> None:
    client, requests = client_serving([])

    assert client.recent([]) == {}
    assert requests == []


def test_parses_recorded_response() -> None:
    body = json.loads((FIXTURES / "open_meteo_two_points.json").read_text())
    client, _ = client_serving(body)

    result = client.recent([SAN_FRANCISCO, SAN_JOSE])

    for hours in result.values():
        assert len(hours) == 72  # 2 past days + today, hourly
        times = [h.time for h in hours]
        assert times == sorted(times)
        assert all(t.utcoffset() == timedelta(0) for t in times)  # UTC
        assert all(
            0 <= h.relative_humidity <= 100 for h in hours if h.relative_humidity is not None
        )
