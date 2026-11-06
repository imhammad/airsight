# Model card: airsight-correction v1

| | |
|---|---|
| **Status** | Champion since 2026-11-06 (AirSight v0.3.0) |
| **Registry** | MLflow model `airsight-correction`, version 1, alias `@champion` |
| **Training run** | `034df2accb7b4f51a02b01c8d3be47ef` (experiment `correction`) |
| **Dataset** | `pairs-f5a557c189d5`: 54,869 sensor-hours, 31 sensors, 10 official monitors, 2026-08-07 to 2026-11-05 |
| **Final test period** | 2026-10-23 to 2026-11-05 (14 days, scored once) |

## What it does

It takes one hour of readings from a PurpleAir sensor (its two particle counters and its humidity
sensor) plus the weather for that hour, and estimates what an official monitor would measure for
PM2.5 in the same place, in µg/m³.

**Intended use:** correcting PurpleAir sensors in the San Francisco Bay Area for AirSight's map
and API, so people can see air quality close to them with accuracy close to an official monitor.

**Not intended for:** regulatory or legal decisions; regions it was not evaluated in; smoke events
above 35.4 µg/m³, where it has no test data (see Limitations).

## Model

LightGBM gradient-boosted trees trained on absolute error (we are judged on MAE): 400 rounds,
learning rate 0.05, 31 leaves, at least 50 hours per leaf, 80% bagging, 90% feature sampling,
seed 42. The model kept in the registry is fitted on all development data, never on the final
test period.

| Feature | Meaning |
|---|---|
| `raw` | average of the sensor's two counters (`pm2.5_cf_1`) |
| `channel_difference` | how much the two counters disagree |
| `sensor_humidity` | the sensor's own humidity reading |
| `temperature`, `relative_humidity`, `wind_speed`, `precipitation` | Open-Meteo weather for the sensor's area |
| `local_hour`, `day_of_week` | California local time |

Features are computed in one place (`backend/src/airsight/ml/features.py`) for training and
serving. Tests check that serving reproduces training predictions exactly, that the stored model
expects exactly these features, and that the feature values never change by accident.

## Data

Hourly PurpleAir readings for sensors within 1 km of an AirNow monitor, each paired with its
nearest monitor's reading for the same hour, plus weather. Only clean hours are used (no quality
flag: both counters present, no impossible values, no stuck zeros, counters agreeing), and sensors
the quality rules exclude are left out entirely. See [docs/data-exploration.md](../data-exploration.md)
for how the data was checked.

## Evaluation

Following [ADR 0007](../adr/0007-model-evaluation.md): every monitor is scored by a model trained
without any of that monitor's sensors (leave one station out). The headline number is the
**average of the per-station MAEs**, so busy stations can't hide weak ones. Raw readings and the
EPA US-wide correction are scored by exactly the same code.

### Final test (14 unseen days)

| | Headline MAE | All hours MAE | Moderate hours MAE (867 h) | Bias |
|---|---|---|---|---|
| Raw PurpleAir | 2.87 | 2.98 | 4.48 | +0.29 |
| EPA correction | 3.42 | 2.99 | 6.18 | −1.66 |
| **airsight-correction v1** | **2.50** | **2.53** | **3.89** | +0.84 |

All values in µg/m³. Good hours (≤ 9): 7,856. Above 35.4: none, so no claim is made there.

| Station | Hours | Raw | EPA | v1 |
|---|---|---|---|---|
| Berkeley Aquatic Park | 297 | 2.35 | 5.63 | **2.47** |
| Concord | 315 | 2.45 | **1.60** | 2.36 |
| Laney College | 321 | 2.92 | 5.82 | **2.01** |
| Oakland | 313 | 2.36 | 2.31 | **1.97** |
| Oakland West | 2,001 | 3.05 | 3.32 | **2.39** |
| Redwood City | 302 | 2.26 | 5.02 | **1.99** |
| San Francisco | 2,296 | 2.28 | 2.31 | **2.10** |
| San Pablo - Rumrill | 309 | 4.24 | **3.11** | 3.14 |
| San Rafael | 979 | 2.01 | **1.97** | 3.73 |
| Vallejo | 1,590 | 4.73 | 3.11 | **2.83** |

Bold marks the better of EPA and v1 at each station.

### Ship rules (ADR 0007)

1. Headline MAE below EPA's: 2.50 < 3.42. **Pass.**
2. Moderate hours not worse than raw: 3.89 ≤ 4.48. **Pass.**
3. Better than EPA at more than half the stations: 7 of 10. **Pass.**

On the development period (2026-08-07 to 2026-10-22) the picture was similar: headline 2.70
against 3.95 for EPA and 3.84 for raw, better than EPA at 9 of 10 stations.

## Limitations

- **Reads too low on moderately polluted hours.** Bias is −3.77 µg/m³ on the final test (−4.30 in
  development). It is still better than both baselines there, but under-reading is the wrong
  direction for health warnings. Likely cause: 84% of development hours are clean air (up to
  9 µg/m³), and training on absolute error pulls estimates toward typical values.
- **San Rafael reads too high** (bias +3.19, MAE 3.73), where EPA does best. The model also loses
  to EPA at Concord and, narrowly, at San Pablo.
- **No smoke data.** The final test has no hours above 35.4 µg/m³ and development had only 38. The
  model must not be trusted on smoke days until it has been tested on them.
- **Short history.** Three months of training data (summer to autumn) and a 14-day final test in
  late autumn. Winter wood smoke and a smoky wildfire season are unseen.
- **Small stations.** Some monitors have few paired hours (Laney College had 50 in development),
  so their per-station numbers are noisy.
- **One region.** Only evaluated in the San Francisco Bay Area.
- **Sensor ageing** is not modelled; a drifting sensor will look like a wrong correction.

## Reproduce

```bash
docker compose up -d --wait
cd backend
uv run python -m airsight.ml.dataset            # rebuild the dataset from the database
uv run python -m airsight.ml.evaluation         # baselines on the development period
uv run python -m airsight.ml.train              # tracked training run, prints its run id
uv run python -m airsight.ml.registry promote <run_id>   # final test, then register if it ships
```

A rebuilt dataset includes newer data, so it gets a new hash and slightly different numbers.
