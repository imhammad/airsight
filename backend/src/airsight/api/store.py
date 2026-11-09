"""Where the API keeps cached responses and rate-limit counters: Redis, or memory in tests."""

import time
from collections.abc import Callable
from typing import Protocol

import redis.asyncio


class Store(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...

    async def incr(self, key: str, ttl_seconds: int) -> int:
        """Add one to a counter that expires ttl_seconds after it was created."""
        ...


class RedisStore:
    def __init__(self, url: str) -> None:
        # Short timeouts: a slow cache must never make the API slow
        self._redis = redis.asyncio.Redis.from_url(
            url, socket_timeout=0.5, socket_connect_timeout=0.5
        )

    async def get(self, key: str) -> bytes | None:
        value = await self._redis.get(key)
        return value.encode() if isinstance(value, str) else value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def incr(self, key: str, ttl_seconds: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl_seconds, nx=True)  # only when the counter is new
            count, _ = await pipe.execute()
        return int(count)


class MemoryStore:
    """The same behaviour in a dict, for tests and for running the API without Redis."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._values: dict[str, tuple[bytes, float]] = {}

    def _live(self, key: str) -> bytes | None:
        entry = self._values.get(key)
        if entry is None or entry[1] <= self._clock():
            self._values.pop(key, None)
            return None
        return entry[0]

    async def get(self, key: str) -> bytes | None:
        return self._live(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        self._values[key] = (value, self._clock() + ttl_seconds)

    async def incr(self, key: str, ttl_seconds: int) -> int:
        current = self._live(key)
        count = int(current or 0) + 1
        expires = self._values[key][1] if current is not None else self._clock() + ttl_seconds
        self._values[key] = (str(count).encode(), expires)
        return count
