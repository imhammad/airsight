# Model card: airsight-forecast v1

| | |
|---|---|
| **Status** | Champion since 2026-11-12; not served yet (the forecast job and API come in #112) |
| **Registry** | MLflow model `airsight-forecast`, version 1, alias `@champion` |
| **Training run** | `ff402b0cd79146c6a12dd010c9ce47cf` (experiment `forecast`) |
| **Dataset** | `forecast-7d9714f5d39f`: 484,412 rows, 33 sensors, 10 official monitors, 2026-08-07 to 2026-11-11 |
| **Final test period** | Forecasts issued 2026-10-29 to 2026-11-11 (14 days, 54,193 rows, scored once) |

## What it does

Every 3 hours, for every PurpleAir sensor paired with an official monitor, it forecasts the
monitor's PM2.5 reading for each of the next 24 hours, in µg/m³. Each hour gets a range: p50 is
the middle estimate, and the true value should fall between p10 and p90 8 times in 10.

**Intended use:** telling people in the San Francisco Bay Area whether the air will be better or
worse later today and tomorrow, with an honest range, on AirSight's sensor pages and API.

**Not intended for:** health decisions on smoke days (see Limitations), regulatory use, or
regions it was not evaluated in.

## Model

Three LightGBM models trained on quantile loss, one each for p10, p50 and p90. Hours ahead is a
feature, so one set of models covers all 24 horizons. 300 rounds, learning rate 0.05, 31 leaves,
at least 200 rows per leaf, 80% bagging, 90% feature sampling, seed 42. If the three answers
cross, they are sorted.

**Calibration.** Quantile models are overconfident on hours they haven't seen: without it, the
p10 to p90 range held only 69% of hours in the backtest. Each fit therefore first learns from all
but the newest week (purged, so no target inside that week is learned), measures how far the
newest week fell outside its range, and widens p10 and p90 by that amount for each hour ahead
(conformalized quantile regression, [ADR 0012](../adr/0012-forecast-design.md)). Then it learns
from every row. v1 widens by 0.28 to 1.14 µg/m³ depending on hours ahead. p10 never goes below 0.

The three models and the widening are stored as **one** MLflow model, so they can only be
versioned, promoted and served together.

| Feature | Meaning |
|---|---|
| `raw_now`, `raw_mean_3h`, `raw_mean_24h` | the sensor's raw reading at the issue hour, and its 3 and 24 hour means |
| `raw_day_before` | the sensor's raw reading 24 hours before the target hour |
| `official_now` | the monitor's latest reading, at most 2 hours old |
| `horizon` | hours ahead, 1 to 24 |
| `local_hour`, `day_of_week` | of the target hour, California time |
| `temperature`, `relative_humidity`, `wind_speed`, `wind_direction`, `precipitation` | weather **forecast** for the target hour |

Every input is known at the issue hour. Training uses the weather as it was forecast the day
before (Open-Meteo Previous Runs API), never the weather that happened, because the real
forecast will not have observed weather either.

**What it relies on** (p50 model, share of total gain): the monitor's latest reading 29%, wind
direction 12%, humidity 12%, wind speed 10%, temperature 9%, day of week 9%, hour 7%. The
sensor's own inputs together account for 9%. The forecast weather carries almost half of the
model, which is why serving must use a real forecast for it, never observed weather.

## Evaluation

Following [ADR 0012](../adr/0012-forecast-design.md). Each station's MAE of p50 is computed
first, and the headline number is their average, so busy stations can't hide weak ones. Two
baselines are scored by the same code: **persistence** (the monitor's latest reading, for every
hour ahead) and **same hour yesterday** (the monitor's reading 24 hours before the target).

### Final test (14 unseen days)

| | Headline MAE | 1 to 6 h | 7 to 12 h | 13 to 24 h | p10 to p90 holds | Pinball loss |
|---|---|---|---|---|---|---|
| Persistence | 3.21 | 2.78 | 3.31 | 3.40 | n/a | 1.60 |
| Same hour yesterday | 3.24 | 3.20 | 3.24 | 3.26 | n/a | 1.62 |
| **airsight-forecast v1** | **2.69** | **2.41** | **2.72** | **2.82** | **79%** | **0.86** |

All values in µg/m³. 16% lower MAE than the better baseline.

| Station | Persistence | Same hour yesterday | v1 |
|---|---|---|---|
| Berkeley Aquatic Park | 2.77 | 2.88 | **2.44** |
| Concord | 2.90 | 2.84 | **2.63** |
| Laney College | 3.19 | 3.26 | **2.54** |
| Oakland | 2.92 | 2.88 | **2.26** |
| Oakland West | 3.76 | 3.52 | **2.82** |
| Redwood City | 2.68 | 2.92 | **2.30** |
| San Francisco | 2.71 | 2.64 | **2.37** |
| San Pablo - Rumrill | 4.47 | 3.93 | **3.37** |
| San Rafael | **2.94** | 3.22 | 3.02 |
| Vallejo | 3.77 | 4.29 | **3.14** |

Bold marks the best at each station. v1 is best at 9 of 10.

### Ship rules (ADR 0012)

1. Headline MAE below both baselines: 2.69 < 3.21. **Pass.**
2. Better than the better baseline in at least 2 of 3 horizon groups: 3 of 3. **Pass.**
3. p10 to p90 holds 75% to 85% of hours: 79%. **Pass.**

### Backtest (development period)

Four rolling 7-day folds ending 2026-10-28, each trained only on targets before the fold:
headline MAE 2.88 against 3.37 for persistence and 3.52 for same hour yesterday (2.63, 2.92 and
2.99 by horizon group), coverage 82%. The final test came out slightly better than the backtest,
and its coverage held, so the calibration generalised to days it never saw.

### Without the monitor (checked 2026-11-14)

AirNow's Bay Area feed went down on 12 November, so live forecasts ran without the monitor's
latest reading, the model's biggest input. Scoring the champion on the same final test with that
reading blanked out: MAE 2.88 against 2.69 (2.74, 2.84 and 2.97 by horizon group), coverage 78%.
That is about 7% less accurate, still ahead of both baselines (which need the monitor anyway), and
the range stays honest. Only 1.1% of training rows lacked the reading. Such forecasts are now
stored with `monitor_offline`, and the sensor page says so.

## Limitations

- **No smoke data.** Three months of summer and autumn air, mostly clean. Under ADR 0012, serving
  (#112) marks any forecast above 35.4 µg/m³ and widens its range, because the model has not
  been tested there.
- **San Rafael:** the only station where it loses to persistence (3.02 against 2.94). The
  correction model is weakest there too, so the monitor pairing deserves a look.
- **Coverage is an average.** 79% is the mean over stations; single stations and single hours
  ahead can be wider or narrower. The widening per hour ahead comes from one week of data, so it
  is noisy (0.28 at 22 hours, 1.14 at 17).
- **Weather forecast quality.** Training used Open-Meteo's day-before forecasts. A worse forecast
  at serving time would make the forecast worse in ways this test can't show.
- **Short history and one region**, as for the correction model.
- **Replacing this champion** needs a head-to-head on fresh days, which isn't built yet.
  Promotion refuses a second forecast until it is.

## Reproduce

```bash
docker compose up -d --wait
cd backend
uv run python -m airsight.ml.forecast_dataset      # rebuild the dataset from the database
uv run python -m airsight.ml.forecast_evaluation   # baselines on the backtest
uv run python -m airsight.ml.forecast_train        # tracked training run, prints its run id
uv run python -m airsight.ml.forecast_registry promote <run_id>   # final test, then register
```

A rebuilt dataset includes newer data, so it gets a new hash and slightly different numbers.
