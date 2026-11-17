"""Prometheus metrics for the API, served at /metrics (ADR 0013).

Only what the API alone can see: each request's route, status and time, and whether the cache
answered it. Freshness, jobs and model accuracy come from the exporter, which reads the database.
"""

import re
import time
from importlib.metadata import version

from fastapi import FastAPI
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    GCCollector,
    Histogram,
    Info,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PATH = "/metrics"
# A path no route matches gets one label, so a scanner trying random URLs can't create
# thousands of time series
UNMATCHED = "unmatched"
# Most answers take a few milliseconds from the cache, the slowest uncached ones under a second
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


class ApiMetrics:
    """The API's metrics, in their own registry so every app (and every test) starts at zero."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        # Memory, CPU and open files of the API process; garbage collection; Python version
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        GCCollector(registry=self.registry)
        Info("airsight_api", "The running API", registry=self.registry).info(
            {"version": version("airsight")}
        )
        self.requests = Counter(
            "airsight_api_requests",
            "Requests answered, by route template and status code",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "airsight_api_request_duration_seconds",
            "Time to answer a request, until its last byte is sent",
            ["method", "route"],
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.cache = Counter(
            "airsight_api_cache",
            "Cacheable requests, by whether the cache answered (hit) or not (miss)",
            ["result"],
            registry=self.registry,
        )

    def endpoint(self, request: Request) -> Response:
        return Response(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)


def pattern(template: str) -> re.Pattern[str]:
    """/v1/sensors/{sensor_id} matches /v1/sensors/pa-1 and nothing longer."""
    parts = re.split(r"\{[^/}]+\}", template)
    return re.compile("[^/]+".join(re.escape(part) for part in parts) + "$")


class RouteTemplates:
    """Turns a URL path into its route template, such as /v1/sensors/{sensor_id}.

    Built from the OpenAPI paths (public and stable) plus the app's own plain routes such as
    /metrics, the first time it is needed, when every route has been added.
    """

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.patterns: list[tuple[re.Pattern[str], str]] | None = None

    def build(self) -> list[tuple[re.Pattern[str], str]]:
        templates = set(self.app.openapi()["paths"])
        templates |= {
            path
            for r in self.app.router.routes
            if isinstance(path := getattr(r, "path", None), str)
        }
        # Fixed paths before ones with parameters, so /v1/readings/latest never reads as /{id}
        ordered = sorted(templates, key=lambda t: (t.count("{"), -len(t)))
        return [(pattern(t), t) for t in ordered]

    def __call__(self, path: str) -> str:
        if self.patterns is None:
            self.patterns = self.build()
        return next((t for pattern, t in self.patterns if pattern.match(path)), UNMATCHED)


class MetricsMiddleware:
    """Counts and times every request, including those answered by the cache or refused.

    It works out the route from the path rather than waiting for routing, because a cache hit
    or a 429 is answered before the request reaches a route.
    """

    def __init__(self, app: ASGIApp, metrics: ApiMetrics, templates: RouteTemplates) -> None:
        self.app, self.metrics, self.templates = app, metrics, templates

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method, route = scope["method"], self.templates(scope["path"])
        started = time.perf_counter()
        status = 500  # what the client gets if the app raises before answering

        async def record(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                for name, value in message.get("headers", []):
                    if name.lower() == b"x-cache":
                        self.metrics.cache.labels(value.decode("latin-1").lower()).inc()
            await send(message)

        try:
            await self.app(scope, receive, record)
        finally:
            self.metrics.duration.labels(method, route).observe(time.perf_counter() - started)
            self.metrics.requests.labels(method, route, str(status)).inc()
