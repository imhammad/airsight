# ADR 0005: Precompute predictions in batch instead of running the model per request

- **Status:** Accepted
- **Date:** 2026-11-03
- **Issue:** #26

## Context

New low-cost readings arrive every 10 minutes; official ground truth arrives hourly. API traffic
is read-heavy, and many users ask about the same places. The original plan proposed a separate
model service that the API would call for every request.

## Options

1. **Online:** a model service that the API calls on each request.
2. **Batch:** workers compute the corrected value for every new reading, and an hourly forecast for
   every sensor, and store them in the database. The API only reads stored results.

## Decision

Option 2. Training runs as a separate batch command that logs to MLflow and registers the model.
Prediction workers load the model version marked as production.

## Consequences

- API speed depends only on a database read and the cache, not on model size.
- A broken model can't take the API down: it keeps serving the last stored values, each with an
  `as_of` timestamp so the UI can show how fresh the data is.
- Every prediction is stored with its model version. This makes the live accuracy page possible
  (compare stored predictions against official readings that arrive later) and makes any number
  traceable to the exact model that produced it.
- Trade-offs: freshness is bounded by the job schedule (about 10 minutes for corrections, hourly for
  forecasts), and predictions are computed even for sensors nobody looks at. With ~2,600 sensors and
  a small gradient boosting model, that costs seconds.
- Revisit if the product needs predictions for arbitrary user inputs, which batch can't provide.
