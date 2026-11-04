"""Logging setup shared by every command and worker."""

import logging

# httpx2 logs every request URL at INFO level. AirNow puts its API key in the URL,
# so these logs must never be shown.
QUIET_LOGGERS = ("httpx2", "httpcore")


def quiet_request_logs() -> None:
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    quiet_request_logs()
