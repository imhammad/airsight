# ADR 0001: Train in the San Francisco Bay Area

- **Status:** Accepted
- **Date:** 2026-11-02
- **Issue:** #3

## Context

The calibration model learns from hours where a low-cost PurpleAir sensor and an official,
regulatory-grade PM2.5 monitor measure the same air. The training region therefore needs many
monitors with a PurpleAir sensor close by, plus long hourly histories.

We compared the San Francisco Bay Area with Kuala Lumpur, Malaysia, using
`notebooks/00_fetch_coverage.sh` and `notebooks/00_data_coverage.py`
(snapshot: 2026-11-01 12:00 UTC).

## Evidence

| | Bay Area | Kuala Lumpur |
|---|---|---|
| Official PM2.5 monitors | 12 | 1 (3 in all of Malaysia on OpenAQ) |
| Active outdoor PurpleAir sensors | 2,618 | 2 |
| Monitors with a sensor within 1 km | 11 (39 pairs) | 0 |
| Monitors with a sensor within 2 km | 12 (115 pairs) | 0 |

## Decision

Train and launch the MVP in the San Francisco Bay Area. Do not use Malaysia for training or
evaluation.

## Consequences

- With 12 monitors, models are evaluated with leave-one-station-out: train on 11 stations,
  test on the held-out one, repeat for each. Random splits would leak station identity.
- Bay Area wildfire smoke seasons provide high-pollution examples, where the EPA's published
  PurpleAir correction is known to struggle.
- Open air quality data in Malaysia is too sparse today to train or validate on. This is
  recorded as a limitation. An out-of-region test will use a second region chosen in Phase 5.
- The counts come from a single-hour snapshot. Historical archives may include more stations;
  we recheck during data ingestion (Phase 4).
