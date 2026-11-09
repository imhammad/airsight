"""Rate limiting and response caching, both kept in the store (Redis in production).

If Redis is down, both fail open: requests are answered, just without a cache or a limit.
An outage of a helper should never become an outage of the API.
"""

import contextlib
import logging
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode

from fastapi import Request, Response
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from airsight.api.problems import problem
from airsight.api.store import Store
from airsight.core.cache import CACHE_PREFIX

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
UNLIMITED_PATHS = {"/v1/health"}  # health checks must never be throttled

# How long each kind of answer stays fresh (ADR 0008)
LATEST_TTL = 5 * 60  # new corrections land at most every 3 hours
PAST_TTL = 60 * 60  # the past only changes if we backfill
MODEL_TTL = 60 * 60  # cleared on promotion
ACCURACY_TTL = 15 * 60
COORDINATE_DECIMALS = 3  # about 100 m


class RateLimitMiddleware(BaseHTTPMiddleware):
    """At most `limit` requests per client IP per minute, counted in fixed one-minute windows."""

    def __init__(
        self, app: ASGIApp, store: Store, limit: int, clock: Callable[[], float] = time.time
    ) -> None:
        super().__init__(app)
        self.store, self.limit, self.clock = store, limit, clock

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self.limit <= 0 or request.url.path in UNLIMITED_PATHS:
            return await call_next(request)
        now = self.clock()
        window = int(now // WINDOW_SECONDS)
        reset = WINDOW_SECONDS - int(now % WINDOW_SECONDS)
        client = request.client.host if request.client else "unknown"
        try:
            count = await self.store.incr(f"ratelimit:{client}:{window}", WINDOW_SECONDS)
        except RedisError:
            logger.warning("Rate limit store unavailable; serving without a limit")
            return await call_next(request)

        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(max(self.limit - count, 0)),
            "RateLimit-Reset": str(reset),
        }
        if count > self.limit:
            detail = f"More than {self.limit} requests a minute; try again in {reset} seconds"
            return problem(429, detail, headers={**headers, "Retry-After": str(reset)})
        response = await call_next(request)
        response.headers.update(headers)
        return response


def normalized_query(query: str) -> str:
    """Sorted parameters, coordinates rounded, so nearby and reordered requests share an entry."""
    params = []
    for name, value in parse_qsl(query, keep_blank_values=True):
        if name in ("lat", "lon"):
            with contextlib.suppress(ValueError):  # left as is; validation rejects it
                value = f"{float(value):.{COORDINATE_DECIMALS}f}"
        params.append((name, value))
    return urlencode(sorted(params))


def cache_ttl(path: str, query: str, now: datetime) -> int | None:
    """Seconds an answer to this request stays fresh, or None if it isn't cached."""
    if path in ("/v1/readings/nearest", "/v1/sensors") or re.fullmatch(r"/v1/sensors/[^/]+", path):
        return LATEST_TTL
    if re.fullmatch(r"/v1/sensors/[^/]+/history", path):
        try:
            end = datetime.fromisoformat(dict(parse_qsl(query))["end"])
        except (KeyError, ValueError):
            return None  # validation will reject it
        today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return PAST_TTL if end.tzinfo is not None and end <= today else LATEST_TTL
    if path == "/v1/model":
        return MODEL_TTL
    if path == "/v1/accuracy":
        return ACCURACY_TTL
    return None


class CacheMiddleware(BaseHTTPMiddleware):
    """Serve repeated GETs from the store, with a Cache-Control header that matches."""

    def __init__(self, app: ASGIApp, store: Store, clock: Callable[[], float] = time.time) -> None:
        super().__init__(app)
        self.store, self.clock = store, clock

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "GET":
            return await call_next(request)
        query = normalized_query(request.url.query)
        now = self.clock()
        ttl = cache_ttl(request.url.path, query, datetime.fromtimestamp(now, UTC))
        if ttl is None:
            return await call_next(request)
        # The route sees the normalized query too, so every client sharing an entry gets
        # exactly the answer the entry holds
        request.scope["query_string"] = query.encode()
        key = f"{CACHE_PREFIX}{request.url.path}?{query}"

        try:
            cached = await self.store.get(key)
        except RedisError:
            logger.warning("Cache unavailable; serving without it")
            return await call_next(request)
        if cached is not None:
            expires, body = cached.split(b"\n", 1)
            max_age = max(math.ceil(float(expires) - now), 0)
            return Response(
                body,
                media_type="application/json",
                headers={"Cache-Control": f"public, max-age={max_age}", "X-Cache": "HIT"},
            )

        response = await call_next(request)
        if response.status_code != 200:
            return response  # errors are never cached
        body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
        try:
            await self.store.set(key, f"{now + ttl}\n".encode() + body, ttl)
        except RedisError:
            logger.warning("Cache unavailable; response not stored")
        headers = dict(response.headers)
        headers.update({"Cache-Control": f"public, max-age={ttl}", "X-Cache": "MISS"})
        return Response(body, status_code=200, headers=headers)
