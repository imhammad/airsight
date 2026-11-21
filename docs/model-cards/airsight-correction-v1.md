# Model card: airsight-correction v1

| | |
|---|---|
| **Status** | Champion since 2026-11-06 (AirSight v0.3.0), served by the API since v0.4.0; kept after the 2026-11-21 retrain ([Retrain history](#retrain-history)) |
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

## Live performance

Since v0.4.0 the API scores the stored corrections against the official monitors every day, only
on hours after the training data ends (`GET /v1/accuracy`, see [API.md](../API.md)). First week
live, 2026-10-31 to 2026-11-07 (3,550 hours, 10 stations):

| | Headline MAE |
|---|---|
| Raw PurpleAir | 3.11 |
| EPA correction | 3.60 |
| **airsight-correction v1** | **2.77** |

Still better than EPA at 7 of 10 stations, but better than raw readings at only 6 of 10: it loses
to raw at Berkeley Aquatic Park, Redwood City, San Francisco and San Rafael. The bias has changed
sign. On the final test the model read low on moderate hours; live, it reads 1 to 2 µg/m³ **high**
at 9 of 10 stations, and +3.5 at San Rafael. The likely cause is that November air is cleaner
than the August to October training data. This is the drift the monitoring and retraining in
Phase 8 are for.

## Retrain history

### 2026-11-21: retrained, v1 kept (#108)

**Why.** On 2026-11-09 v1 was less accurate than raw readings at 4 of 10 monitors, which is
a retrain trigger in ADR 0011. By the time the retrain could run (it needed 14 fresh days for a
final test), the data-quality fixes in #99 and #100 had brought v1 back to 2.67 live against
4.84 for raw. The retrain went ahead as planned, with the usual rule that it replaces v1 only if
it wins.

**Data.** Dataset `pairs-3e54345cdafc`: 60,704 sensor-hours, 31 sensors, 10 monitors, ending
2026-11-21. Training run `9a986e839dfc42b599f0bdbe06929514`.

**Validation** (2026-10-24 to 2026-11-07) picks one of the three candidates:

| Candidate | Headline MAE |
|---|---|
| Raw PurpleAir | 2.90 |
| EPA correction | 3.47 |
| **all-data** (chosen) | **2.56** |
| last-60-days | 2.58 |
| recent-weighted (30-day half-life) | 2.60 |

**Final test** (2026-11-07 to 2026-11-21, 5,562 hours, the same hours for every model, seen by
neither):

| | Headline MAE | All hours MAE | Moderate hours MAE (1,094 h) | Bias |
|---|---|---|---|---|
| Raw PurpleAir | 4.48 | 4.80 | 10.48 | +1.48 |
| EPA correction | 4.17 | 3.58 | 5.46 | −2.02 |
| Candidate (all-data, trained on everything before the test) | 2.66 | 2.71 | 5.35 | −0.73 |
| **v1 (champion)** | **2.65** | **2.69** | **4.93** | −0.45 |

The candidate passed the ADR 0007 ship rules, but ADR 0011 also requires a lower final-test MAE
than the champion, and 2.66 is not below 2.65. **v1 stays champion.** The two are effectively
tied: the candidate is better at 4 stations (Concord, Oakland, Redwood City, San Francisco), v1
at the other 6, and v1 is clearly better on moderate hours.

**What we learned.**

- All three candidates scored within 0.04 of each other on validation, and the one that weights
  recent data most scored worst. There is no sign that the sensors' behaviour changed with the
  season. v1's weak start in November came from data problems that #99 and #100 fixed, not from
  drift, which corrects the guess in [Live performance](#live-performance).
- A month more of training data did not help. More variety (wood smoke, wildfire smoke) will
  matter more than more of the same autumn air.
- November is harder for raw sensors than the original test: raw reads 7 µg/m³ high on moderate
  hours. v1 removes most of that error, but still reads low on those hours (bias −4.68).

**Next retrain** needs a dataset ending 2026-12-05 or later, so its final test is 14 days
neither model has seen, and, as ADR 0011 says, one of its triggers. The alerts from #141 watch
both.

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
