# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog (https://keepachangelog.com/en/1.1.0/), and the project uses
Semantic Versioning (https://semver.org/).

## Unreleased

## 0.4.0 - 2026-11-09

Public API: corrected readings for every served sensor, which model made them, and the model's
live accuracy against official monitors, with caching, rate limits and a tested contract.

### Added

- API design decision: REST under `/v1`, stable sensor ids, Problem Details errors, cursor
  pagination, cache lifetimes, rate limits and additive-only changes (ADR 0008) (#73).
- Corrected readings stored per sensor-hour with the model version that made them, refreshed by a
  Celery task every 3 hours (#74).
- `GET /v1/sensors`, `/v1/sensors/{sensor_id}` and `/v1/readings/nearest`, with AQI categories
  and a stale flag (#75).
- `GET /v1/sensors/{sensor_id}/history`, `/v1/model` and `/v1/accuracy`: live, out-of-sample
  error per station against raw and EPA baselines (#76).
- Redis response cache with `X-Cache` and `Cache-Control`, cleared when a model is promoted;
  60 requests a minute per IP with `RateLimit-*` headers; RFC 9457 errors (#84).
- OpenAPI contract in `docs/openapi.json` with a test that keeps it in sync, the API guide
  `docs/API.md`, and a load test (#85).
- Live performance in the model card.

### Changed

- Promotion tags the model version with `trained_before`, the first hour it never saw (#76).

## 0.3.0 - 2026-11-06

Correction model: LightGBM corrects PurpleAir readings with a headline error of 2.50 µg/m³ on
14 unseen days, against 3.42 for the EPA correction and 2.87 for raw readings.

### Added

- Evaluation decision: leave one station out, a final 14-day test scored once per release,
  station-averaged MAE as the headline, and ship rules (ADR 0007) (#59).
- Versioned training dataset in Parquet, named by a hash of its contents, with features shared
  by training and serving (#60).
- Evaluation harness with raw and EPA baselines, results per station and per AQI band, and the
  ship rules in code (#61).
- MLflow tracking server in Docker Compose and a LightGBM correction model; every run records
  its dataset, parameters, metrics and model (#62).
- Model registry: promotion runs the final test and registers the model as
  `airsight-correction@champion` only if every ship rule passes; skew, signature and
  golden-feature tests (#63).
- Model card and results in the README (#64).

### Fixed

- The backend image installs `libgomp1`, which LightGBM needs (#62).
- Training tests no longer leave MLflow files in `backend/mlruns` (#62).

## 0.2.0 - 2026-11-05

Data pipeline: three months of paired sensor, monitor and weather data, kept current every
3 hours, with quality checks.

### Added

- Architecture decisions: TimescaleDB with PostGIS, Celery with Redis, batch predictions
  (ADRs 0003 to 0005), and an architecture overview (#27, #29).
- Typed settings from environment variables, with API keys as secrets (#37).
- Database schema through Alembic migrations: hypertables, PostGIS locations and an hourly
  continuous aggregate (#38).
- Clients for Open-Meteo, AirNow and PurpleAir with retries, and a guard on PurpleAir's paid
  points (ADR 0006) (#39, #40, #41).
- Backfill command with idempotent upserts and sensor pairing within 1 km (#42); it now resumes
  after a failure and skips hours already stored (#48).
- Data exploration on 3 months of data: broken sensors found, the EPA correction measured as
  the baseline, and the v0.3 target set (#45, #49).
- Live ingestion every 3 hours: per-sensor catch-up, a points cap per run and a lock against
  overlapping runs; Celery worker and beat run in Docker Compose (#46, #47).
- Data quality: per-hour flags computed by the database and a daily sensor health check that
  excludes broken sensors (#50).

### Changed

- Dependabot skips major upgrades of TypeScript and @types/node (#25).

### Fixed

- Request logs no longer contain API keys (#44).
- Celery beat has a health check, so the CI smoke test can wait for it (#47).

## 0.1.0 - 2026-11-02

Foundations: the repository, tooling and delivery pipeline every later feature builds on.

### Added

- Issue forms and pull request template (#2).
- Data coverage check confirming the San Francisco Bay Area as the training region (ADR 0001) (#4).
- Backend Python package `airsight` (uv, FastAPI) with `GET /v1/health`, and ADR 0002 on the
  single-package layout (#11).
- Multi-stage, non-root Docker image for the backend and a docker compose stack with
  PostgreSQL (TimescaleDB + PostGIS) and Redis, all with health checks (#12).
- Pre-commit hooks: ruff, mypy, file hygiene and private key detection (#13).
- CI on every pull request: lint, backend tests, a docker compose smoke test and web checks,
  plus Dependabot for uv, npm, GitHub Actions and Docker (#14, #17).
- Web app scaffold (Vite, React, TypeScript) with ESLint, Prettier and Vitest (#17).
- README, contributing guide, security policy and engineering log (#21).
