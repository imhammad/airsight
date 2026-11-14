# AirSight API

AirSight's public API serves corrected PM2.5 for low-cost sensors in the San Francisco Bay Area.
Every value comes from a registered model, and the API says which one. The rules behind it are in
[ADR 0008](adr/0008-public-api-design.md). The machine-readable contract is
[openapi.json](openapi.json), and a running API shows interactive docs at `/docs`.

- **Base URL (local):** `http://localhost:8000/v1`
- **Format:** JSON, `snake_case` fields, missing values are `null` (never left out)
- **Access:** read-only and public, no key needed, 60 requests a minute per IP

## Endpoints

| Method and path | Returns |
|---|---|
| `GET /v1/health` | service status and version |
| `GET /v1/sensors?limit=&cursor=` | every sensor we serve, paginated |
| `GET /v1/sensors/{sensor_id}` | one sensor and its latest reading |
| `GET /v1/sensors/{sensor_id}/history?start=&end=` | hourly readings, oldest first, at most 31 days |
| `GET /v1/sensors/{sensor_id}/forecast` | PM2.5 for the next 24 hours, with a likely range |
| `GET /v1/readings/latest?limit=&cursor=` | every sensor with its latest reading, for a map |
| `GET /v1/readings/nearest?lat=&lon=&radius_km=&limit=` | latest readings of the closest healthy sensors |
| `GET /v1/model` | the model behind every value, and its final-test results |
| `GET /v1/accuracy?days=` | live error against official monitors, per station |
| `GET /v1/accuracy/forecast?days=` | live error of the forecast, by hours ahead and station |

### Readings near a place

```
curl "http://localhost:8000/v1/readings/nearest?lat=37.8716&lon=-122.2727&limit=1"
```
```json
{
  "data": [
    {
      "sensor": {
        "id": "pa-27359",
        "name": "Oceanview Neighborhood Assn",
        "latitude": 37.87204,
        "longitude": -122.30109,
        "health": "ok"
      },
      "distance_km": 2.5,
      "reading": {
        "pm25": 9.1,
        "source": "corrected",
        "pm25_corrected": 9.1,
        "pm25_raw": 9.9,
        "aqi_category": "moderate",
        "model_version": "airsight-correction/1",
        "observed_at": "2026-11-07T05:00:00Z",
        "stale": false
      }
    }
  ],
  "next_cursor": null
}
```

| Parameter | Default | Allowed |
|---|---|---|
| `lat`, `lon` | required | degrees, rounded to 3 decimals (about 100 m) |
| `radius_km` | 10 | above 0, at most 50 |
| `limit` | 5 | 1 to 20 |

Only healthy sensors are returned, nearest first.

### Every sensor, for a map

`/v1/readings/latest` returns every sensor we serve, each shaped like `/v1/sensors/{sensor_id}`,
so a map needs one request instead of one per sensor. `limit` is 200 by default here, so today
the whole network fits on one page; follow `next_cursor` anyway. Excluded sensors are included
with `"latest_reading": null`, so a map can show them as out of service.

### Sensors

Sensor ids never change. They are built from the source, so `pa-27359` is PurpleAir sensor 27359.
We serve the PurpleAir sensors within 1 km of an official monitor. A sensor the quality checks
found unreliable is listed with `"health": "excluded"` and has no reading
(`"latest_reading": null`).

### History

`start` is included and `end` is not. Both need a time zone, such as `2026-11-01T00:00:00Z` or
`2026-10-31T17:00:00-07:00`. A time without one is rejected rather than guessed.

```
curl "http://localhost:8000/v1/sensors/pa-27359/history?start=2026-11-06T00:00:00Z&end=2026-11-07T00:00:00Z"
```

### Forecast

Every 3 hours we forecast the next 24 hours for each healthy sensor, from its recent readings,
the official monitor next to it and the day-ahead weather forecast ([ADR 0012](adr/0012-forecast-design.md)).

```
curl "http://localhost:8000/v1/sensors/pa-27359/forecast"
```

Each hour has `p50`, the most likely PM2.5, and a likely range from `p10` to `p90`: on the final
test the true value fell inside it 79% of the time. `issued_at` is the last hour of data the
forecast used, so `hours_ahead` 1 is the hour after it. `aqi_category` follows `p50`.
`outside_experience: true` means the air is dirtier than any the model was trained on (above
35.4 µg/m³, such as wildfire smoke): the range is widened, and the forecast deserves less trust.
`stale` is `true` when the newest forecast is more than 6 hours old. `monitor_offline` is
`true` when the official monitor next to the sensor had no reading in the 3 hours before
`issued_at` (an AirNow outage, for example): the forecast then rests on the sensor and the
weather alone. On the final test that made it about 7% less accurate (MAE 2.88 against 2.69),
and the range still held the real value 78% of the time. Excluded sensors, and sensors
not forecast yet, return 404 `No forecast for sensor ...`.

### Model and accuracy

`/v1/model` names the champion model, the dataset it was trained on, `trained_before` (the model
never saw hours from then on) and its final-test result. The final test is the mean of the
per-station errors over 14 days (ADR 0007).

`/v1/accuracy?days=7` scores the stored corrections against the official monitors over recent
days (1 to 30). It only counts hours after `trained_before`, so it is always an out-of-sample
score. For each station it reports the mean absolute error (MAE) of the corrected value, the raw
sensor and the EPA's US-wide correction, plus the corrected value's bias (positive means it reads
high), and `source`: what the sensors next to that station show right now (ADR 0010).

