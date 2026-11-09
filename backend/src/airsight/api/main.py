import time
from collections.abc import Callable
from importlib.metadata import version

from fastapi import FastAPI

from airsight.api import problems
from airsight.api.middleware import CacheMiddleware, RateLimitMiddleware
from airsight.api.routes import health, model, readings, sensors
from airsight.api.store import RedisStore, Store
from airsight.core.config import get_settings


def create_app(
    store: Store | None = None,
    rate_limit_per_minute: int | None = None,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    """The API. Tests pass a MemoryStore, and rate_limit_per_minute=0 to turn the limit off."""
    settings = get_settings()
    store = store or RedisStore(settings.redis_url)
    limit = (
        settings.rate_limit_per_minute if rate_limit_per_minute is None else rate_limit_per_minute
    )

    app = FastAPI(title="AirSight API", version=version("airsight"))
    problems.install(app)
    # The last one added runs first: the rate limit counts every request, cached or not
    app.add_middleware(CacheMiddleware, store=store, clock=clock)
    app.add_middleware(RateLimitMiddleware, store=store, limit=limit, clock=clock)
    app.include_router(health.router, prefix="/v1")
    app.include_router(sensors.router, prefix="/v1")
    app.include_router(readings.router, prefix="/v1")
    app.include_router(model.router, prefix="/v1")
    return app


app = create_app()
