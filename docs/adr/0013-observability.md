# ADR 0013: How we watch the system and the model

- **Status:** Accepted
- **Date:** 2026-11-15
- **Issue:** #136

## Context

On 12 November AirNow's Bay Area feed stopped. Every live run still reported success, because an
empty answer is a valid answer. Forecasts quietly ran without the monitor's reading, and the
forecast score stayed at zero hours. We found out two days later, by looking. Nothing told us.

Phase 9 has to make problems like this visible before a user notices them. That means answering
four questions. What do we measure? How do the numbers leave the processes that know them? How
do we look at them and get told? How do we see the model drifting?

Our setup shapes the answers. One API container. One Celery worker with `--concurrency=1`, one
beat scheduler. Jobs run every 3 hours or once a day, not continuously. Most of what we care
about (how old the newest reading is, whether the last run worked) is already in the database.

## Options for getting numbers out of the workers

1. **Each worker serves its own `/metrics`.** The usual pattern for long-running services. A
   Celery prefork worker runs tasks in child processes, so counters need Prometheus'
   multiprocess mode, a shared directory and cleanup when children restart.
2. **Pushgateway.** Each job pushes its numbers when it ends. Made for batch jobs, but the
   gateway keeps the last value forever, so a job that stopped running still looks healthy.
3. **Read it from the database.** Jobs already write their results there. A small exporter
   queries the database when Prometheus asks and turns the answers into gauges.

## Decision

**Metrics.** Prometheus format, through `prometheus_client`.

- The **API** serves `/metrics` itself: requests by route and status, latency histograms,
  cache hits and rate-limit refusals. A request is fast and happens in the API process, so the
  API is the only place that sees it.
- A new **exporter** service (same image, `python -m airsight.observability.exporter`, port 9108)
  answers for everything else from the database and Redis (option 3):
  - freshness: seconds since the newest row of each source (PurpleAir readings, AirNow
    readings, corrected readings, forecasts, day-ahead weather);
  - jobs: last start, last success, last duration and rows for each scheduled task;
  - queue: tasks waiting in Redis;
  - model: the live 14-day MAE of the correction and of raw, monitors on raw, forecast coverage.
- To give every task a row, a Celery signal records each scheduled task in `ingestion_runs`, not
  only live ingestion. The table keeps its name; the migration that widens its use explains why.

Option 3 fits our scale: a few queries every 30 seconds on indexed columns. A stopped worker
cannot report "I'm fine", because the numbers come from what the work left behind, not from the
worker. That is exactly the failure we missed on 12 November.

**Logs.** One JSON object per line on stdout, from the standard `logging` module with our own
formatter (no new dependency). Every API request gets an ID, taken from an incoming
`X-Request-ID` header or made fresh, returned in the response header and added to every log line
of that request. Task logs carry the Celery task name and ID. The rule that hides the AirNow key
stays. Docker keeps the logs; collecting them centrally (Loki or similar) waits until we deploy.

**Dashboards and alerts.** Prometheus, Alertmanager and Grafana join `docker-compose.yml`, with
every dashboard, data source and alert rule kept as files in `infra/` so they are reviewed like
code. Three dashboards: system (API traffic, errors, latency), pipeline (freshness, jobs,
queue) and model (live accuracy, raw fallback, forecast coverage). Alert rules:

| Alert | Fires when |
|---|---|
| `DataStale` | a source's newest row is more than about 2 hours older than its schedule allows |
| `JobFailing` | a scheduled task hasn't succeeded for two of its periods |
| `TargetDown` | Prometheus can't scrape the API or the exporter |
| `ExporterFailing` | the exporter can't read one of its sources |
| `ApiErrors` | more than 1% of API requests fail with a 5xx over 10 minutes |
| `CorrectionWorseThanRaw` | the 14-day live MAE of the correction is above raw (ADR 0011) |
| `MonitorsOnRaw` | 3 or more monitors have been on raw for 7 days (ADR 0011) |

*Amended 2026-11-17 (#141).* The first version also fired `JobFailing` when a task's last run
failed. In the first week a single live run failed on a network error and the next run caught
up, so that rule would have woken someone for nothing. One failed run now shows in red on the
Pipeline dashboard; the alert waits for two missed periods. `TargetDown` and `ExporterFailing`
were added because every other alert reads the exporter's numbers: without them, a stopped
exporter would silence everything. The exact thresholds and tests are in
`infra/prometheus/rules/` and `infra/prometheus/tests/`.

Until we deploy, Alertmanager has no outside receiver: firing alerts show in its web page and in
Grafana. Phase 10 adds a real channel.

**Drift.** Once a day, an Evidently report compares the last 7 days of live model inputs with the
model's training data. The HTML report is logged to MLflow next to the model, and the share of
drifted inputs becomes a gauge on the model dashboard. Drift is a warning for a person to read;
it does not start a retrain (ADR 0011).

**What to do when an alert fires** is in the [runbook](../RUNBOOK.md), one section per alert.
Each rule's `runbook_url` links to its section.

## Consequences

- Three more containers. Prometheus and Grafana together need a few hundred MB of memory, fine
  on a 16 GB laptop and on the small VM Phase 10 expects.
- The exporter adds a few cheap queries every 30 seconds. If they ever get slow, the exporter can
  cache its answers for a scrape or two.
- Freshness thresholds depend on each job's schedule. Changing a schedule means changing its
  alert, and the runbook says so.
- `/metrics` must not be public once deployed. Phase 10's reverse proxy blocks it.
- The live accuracy job and the retrain-and-promote rule that Phase 9 lists already exist (ADR
  0010, ADR 0011). This phase only puts them on dashboards and behind alerts.
