"""Load test the running API: how fast /v1/readings/nearest answers, with and without the cache.

Two kinds of traffic:
  cached    a few popular places asked again and again, which is what real traffic looks like
  uncached  a new random place in the Bay Area every time, so every request reaches PostgreSQL

Raise the rate limit first, or almost every request gets 429 (see docs/API.md, Performance):
    RATE_LIMIT_PER_MINUTE=1000000 docker compose up -d --wait api
    uv run python -m airsight.api.loadtest --traffic uncached
"""

import argparse
import asyncio
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field

import httpx2

# Downtown San Francisco, Oakland, Berkeley, San Jose and Vallejo
POPULAR = [
    (37.7793, -122.4193),
    (37.8044, -122.2712),
    (37.8716, -122.2727),
    (37.3382, -121.8863),
    (38.1041, -122.2566),
]
BAY_AREA = ((37.30, 38.10), (-122.60, -121.80))  # latitude and longitude ranges


@dataclass
class Results:
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter[int] = field(default_factory=Counter)
    cache: Counter[str] = field(default_factory=Counter)


def place(traffic: str, rng: random.Random) -> tuple[float, float]:
    if traffic == "cached":
        return rng.choice(POPULAR)
    (lat_min, lat_max), (lon_min, lon_max) = BAY_AREA
    return rng.uniform(lat_min, lat_max), rng.uniform(lon_min, lon_max)


async def client_loop(
    client: httpx2.AsyncClient, traffic: str, deadline: float, seed: int, results: Results
) -> None:
    rng = random.Random(seed)
    while time.perf_counter() < deadline:
        lat, lon = place(traffic, rng)
        started = time.perf_counter()
        response = await client.get("/v1/readings/nearest", params={"lat": lat, "lon": lon})
        results.latencies_ms.append((time.perf_counter() - started) * 1000)
        results.statuses[response.status_code] += 1
        results.cache[response.headers.get("X-Cache", "none")] += 1


async def run(base_url: str, traffic: str, clients: int, seconds: float) -> Results:
    results = Results()
    limits = httpx2.Limits(max_connections=clients)
    async with httpx2.AsyncClient(base_url=base_url, limits=limits, timeout=30) as client:
        deadline = time.perf_counter() + seconds
        await asyncio.gather(
            *(client_loop(client, traffic, deadline, seed, results) for seed in range(clients))
        )
    return results


def report(results: Results, traffic: str, clients: int, seconds: float) -> str:
    latencies = results.latencies_ms
    cuts = statistics.quantiles(latencies, n=100)
    hits = results.cache["HIT"] / max(len(latencies), 1)
    return "\n".join(
        [
            f"traffic {traffic}, {clients} clients, {seconds:.0f} s",
            f"requests  {len(latencies)} ({len(latencies) / seconds:.0f} per second)",
            f"latency   p50 {cuts[49]:.1f} ms, p95 {cuts[94]:.1f} ms, p99 {cuts[98]:.1f} ms, "
            f"max {max(latencies):.1f} ms",
            f"statuses  {dict(sorted(results.statuses.items()))}",
            f"cache     {hits:.0%} hits",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--traffic", choices=["cached", "uncached"], default="cached")
    parser.add_argument("--clients", type=int, default=20, help="concurrent clients")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    results = asyncio.run(run(args.url, args.traffic, args.clients, args.seconds))
    print(report(results, args.traffic, args.clients, args.seconds))


if __name__ == "__main__":
    main()
