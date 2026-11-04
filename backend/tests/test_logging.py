import logging
from datetime import UTC, datetime

import httpx2
import pytest
from pydantic import SecretStr

from airsight.core.logging import configure_logging
from airsight.ingestion.airnow import AirNowClient
from airsight.ingestion.regions import BAY_AREA


def test_request_logs_never_contain_the_airnow_key(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging()
    caplog.set_level(logging.INFO)
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=[]))
    client = AirNowClient(httpx2.Client(transport=transport), SecretStr("secret-test-key"))

    client.hourly_pm25(
        BAY_AREA, datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)
    )

    assert "secret-test-key" not in caplog.text
