# ADR 0003: Store time series in PostgreSQL with TimescaleDB and PostGIS

- **Status:** Accepted
- **Date:** 2026-11-03
- **Issue:** #26

## Context

About 2,600 low-cost sensors report every 10 minutes: roughly 375,000 rows a day, over 130 million
a year, plus hourly official monitor readings and weather. The main queries are:

- a time range for one sensor, and the latest value for every sensor
- hourly averages (official monitors report hourly, so training data is hourly)
- spatial lookups such as "sensors within 2 km of this monitor"
- joins between sensor readings, monitor readings, weather and sensor metadata to build training pairs

## Options

1. Plain PostgreSQL.
2. PostgreSQL with the TimescaleDB and PostGIS extensions.
3. A dedicated time-series database (InfluxDB) next to a relational database for metadata.
4. A columnar analytics database (ClickHouse).

## Decision

Option 2.

## Consequences

- Hypertables partition data by time automatically, keeping time-range queries fast and making
  retention cheap (old chunks are dropped, not deleted row by row).
- Continuous aggregates maintain hourly averages incrementally instead of recomputing them.
- Chunk compression shrinks older data substantially.
- PostGIS answers distance queries inside the database.
- Everything is one database with ordinary SQL joins. Building training pairs needs time series,
  locations and metadata together, which option 3 would split across two systems.
- Trade-offs: a larger Docker image, and some features are Timescale-specific. The data is still
  plain PostgreSQL, so moving away stays possible. Option 4 would be faster for huge analytical
  scans, but this workload is mostly small, targeted queries.
