import time
from collections.abc import Callable
from importlib.metadata import version

from fastapi import FastAPI

from airsight.api import problems
from airsight.api.logging import RequestLogMiddleware
from airsight.api.metrics import PATH as METRICS_PATH
from airsight.api.metrics import ApiMetrics, MetricsMiddleware, RouteTemplates
from airsight.api.middleware import CacheMiddleware, RateLimitMiddleware
from airsight.api.routes import health, model, readings, sensors
from airsight.api.store import RedisStore, Store
from airsight.core.config import get_settings
from airsight.core.logging import configure_logging


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
    # Outside the cache and the limit, so cache hits and refusals are counted and logged too
    metrics = ApiMetrics()
    app.add_middleware(MetricsMiddleware, metrics=metrics, templates=RouteTemplates(app))
    app.add_middleware(RequestLogMiddleware)
    # For Prometheus, not for the public: kept out of the OpenAPI contract, and blocked at the
    # reverse proxy once deployed (ADR 0013)
    app.add_route(METRICS_PATH, metrics.endpoint, include_in_schema=False)
    app.include_router(health.router, prefix="/v1", responses=problems.responses(500))
    # Documented on every data endpoint, replacing FastAPI's default validation error shape
    errors = problems.responses(422, 429, 500)
    for router in (sensors.router, readings.router, model.router):
        app.include_router(router, prefix="/v1", responses=errors)
    return app


configure_logging()
app = create_app()
