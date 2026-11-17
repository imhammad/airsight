"""Logging setup shared by every command, the API and the worker (ADR 0013).

Every line is one JSON object, so logs can be searched and one request or task followed from
start to end. LOG_FORMAT=text gives the old one-line format, easier to read in a terminal.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from airsight.core.config import get_settings

# httpx2 logs every request URL at INFO level. AirNow puts its API key in the URL,
# so these logs must never be shown.
QUIET_LOGGERS = ("httpx2", "httpcore")
# Uvicorn sets up its own handlers; ours replace them so its lines are JSON too
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
HANDLER_NAME = "airsight"

# Set for the length of one API request or one Celery task, and added to every line logged then
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
current_task: ContextVar[tuple[str, str] | None] = ContextVar("current_task", default=None)

# Everything a LogRecord carries by itself; anything else came in through `extra=`.
# Uvicorn adds color_message, the message with terminal colour codes: no use in JSON.
STANDARD_FIELDS = set(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
    "color_message",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, message, context, then any extras."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if (rid := request_id.get()) is not None:
            entry["request_id"] = rid
        if (task := current_task.get()) is not None:
            entry["task"], entry["task_id"] = task
        entry.update(
            (key, value) for key, value in vars(record).items() if key not in STANDARD_FIELDS
        )
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def quiet_request_logs() -> None:
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: int | str = logging.INFO, log_format: str | None = None) -> None:
    """Send every log line to stderr in one format. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(HANDLER_NAME)
    use_json = (log_format or get_settings().log_format) == "json"
    handler.setFormatter(JsonFormatter() if use_json else logging.Formatter(TEXT_FORMAT))

    root = logging.getLogger()
    # Replace only our own handler, so a test's capture handler stays in place
    root.handlers = [h for h in root.handlers if h.get_name() != HANDLER_NAME] + [handler]
    root.setLevel(level)
    for name in UVICORN_LOGGERS:
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    # The API logs each request itself, with its ID (api/logging.py)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    quiet_request_logs()
