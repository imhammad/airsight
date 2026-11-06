# ADR 0008: Public API design

- **Status:** Accepted
- **Date:** 2026-11-06
- **Issue:** #67

## Context

AirSight's API is how the web app (Phase 7) and anyone else reads corrected air quality. Once
people build on it, changing a field or an error shape breaks them, so the rules come first.

Facts that shape it: corrections are computed in batches by workers after each ingestion, never
per request (ADR 0005). New data arrives every 3 hours. The API is read-only and public, with no
accounts in v0.4. Every corrected value comes from one registered model version (`@champion`).

## Options

1. **REST with JSON, versioned in the URL** (`/v1/...`): simple, cacheable by URL, matches the
   OpenAPI docs FastAPI generates.
2. **GraphQL:** flexible queries, but harder to cache and rate-limit, and our questions are few
   and fixed.
3. **REST with versions in a header:** cleaner URLs, but harder to try in a browser and easy to
   forget.

## Decision

Option 1, with these rules.

### Resources

| Method and path | Returns |
|---|---|
| `GET /v1/health` | service status and version (exists) |
| `GET /v1/sensors` | all sensors we serve, paginated |
| `GET /v1/sensors/{sensor_id}` | one sensor and its latest reading |
| `GET /v1/sensors/{sensor_id}/history?start=&end=` | hourly readings for a time range (max 31 days) |
| `GET /v1/readings/nearest?lat=&lon=&radius_km=&limit=` | latest readings of the closest healthy sensors |
| `GET /v1/model` | the champion model: version, dataset, final-test results |
| `GET /v1/accuracy?days=` | live error of corrected readings against official monitors |

- **Sensor ids are strings that never change**, built from the source: `pa-131075` is PurpleAir
  sensor 131075. Database ids stay internal, so rebuilding the database breaks no links.
- Sensors that the quality rules exclude are listed with `"health": "excluded"` and no corrected
  value. `nearest` only returns healthy sensors.

### Response shape

- A single resource is returned as a plain JSON object. A list is returned as
  `{"data": [...], "next_cursor": "..." | null}`.
- **Every reading carries its provenance:** `pm25_corrected`, `pm25_raw`, `aqi_category`,
  `model_version` (such as `airsight-correction/1`), `observed_at`, and `stale` (true when the
  reading is older than 6 hours, which is two missed ingestions).
- Field names are `snake_case`. Missing values are `null`, never left out.

### Units and time

- PM2.5 in µg/m³ with one decimal. AQI categories use the US EPA 2024 PM2.5 breakpoints: `good`
  (up to 9.0), `moderate` (to 35.4), `unhealthy_sensitive` (to 55.4), `unhealthy` (to 125.4),
  `very_unhealthy` (to 225.4), `hazardous`.
- Times are ISO 8601 in UTC with a `Z`. An hourly reading's time is the start of its hour. Query
  times without a time zone are rejected, not guessed.

### Errors

Every error uses **Problem Details (RFC 9457)** with content type `application/problem+json`:
`type`, `title`, `status`, `detail`, plus `errors` listing each invalid field for validation
failures. Status codes: 400/422 for bad input, 404 for an unknown sensor, 429 for too many requests,
503 when no model has been promoted yet. Error responses never contain stack traces or SQL.

### Pagination

Cursor-based: `limit` (default 50, max 200) and an opaque `next_cursor` to pass back as `cursor`.
Page numbers were rejected because rows shift when sensors are added, which makes pages skip or
repeat items, and deep offsets get slower.

### Caching

Responses are cached in Redis by their normalised query (coordinates rounded to 3 decimals,
about 100 m) and sent with a matching `Cache-Control` header:

| Data | Expiry | Why |
|---|---|---|
| Latest readings, nearest | 5 minutes | new corrections land at most every 3 hours; 5 minutes bounds how late a new batch shows up |
| History older than today | 1 hour | the past only changes if we backfill |
| Model info | 1 hour, and cleared on promotion | changes only when a model is promoted |
| Accuracy | 15 minutes | recomputed from recent hours |

### Rate limits

60 requests per minute per client IP, counted in Redis. Over the limit: 429 with `Retry-After`.
Every response carries `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset` headers.

### Compatibility

Within `/v1`, changes are additive only: new endpoints, new optional parameters and new fields.
Renaming or removing anything means `/v2`. CI fails if the OpenAPI schema changes without the
committed schema file being updated in the same PR (#72).

## Consequences

- The API never loads the model, so requests stay fast and a broken model can't take it down.
  The cost: a new champion's corrections appear only after the next batch run.
- Caching by rounded coordinates means two people 50 m apart share a cached answer, which is fine
  for air quality and makes the cache effective.
- No accounts means rate limits by IP, which a determined user can get around. Fine for a
  portfolio-scale public API; API keys can come later without breaking `/v1`.
- Problem Details and cursors are slightly more work than ad hoc errors and page numbers, but they
  are standards any client already understands.
