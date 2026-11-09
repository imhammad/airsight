import random

from airsight.api.loadtest import BAY_AREA, POPULAR, Results, place, report


def test_cached_traffic_repeats_popular_places() -> None:
    rng = random.Random(0)

    assert {place("cached", rng) for _ in range(100)} == set(POPULAR)


def test_uncached_traffic_spreads_over_the_bay_area() -> None:
    rng = random.Random(0)
    (lat_min, lat_max), (lon_min, lon_max) = BAY_AREA

    places = [place("uncached", rng) for _ in range(100)]

    assert len(set(places)) == 100
    assert all(lat_min <= lat <= lat_max and lon_min <= lon <= lon_max for lat, lon in places)


def test_report_shows_percentiles_and_cache_hits() -> None:
    results = Results(latencies_ms=[float(ms) for ms in range(1, 101)])
    results.statuses[200] = 100
    results.cache["HIT"] = 75

    text = report(results, "cached", clients=5, seconds=10)

    assert "requests  100 (10 per second)" in text
    assert "p50 50.5 ms, p95 96.0 ms" in text
    assert "75% hits" in text