`/v1/accuracy/forecast?days=7` scores the stored forecasts whose hour fell in the last days
(1 to 30) against what the monitor then read. A forecast is always issued before its hour, so
this is out of sample too. It reports the MAE of `p50` next to the two baselines of ADR 0012
(`persistence`: the monitor's reading when the forecast was issued; `same_hour_yesterday`), all
three on exactly the same hours, plus `coverage`: the share of hours inside the `p10` to `p90`
range, which should be near 0.8. Each is averaged per station first, overall (`headline_mae`)
and for 1 to 6, 7 to 12 and 13 to 24 hours ahead (`by_horizon`). Only the newest forecast model
is scored; `model_version` is `null` until a forecast has an hour to score.

## Readings

| Field | Meaning |
|---|---|
| `pm25` | the PM2.5 to show, in µg/m³: the value `source` names |
| `source` | `corrected`, or `raw` where the correction has been less accurate (below) |
| `pm25_corrected` | corrected PM2.5 in µg/m³, one decimal |
| `pm25_raw` | the sensor's own reading (mean of its two channels) in µg/m³ |
| `aqi_category` | US EPA category of `pm25`, 2024 breakpoints (below) |
| `model_version` | the model that produced the value, such as `airsight-correction/1` |
| `observed_at` | start of the hour, UTC |
| `stale` | `true` when the reading is more than 6 hours old (two missed ingestions) |

| Category | PM2.5 (µg/m³) |
|---|---|
| `good` | up to 9.0 |
| `moderate` | 9.1 to 35.4 |
| `unhealthy_sensitive` | 35.5 to 55.4 |
| `unhealthy` | 55.5 to 125.4 |
| `very_unhealthy` | 125.5 to 225.4 |
| `hazardous` | above 225.4 |

The category follows the rounded value, so the number and the category always agree.

### Corrected or raw

Every 3 hours, each official monitor's last 14 days are scored. Where the corrections were
further from the monitor than the sensors' own readings, over at least 200 hours, the sensors
next to that monitor show raw (`source: "raw"`, and `pm25` equals `pm25_raw`). They switch back
on their own once the correction wins again. The rule and its reasons are in
[ADR 0010](adr/0010-raw-fallback.md).

## Pagination

Lists are `{"data": [...], "next_cursor": "..."}`. Pass `next_cursor` back as `cursor` to get the
next page, until it is `null`. `limit` is 50 by default and at most 200. Cursors are opaque and
stay valid when sensors are added, so pages never skip or repeat a sensor.

## Errors

Every error is Problem Details ([RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)) with content
type `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "No sensor with id pa-0"
}
```

| Status | When |
|---|---|
| 400 | a cursor this API did not return |
| 404 | no sensor with this id, or no such path |
| 422 | invalid parameters; `errors` lists each field and why |
| 429 | over the rate limit; wait `Retry-After` seconds |
| 500 | unexpected server error (details are logged, never returned) |
| 503 | no model has been promoted yet |

## Caching

Answers change at most every 3 hours, so responses are cached in Redis and carry `Cache-Control`
and `X-Cache: HIT` or `MISS`:

| Data | Fresh for |
|---|---|
| latest readings, nearest, sensor list, forecasts | 5 minutes |
| history ending before today (UTC) | 1 hour |
| model | 1 hour, cleared when a new model is promoted |
| accuracy and forecast accuracy | 15 minutes |

Coordinates are rounded to 3 decimals before the query runs, so two people 50 m apart share one
cached answer.

## Rate limits

60 requests per minute per client IP, in fixed one-minute windows. Every response carries
`RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset` (seconds until the window resets).
Over the limit, the API answers 429 with `Retry-After`. `/v1/health` is never limited. The limit
is the `RATE_LIMIT_PER_MINUTE` setting.

The client IP comes from the connection, or from `X-Forwarded-For` only when the request comes
through a proxy we trust. Uvicorn trusts only the addresses in `FORWARDED_ALLOW_IPS` (by default
just 127.0.0.1), so a client can't dodge the limit by sending a made-up header. In production
(Phase 9) this is set to the load balancer's address.

If Redis is unavailable, the API keeps answering without the cache and without the limit.

## Compatibility

Within `/v1`, changes are additive only: new endpoints, new optional parameters and new fields.
Renaming or removing anything means `/v2`. Clients should ignore fields they don't know.

One exception, before v1.0.0 and while the web app was the only client: in v0.5.0
`aqi_category` started following the new `pm25` field instead of `pm25_corrected`
(ADR 0010). For sensors showing corrected readings nothing changed.

[openapi.json](openapi.json) is generated from the code. A test fails when the code and the
file disagree, so every API change appears as a diff of that file in its pull request, where
reviewers check that it is additive. After changing the API, regenerate it from `backend/`:

```
uv run python -m airsight.api.openapi
```

## Performance

`python -m airsight.api.loadtest` measures `/v1/readings/nearest` under load, with two kinds of
traffic: `cached` (a few popular places, like real traffic) and `uncached` (a random place every
time, so every request reaches PostgreSQL). Raise the rate limit first:

```
RATE_LIMIT_PER_MINUTE=1000000 docker compose up -d --wait api
cd backend
uv run python -m airsight.api.loadtest --traffic uncached
uv run python -m airsight.api.loadtest --traffic cached
cd ..
docker compose up -d --wait api
```

Measured on 2026-11-09 on a MacBook Air M5 (16 GB) with Docker Desktop, 20 concurrent clients
for 30 seconds each:

| Traffic | Requests a second | p50 | p95 | p99 | Cache hits |
|---|---|---|---|---|---|
| uncached | 920 | 20.9 ms | 28.1 ms | 51.5 ms | 2% |
| cached | 3,241 | 6.0 ms | 7.2 ms | 9.9 ms | 100% |

Every request returned 200. Uncached traffic still gets a few hits, because two random places
sometimes round to the same 100 m cell. The API, the database and the load test shared one
laptop, so these are local numbers; production numbers come with deployment (Phase 9).
