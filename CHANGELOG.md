# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog (https://keepachangelog.com/en/1.1.0/), and the project uses
Semantic Versioning (https://semver.org/).

## Unreleased

### Added

- Production alerts reach a phone through Telegram; until now they went to no receiver at all.

### Changed

- The README is redesigned: figures drawn from the project's own data in the web app's palette
  and fonts, in light and dark, a live error badge, a where-to-start guide, four problems worth
  reading about and a decisions table (#176).

### Fixed

- Live ingestion and the forecast try again every 10 to 15 minutes after a network error,
  instead of waiting for the next run 3 hours later. One network drop on the Mac had left every
  reading more than 6 hours old.

## 0.8.0 - 2026-11-25

Deployment. AirSight is live at https://airsight.tailbcc5c4.ts.net, served from a Mac through
Tailscale Funnel at no cost, with automatic deploys, daily backups and a public status page
(https://stats.uptimerobot.com/mJiJYV9Elv).

### Added

- ADR 0014: production runs on a Mac behind Tailscale Funnel, after the free cloud options fell
  through (#169).
- A production stack, `docker-compose.prod.yml`: its own Compose project and volumes, restart
  policies, memory limits and secrets from `.env.prod`. Caddy is the only door in: it serves the
  web app and the API on `127.0.0.1:8080`, adds security headers, never serves `/metrics`, and
  passes each visitor's real address to the API's rate limit (#170).
- Automatic deploys: every push to `main` builds multi-arch images to GHCR; a release tag deploys
  that exact commit over the tailnet (a `tag:ci` runner allowed only the Mac's SSH port, and a
  key that can only run `scripts/deploy.sh`), migrates, checks the health page and rolls back on
  failure (#171).
- Daily database backups to iCloud Drive, each checked with `pg_restore --list`, and a restore
  check that proves a backup by restoring it next to live. The runbook has a rehearsed
  procedure for restoring the database (#172).
- `docs/DEPLOYMENT.md`: how production works, how to set it up from scratch, and how to operate
  it (#173).
- An uptime monitor on the health page every 5 minutes, with a public status page.

### Changed

- The web image builds its static files on the build machine's own CPU, so multi-arch builds stay
  fast (#171).
- shellcheck runs in pre-commit (#171).

### Known limits

- The site is up only while the Mac is awake and online.
- Backups cover the database, not MLflow's model store.

## 0.7.0 - 2026-11-21

Observability and live model monitoring. Most of it shipped early in 0.6.0 (see "Observability"
there): JSON logs, Prometheus metrics, the monitoring stack, three dashboards and seven alerts.
This release completes it with a daily check of the model's inputs.

### Added

- A daily input drift check: each of the correction model's 6 inputs over the last 7 days is
  compared with its training data, the scores are stored in `input_drift`, a report is logged
  to the MLflow experiment `input-drift`, and the Model dashboard shows them in a new Inputs row.
  Drift is a reason to look, not to retrain (ADR 0011) (#161).

### Changed

- ADR 0013 amended: the drift check computes Evidently's default test itself with scipy, because
  Evidently does not support pandas 3 (#161).
- The JobFailing alert also covers the daily drift job (#161).

## 0.6.0 - 2026-11-21

Forecast: the next 24 hours of PM2.5 for every paired sensor, with an honest p10 to p90 range,
issued every 3 hours, served by the API, shown on the sensor page and scored live on the accuracy
page. Also the first retrain of the correction model, and early observability work from v0.7.0.

### Added

- Retraining rules: three training-data candidates, a validation period that picks one, and a
  final test the new model must win against the champion (ADR 0011) (#114, #117).
- Forecast design: LightGBM quantile models, day-ahead weather as it was forecast, a
  rolling-origin backtest and ship rules against persistence and same hour yesterday (ADR 0012)
  (#118).
- Day-ahead weather forecasts stored daily from the Open-Meteo Previous Runs API (#119).
- Forecast dataset and rolling-origin backtest (#120).
- airsight-forecast v1: p10, p50 and p90 models with a range calibrated by conformalized quantile
  regression, stored and promoted as one model. Final test MAE 2.69 µg/m³ against 3.21 for
  persistence, best at 9 of 10 monitors, range holds 79% of hours; model card in
  `docs/model-cards/airsight-forecast-v1.md` (#122, #123, #124, #125).
- A job that issues the forecast every 3 hours and stores it (#126).
- `GET /v1/sensors/{sensor_id}/forecast`, with `stale` and `monitor_offline` flags (#127, #134).
- The next 24 hours on the sensor page, as a range with the middle estimate (#128).
- `GET /v1/accuracy/forecast` and a forecast section on the accuracy page: live error against
  both baselines, by hours ahead, and how often the range holds (#130, #135).

### Changed

- Sensors with a dead or disagreeing channel are excluded from training and serving (#115).
- The correction no longer uses the sensor's humidity reading, so sensors that report none are
  corrected too (#116).
- The correction model was retrained on 2026-11-21 under ADR 0011. The new model tied v1 on the
  final test (2.66 against 2.65 µg/m³), so v1 stays champion; the result is in the v1 model
  card (#159).

### Fixed

- Live ingestion refills gaps in official readings after a missed run, up to 3 days back (#132).
- Forecast hours were built wrongly when start and end used different UTC objects (#121).

### Observability (early v0.7.0 work, included in this release)

- How we watch the system and the model (ADR 0013) (#143).
- Structured JSON logs with request IDs in the API and the worker (#151).
- Prometheus metrics: the API at `/metrics`, and a pipeline and model exporter on port 9108
  (#152, #153, #154).
- Prometheus, Alertmanager and Grafana in Docker Compose, with Pipeline, API and Model dashboards
  kept as code (#155).
- Seven alert rules with unit tests in CI, and `docs/RUNBOOK.md` with a section per alert (#156).
- The forecast retries for up to an hour when its readings aren't loaded yet, instead of reporting
  success with nothing stored (#158).

## 0.5.0 - 2026-11-11

Web app: a phone-first map of corrected readings, a page per sensor, the live accuracy against
official monitors and the method in plain words, with browser tests and Lighthouse in CI.

### Added

- Web design decision: who it is for, the layout, AQI colours, type and motion (ADR 0009) (#95).
- App shell with routing, data fetching and an API client typed from the OpenAPI contract (#96).
- Map of every sensor coloured by AQI category, with the nearest sensor's reading and
  "Use my location"; `GET /v1/readings/latest` (#97).
- Sensor page with the reading, the sensor's own value, the model and the last 24 hours (#98).
- Accuracy page with the live 14-day error against raw and EPA, per monitor, and an About page
  explaining the data, the model, how it is tested and its limits (#102).
- Browser tests on a phone and a laptop, and a Lighthouse gate in CI: accessibility, best
  practices and SEO must score 90 or more (#103).

### Changed

- Near monitors where the correction has been less accurate than the raw sensor over the last 14
  days, sensors serve their raw reading (ADR 0010). Readings gain `pm25` (the value to show) and
  `source`; `aqi_category` now follows `pm25`, the one exception to ADR 0008's additive-only rule,
  recorded in `docs/API.md` (#101).
- Each station in `/v1/accuracy` says whether its sensors show corrected or raw readings (#102).

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
