# ADR 0006: Collect PurpleAir data within the free points budget

- **Status:** Accepted
- **Date:** 2026-11-03
- **Issue:** #32

## Context

PurpleAir charges points for every API call: 5 points per request for current sensor data and 2 for
history, plus, for every row returned, the sum of the requested fields' prices (checked on the
Develop portal on 2026-11-03). The account holds about 995,000 free points. The fields we need cost
4 points per sensor-hour: `pm2.5_cf_1_a` (1), `pm2.5_cf_1_b` (1) and `humidity` (2).

- Polling all ~2,600 Bay Area sensors every 10 minutes costs about 2.6 million points a day.
- A year of hourly history for the 115 sensors within 2 km of a monitor costs about 4 million.

## Options

1. Buy points and collect broadly.
2. Collect only what training and evaluation need, within the free budget.

## Decision

Option 2. Collect the sensors within 1 km of an official monitor (at most 39). They are also the
most reliable training pairs. Use the history endpoint with hourly averages for both the backfill
and live collection, and leave out the sensor's temperature, which Open-Meteo provides for free.

## Consequences

- 3 months of history costs about 345,000 points. Live collection every 3 hours costs about 4,400
  points a day, so the remaining budget lasts about 5 months.
- The map shows these sensors only, not every sensor in the region.
- Every call is checked against a per-run points budget before it is made.
- Buying points later only changes settings (more sensors, longer history), not code.
