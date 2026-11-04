# Data exploration: PurpleAir sensors vs official monitors

Issue #33 · 2026-11-04 · Script: `notebooks/01_explore_pairs.py`

## Why this exists

Before building a correction model we need to know what the raw data looks like: how complete it is,
how many sensors are broken, and how good the existing EPA correction already is. These numbers are
the baselines every AirSight model must beat.

## Data

- 7-day backfill, 2026-10-27 16:00 to 2026-11-03 15:00 UTC (a clean, low-pollution week).
- 40 PurpleAir sensors within 1 km of 12 AirNow monitors in the San Francisco Bay Area.
- 6,592 paired sensor-hours. Median sensor coverage 100%; 1 sensor under 75%.
- 4.1% of hours have no official reading (monitor gaps).

Reproduce:

```bash
uv run --project backend --group notebooks python notebooks/01_explore_pairs.py
```

## Sensor health

| Sensor | Monitor | Problem |
|---|---|---|
| 120181 | Concord | Channel A median 4,991.8 µg/m³, channel B always 0 |
| 162567 | San Jose Jackson St | Channel B up to 5,633.3; 49% of hours disagree, 42% impossible |
| 195905 | San Jose Jackson St | Channel B median 6,411.9 |
| 119499 | San Rafael | Channel A about 4,992, channel B 0 |
| (Knox Ave sensor) | San Jose Knox Ave | Reads 0.1 vs official 6.8, yet passes all filters |

After removing impossible values (> 1,000), stuck zeros, missing channels and A/B disagreement
(EPA rule: channels differ by more than 5 µg/m³ AND more than 70%),
**5,055 of 6,592 hours (77%) are trustworthy**.

## Raw vs EPA correction

Error = sensor minus official monitor, in µg/m³, on trustworthy hours.
EPA US-wide correction (Barkjohn et al. 2021): `0.524 * raw - 0.0862 * RH + 5.75`.

| Method | Mean error | MAE | Correlation |
|---|---|---|---|
| Raw (average of A and B) | -0.74 | 2.88 | 0.45 |
| EPA correction | -2.06 | 3.17 | 0.34 |

**The EPA correction did worse than raw this week.**
![raw and EPA vs official](images/exploration/raw_vs_epa.png)

### Error by humidity

| Humidity band | Raw mean error | EPA mean error |
|---|---|---|
| Lowest | -0.91 | +0.36 |
| Low-mid | -0.68 | -1.87 |
| High-mid | -0.28 | -2.84 |
| Highest | -1.56 | -6.06 |

Raw error is roughly flat across humidity. EPA error grows with humidity: at low concentrations the
`-0.0862 * RH` term subtracts more than the particles contribute, and some monitors end up with
corrected values near zero or negative (Berkeley -0.6, Redwood City 0.4, Laney 1.0).
![error by humidity band](images/exploration/error_by_humidity.png)

## Decisions

1. Exclude sensors 120181, 162567, 195905 and 119499 from analysis and training.
2. Keep the EPA A/B disagreement rule for marking unreliable hours.
3. Add a "near zero while the monitor is not" check to the data quality checks (#36),
   prompted by the San Jose Knox Ave sensor.
4. Keep both raw and EPA as baselines. No method is declared better until we have 3 months of data.
5. Quality checks will **flag** rows, not delete them, so we can always see what was excluded and why.

## Limits

- One clean week. Readings stay in a narrow range (about 3 to 9 µg/m³) where noise dominates,
  which drags correlation down for every method.
- No smoke or high-pollution events, which is where corrections matter most.
- Oakland West (1,381 hours) and San Francisco (1,243) have many paired sensors, so they dominate
  pooled numbers. Leave-one-station-out evaluation (ADR 0001) will control for this.

## Next steps

- #34: live ingestion every 3 hours with Celery.
- #35: full 3-month backfill, then rerun this script and update this doc.
- #36: data quality flags based on the findings above.
