import json
import logging
import sys
from datetime import UTC, datetime

import httpx2
import pytest
from pydantic import SecretStr

from airsight.core.logging import (
    HANDLER_NAME,
    JsonFormatter,
    configure_logging,
    current_task,
    request_id,
)
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


def record(message: str = "Loaded %d rows", *args: object, **extra: object) -> logging.LogRecord:
    entry = logging.LogRecord("airsight.test", logging.INFO, __file__, 1, message, args, None)
    entry.__dict__.update(extra)
    return entry


def test_each_line_is_one_json_object_with_its_extras() -> None:
    line = JsonFormatter().format(record("Loaded %d rows", 42, rows=42, color_message="\x1b[36m"))

    entry = json.loads(line)
    assert entry["level"] == "INFO"
    assert entry["logger"] == "airsight.test"
    assert entry["message"] == "Loaded 42 rows"
    assert entry["rows"] == 42
    assert entry["time"].endswith("+00:00")
    assert "request_id" not in entry and "task" not in entry
    assert "color_message" not in entry  # uvicorn's copy with terminal colours


def test_lines_carry_the_request_and_the_task_they_belong_to() -> None:
    request_token = request_id.set("req-1")
    task_token = current_task.set(("airsight.ingest_live", "task-1"))
    try:
        entry = json.loads(JsonFormatter().format(record()))
    finally:
        request_id.reset(request_token)
        current_task.reset(task_token)

    assert entry["request_id"] == "req-1"
    assert (entry["task"], entry["task_id"]) == ("airsight.ingest_live", "task-1")


def test_errors_keep_their_traceback() -> None:
    try:
        raise ValueError("bad row")
    except ValueError:
        entry = record("Failed")
        entry.exc_info = sys.exc_info()

    parsed = json.loads(JsonFormatter().format(entry))

    assert "ValueError: bad row" in parsed["exception"]


def test_configuring_twice_keeps_one_handler_and_leaves_others_alone() -> None:
    other = logging.NullHandler()
    logging.getLogger().addHandler(other)
    try:
        configure_logging(log_format="text")
        configure_logging(log_format="json")

        handlers = logging.getLogger().handlers
        ours = [h for h in handlers if h.get_name() == HANDLER_NAME]
        assert len(ours) == 1
        assert isinstance(ours[0].formatter, JsonFormatter)
        assert other in handlers
    finally:
        logging.getLogger().removeHandler(other)


def test_text_format_for_reading_in_a_terminal() -> None:
    configure_logging(log_format="text")

    ours = [h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME]
    assert not isinstance(ours[0].formatter, JsonFormatter)
    configure_logging(log_format="json")
