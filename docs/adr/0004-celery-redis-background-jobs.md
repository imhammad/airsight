# ADR 0004: Use Celery with Redis for scheduled and background work

- **Status:** Accepted
- **Date:** 2026-11-03
- **Issue:** #26

## Context

AirSight needs periodic jobs (pull sensors every 10 minutes, monitors and weather hourly), long
backfills of historical data split into chunks, and prediction jobs after new data arrives. Jobs need
retries with backoff, respect for external API rate limits, and visibility into failures. One
developer runs everything on a single server.

## Options

1. Cron plus scripts.
2. Celery with Redis as the message broker, and Celery beat for schedules.
3. A lighter queue (RQ or Dramatiq).
4. A streaming platform (Kafka).
5. A data orchestrator (Airflow, Dagster or Prefect).

## Decision

Option 2. Model training is not a Celery task: it runs as a separate, reproducible batch command
(see ADR 0005).

## Consequences

- Retries, timeouts, concurrency limits and scheduling come built in, unlike cron.
- Celery delivers tasks at least once, so a task can run twice. Every task must be idempotent:
  writes are upserts on natural keys, so running a job twice changes nothing.
- Celery beat must run as exactly one instance, so it gets its own container.
- Redis serves as both message broker and cache, using separate logical databases. That's fine
  at this scale; split them if either grows.
- Not Kafka: the data comes from polling APIs, not event streams, and a few hundred thousand rows a
  day don't justify running a Kafka cluster.
- Not an orchestrator yet: Dagster would be the candidate if pipelines grow into many dependent
  steps, but today it would be more infrastructure than problem.
