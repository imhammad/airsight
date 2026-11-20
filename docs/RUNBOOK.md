# Runbook

What to do when an alert fires. Each alert's `runbook_url` links to its section here. The rules
are in [`infra/prometheus/rules/airsight.yml`](../infra/prometheus/rules/airsight.yml), the
decisions behind them in [ADR 0013](adr/0013-observability.md).

Where to look:

- **Grafana** (<http://localhost:3000>): the Pipeline dashboard shows firing alerts at the top
  and in the Alerts row.
- **Alertmanager** (<http://localhost:9093>): every firing alert, with its labels.
- **Prometheus** (<http://localhost:9090/alerts>): every rule, and whether it is pending or
  firing.

Every command below runs in the repo root.

| Alert | Severity | Fires when |
|---|---|---|
| [DataStale](#datastale) | warning | a source's newest row is over 6 hours old (day-ahead weather: 27 hours) |
| [JobFailing](#jobfailing) | warning | a scheduled job hasn't succeeded for two of its periods |
| [TargetDown](#targetdown) | critical | Prometheus can't scrape the API or the exporter for 3 minutes |
| [ExporterFailing](#exporterfailing) | warning | the exporter can't read all of its sources for 15 minutes |
| [ApiErrors](#apierrors) | critical | over 1% of API requests (and at least 3) fail with a 5xx over 10 minutes |
| [CorrectionWorseThanRaw](#correctionworsethanraw) | warning | the correction's 14-day live MAE is above raw for 6 hours |
| [MonitorsOnRaw](#monitorsonraw) | warning | 3 or more monitors have been on raw all week |

## DataStale

**What it means:** no new rows from one source for longer than its schedule allows. Hourly
sources (PurpleAir, AirNow, weather, corrected readings, forecasts) arrive every 3 hours and are
normally at most about 4.5 hours old. Day-ahead weather loads once a day at 04:45 UTC.

**Why it matters:** this is the alert we didn't have on 12 November, when AirNow's Bay Area feed
stopped and every run still reported success.

**Check:**

1. Is it one source or all of them? The "How old the newest data is" panel on Pipeline shows it.
   - **All of them:** the worker or beat is down, or the laptop was asleep. Go to
     [JobFailing](#jobfailing).
   - **Only `corrected` or `forecast`:** their job failed, or their input (PurpleAir, AirNow,
     weather) is stale too. A forecast that finds no readings retries for an hour before it
     fails (`NoReadingsYetError`), so right after the laptop wakes, give it that hour.
   - **Only one outside source:** that provider has a problem. Keep reading.
2. See what live ingestion says about that source:

   ~~~bash
   docker compose logs worker --since 6h | grep -iE "airnow|purpleair|open-meteo|error"
   ~~~

3. For AirNow, check whether the problem is ours or theirs. If Los Angeles is fresh and the Bay
   Area isn't, it's their regional feed, as on 12 November:

   ~~~bash
   docker compose exec db psql -U airsight -d airsight -c "SELECT max(time) FROM reference_readings"
   ~~~

**Fix:**

- If our side failed (a bad key, a code error), fix it and run live ingestion now:
  `docker compose exec worker celery -A airsight.worker.celery_app call airsight.ingest_live`.
- If the provider is down, there's nothing to fix. Every live run fetches from the newest stored
  hour (at most 3 days back), so it catches up by itself once the provider is back. Forecasts
  issued meanwhile are flagged `monitor_offline`.
- If the laptop was asleep, the next run catches up. The alert clears within an hour of it.

## JobFailing

**What it means:** a scheduled job hasn't finished successfully for two of its periods: 6.5 hours
for `live`, `correct_readings` and `issue_forecast`, 48.5 hours for `quality` and
`load_day_ahead_weather`. A single failed run doesn't fire, because the next run catches up; the
Pipeline dashboard shows it in red.

**Check:**

1. Did the job run and fail, or not run at all? Look at "Latest run of each job" on Pipeline.
   - **Last start is recent, Latest run is Failed:** it runs but fails. See its error:

     ~~~bash
     docker compose exec db psql -U airsight -d airsight -c "SELECT task, started_at, status, error FROM ingestion_runs WHERE status = 'failed' ORDER BY started_at DESC LIMIT 5"
     docker compose logs worker --since 12h | grep -A 20 Traceback | tail -60
     ~~~

   - **Last start is old too:** nothing runs it. Check that `worker` and `beat` are up and
     healthy:

     ~~~bash
     docker compose ps worker beat
     docker compose logs beat --since 6h | tail -20
     ~~~

2. A growing "Tasks waiting" queue means the worker is stuck on one task.

**Fix:**

- Fix the error, deploy, and run the job by hand. Its task name is `airsight.` plus the job name,
  for example `docker compose exec worker celery -A airsight.worker.celery_app call airsight.issue_forecast`.
- A worker or beat that is down: `docker compose up -d --wait worker beat`.
- A stuck worker: `docker compose restart worker`.

If you change a job's schedule in `worker/celery_app.py`, change its threshold in the rule too.

## TargetDown

**What it means:** Prometheus couldn't scrape the API (port 8000) or the exporter (port 9108) for
3 minutes. While the exporter is down, DataStale, JobFailing and the model alerts can't see
anything, so this alert stands in for them.

**Check:**

~~~bash
docker compose ps api exporter
docker compose logs exporter --since 15m | tail -30
curl -s localhost:9108/metrics | head -5
~~~

**Fix:** start or restart the service (`docker compose up -d --wait api exporter`). If it keeps
crashing, its logs say why: most often the database isn't reachable.

## ExporterFailing

**What it means:** the exporter answers, but one of its queries failed for 15 minutes in a row.
`airsight_exporter_up` is 0. The metrics it could still read keep coming.

**Check:** the exporter logs name the failing query.

~~~bash
docker compose logs exporter --since 30m | grep -iE "failed|error" | tail -20
~~~

- **"Could not read the champion from MLflow":** MLflow is down. The model accuracy gauges are
  missing until it's back. Run `docker compose ps mlflow`.
- **"Pipeline metrics failed" or "Queue length failed":** the database or Redis isn't reachable.
  Run `docker compose ps db redis`.

**Fix:** bring the failing service back (`docker compose up -d --wait <service>`). The exporter
retries on every scrape and clears by itself.

## ApiErrors

**What it means:** over 1% of API requests, and at least 3 of them, got a 5xx response in the
last 10 minutes. Requests to `/metrics` aren't counted.

**Check:**

1. On the API dashboard, "Responses by status" shows when it started, and "Requests per second by
   route" shows which route.
2. Every 500 response carries an `X-Request-ID` header, and every log line of that request
   carries the same ID. Find the errors in the API logs:

   ~~~bash
   docker compose logs api --since 15m | grep '"level": "ERROR"' | tail -20
   ~~~

3. Take one `request_id` from there and see that request's whole story:

   ~~~bash
   docker compose logs api --since 15m | grep '<request_id>'
   ~~~

**Fix:** most often the database or Redis is unreachable (`docker compose ps db redis`), or a
deploy broke a route. Roll back with `git revert` and redeploy if a deploy caused it.

## CorrectionWorseThanRaw

**What it means:** over the last 14 days, the champion correction model's live error is above
the raw sensors' error, on at least 200 scored hours, and has been for 6 hours. The correction is
making readings worse. ADR 0011 says this calls for a retrain.

**Users are already protected:** each monitor area switches to raw readings by itself when the
correction loses there (ADR 0010). This alert says it happened across the whole network.

**Check:** the Model dashboard shows when the lines crossed. The public accuracy page
(`/v1/accuracy`) gives the per-station numbers.

**Fix:** retrain as ADR 0011 describes, then promote only if the new model passes the final test:

~~~bash
cd backend
uv run python -m airsight.ml.dataset
uv run python -m airsight.ml.train
uv run python -m airsight.ml.registry promote <run_id>
~~~

Write a new model card for the new version.

## MonitorsOnRaw

**What it means:** 3 or more official monitors have had the correction switched off (raw
readings shown instead) for the whole last week. The alert needs a full week of data before it
can fire.

**Check:** which monitors, and by how much the correction loses there: the accuracy page lists
each station's corrected and raw MAE. One station with a known bias (San Rafael, model card v1)
is expected; three for a week is a pattern.

**Fix:** the same retrain as [CorrectionWorseThanRaw](#correctionworsethanraw). If the same
stations keep losing after a retrain, the cause is probably local (a sensor problem, a site
change). Check those sensors in the data quality report before training again.
