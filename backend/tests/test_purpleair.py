import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from airsight.ingestion.purpleair import (
    PointsBudget,
    PointsBudgetExceededError,
    PurpleAirClient,
    call_cost,
)
from airsight.ingestion.regions import BAY_AREA

FIXTURES = Path(__file__).parent / "fixtures"
KEY = SecretStr("secret-test-key")
NOON = datetime(2026, 11, 1, 12, tzinfo=UTC)


def client_serving(
    *bodies: Any, budget: int = 100_000
) -> tuple[PurpleAirClient, list[httpx2.Request]]:
    requests: list[httpx2.Request] = []
    replies = list(bodies)

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=replies.pop(0))

    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return PurpleAirClient(http, KEY, PointsBudget(budget)), requests


def history_body(rows: list[list[Any]]) -> dict[str, Any]:
    # PurpleAir chooses the column order, so it doesn't match the order we asked for
    return {"fields": ["time_stamp", "humidity", "pm2.5_cf_1_a", "pm2.5_cf_1_b"], "data": rows}


def test_cost_is_request_price_plus_fields_per_row() -> None:
    assert call_cost("history", ["pm2.5_cf_1_a", "pm2.5_cf_1_b", "humidity"], rows=24) == 98


def test_history_maps_columns_by_name_and_sorts_by_time() -> None:
    later, earlier = int(NOON.timestamp()) + 3600, int(NOON.timestamp())
    client, requests = client_serving(
        history_body([[later, 60, 5.0, 5.5], [earlier, 55, 4.0, None]])
    )

    readings = client.hourly_readings(1234, NOON, datetime(2026, 11, 1, 14, tzinfo=UTC))

    assert [r.time for r in readings] == [NOON, datetime(2026, 11, 1, 13, tzinfo=UTC)]
    assert readings[0].pm25_a == 4.0
    assert readings[0].pm25_b is None  # a missing channel stays missing
    assert readings[1].humidity == 60
    assert requests[0].headers["X-API-Key"] == "secret-test-key"
    assert "secret-test-key" not in str(requests[0].url)  # the key travels in a header


def test_long_ranges_are_split_into_14_day_requests() -> None:
    client, requests = client_serving(*[history_body([]) for _ in range(3)])

    client.hourly_readings(
        1234, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC)
    )

    assert len(requests) == 3


def test_budget_charges_actual_rows() -> None:
    rows = [[int(NOON.timestamp()) + 3600 * h, 50, 5.0, 5.0] for h in range(24)]
    client, _ = client_serving(history_body(rows))

    client.hourly_readings(1234, NOON, datetime(2026, 11, 2, 12, tzinfo=UTC))

    assert client.budget.spent == 98


def test_refuses_a_call_that_could_exceed_the_budget() -> None:
    client, requests = client_serving(history_body([]), budget=50)

    with pytest.raises(PointsBudgetExceededError):
        client.hourly_readings(1234, NOON, datetime(2026, 11, 2, 12, tzinfo=UTC))
    assert requests == []  # refused before spending anything


def test_parses_recorded_sensors_response() -> None:
    body = json.loads((FIXTURES / "purpleair_sensors.json").read_text())
    client, _ = client_serving(body)

    sensors = client.sensors(BAY_AREA)

    assert len(sensors) > 0
    assert all(isinstance(s.sensor_index, int) for s in sensors)
    assert all(37.2 <= s.latitude <= 38.3 for s in sensors)


def test_parses_recorded_history_response() -> None:
    body = json.loads((FIXTURES / "purpleair_history.json").read_text())
    client, _ = client_serving(body)

    readings = client.hourly_readings(1234, NOON, datetime(2026, 11, 2, 12, tzinfo=UTC))

    assert 0 < len(readings) <= 25
    times = [r.time for r in readings]
    assert times == sorted(times)
    assert all(t.minute == 0 and t.second == 0 for t in times)  # whole hours
    assert any(r.pm25_a is not None for r in readings)
