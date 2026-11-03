import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from airsight.ingestion.airnow import AirNowClient, AirNowError
from airsight.ingestion.regions import BAY_AREA

FIXTURES = Path(__file__).parent / "fixtures"
KEY = SecretStr("secret-test-key")
START = datetime(2026, 11, 1, 12, tzinfo=UTC)
END = datetime(2026, 11, 1, 13, tzinfo=UTC)


def client_serving(status: int, body: Any) -> tuple[AirNowClient, list[httpx2.Request]]:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(status, json=body)

    transport = httpx2.MockTransport(handler)
    return AirNowClient(httpx2.Client(transport=transport), KEY), requests


def observation(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Latitude": 37.7658,
        "Longitude": -122.3978,
        "UTC": "2026-11-01T12:00",
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": 8.1,
        "RawConcentration": 7.4,
        "AQI": 34,
        "Category": 1,
        "SiteName": "San Francisco",
        "AgencyName": "San Francisco Bay Area AQMD",
        "FullAQSCode": "840060750005",
        "IntlAQSCode": "840060750005",
    }
    return row | overrides


def test_parses_raw_hourly_concentration_in_utc() -> None:
    client, requests = client_serving(200, [observation()])

    [reading] = client.hourly_pm25(BAY_AREA, START, END)

    assert reading.station_id == "840060750005"
    assert reading.time == datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert reading.pm25 == 7.4  # the measured hour, not the NowCast Value
    params = requests[0].url.params
    assert params["startDate"] == "2026-11-01T12"
    assert params["BBOX"] == "-123.0,37.2,-121.6,38.3"


def test_skips_missing_values() -> None:
    client, _ = client_serving(200, [observation(RawConcentration=-999.0), observation()])

    assert len(client.hourly_pm25(BAY_AREA, START, END)) == 1


def test_errors_never_reveal_the_key() -> None:
    client, _ = client_serving(401, {"error": "invalid key"})

    with pytest.raises(AirNowError) as caught:
        client.hourly_pm25(BAY_AREA, START, END)

    assert "secret-test-key" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_parses_recorded_response() -> None:
    body = json.loads((FIXTURES / "airnow_bay_area.json").read_text())
    client, _ = client_serving(200, body)

    readings = client.hourly_pm25(BAY_AREA, START, END)

    assert len(readings) > 0
    assert all(r.time.tzinfo == UTC for r in readings)
    assert all(37.2 <= r.latitude <= 38.3 for r in readings)
    assert all(r.pm25 > -999 for r in readings)
    assert len({r.station_id for r in readings}) >= 5  # many monitors, not one
