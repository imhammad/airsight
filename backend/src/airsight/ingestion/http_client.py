"""Shared HTTP behaviour for every external API: timeouts, retries and backoff."""

import random
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx2

# Worth retrying: rate limits and temporary server problems. Anything else (bad key, bad
# request) will fail the same way again, so it's raised immediately.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_WAIT_SECONDS = 60.0


def create_client(timeout_seconds: float) -> httpx2.Client:
    return httpx2.Client(
        timeout=timeout_seconds,
        headers={"User-Agent": "AirSight (+https://github.com/imhammad/airsight)"},
    )


def get_json(
    client: httpx2.Client,
    url: str,
    *,
    params: Mapping[str, str | int | float] | None = None,
    headers: Mapping[str, str] | None = None,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET a URL and return the parsed JSON, retrying temporary failures with backoff."""
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx2.HTTPError as error:
            if attempt == attempts or not is_retryable(error):
                raise
            sleep(wait_seconds(attempt, error))
    raise AssertionError("unreachable")


def is_retryable(error: httpx2.HTTPError) -> bool:
    if isinstance(error, httpx2.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUS_CODES
    # Timeouts and connection failures
    return isinstance(error, httpx2.TransportError)


def wait_seconds(attempt: int, error: httpx2.HTTPError) -> float:
    """Exponential backoff with jitter, or the server's Retry-After when it sends one."""
    if isinstance(error, httpx2.HTTPStatusError):
        retry_after = error.response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), MAX_WAIT_SECONDS)
    backoff: float = 2.0**attempt
    return min(backoff + random.uniform(0, 1), MAX_WAIT_SECONDS)
