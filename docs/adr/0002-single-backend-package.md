# ADR 0002: One backend package with multiple entrypoints

- **Status:** Accepted
- **Date:** 2026-11-02
- **Issue:** #5

## Context

AirSight has an API, background workers (ingestion, predictions) and an ML training pipeline.
They share database models, settings and, most importantly, feature engineering code.

## Options

1. One package per service (`services/api`, `services/worker`, `ml/`), each with its own dependencies.
2. One Python package, `airsight`, in `backend/`, with separate entrypoints for API and workers.

## Decision

Option 2. Code lives in `backend/src/airsight/` with modules such as `api`, `worker`,
`ingestion`, `ml` and `core`. Each deployable (API, worker) is the same image started with a
different command.

## Consequences

- Training and serving import the same feature code, which prevents training/serving skew by design.
- One lockfile and one set of tooling to maintain.
- Services can't drift onto incompatible dependency versions. The tradeoff is that the API image
  includes ML libraries it may not need. Acceptable at this scale; revisit if image size or
  startup time becomes a problem.
