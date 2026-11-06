# ADR 0007: Evaluate the correction model on unseen stations and unseen time

- **Status:** Accepted
- **Date:** 2026-11-06
- **Issue:** #53

## Context

AirSight corrects low-cost sensor readings in places that have no official monitor. A model is
only useful if it works there, so the evaluation must test exactly that. Readings are strongly
correlated hour to hour and sensor to sensor near the same monitor: a random train/test split
would put near-copies of test rows in the training data and report accuracy we can't reproduce.

The data exploration (docs/data-exploration.md) gives the baselines: on 3 months of data the EPA
correction has a mean absolute error (MAE) of 3.21 µg/m³ against 3.65 for raw readings, but it is
worse than raw on moderately polluted hours. Four of the 12 monitors hold most of the paired hours.

## Options

1. Random split of rows: easy, but leaks neighbouring hours and the same sensor into the test set.
2. Time split only: honest about the future, but every test sensor was seen in training.
3. Leave one station out, plus a final time holdout: each test is a place the model never saw,
   and the release number also comes from a period it never saw.

## Decision

Option 3.

- **Stations:** each low-cost sensor belongs to its nearest official monitor. For each of the
  monitors in turn, the model is trained on all other monitors' sensors and tested on that
  monitor's sensors (leave one station out).
- **Time:** the last 14 days of data before the dataset is built are the final test period.
  Development and tuning use only the earlier data. The final test is run once per release
  candidate, still leaving one station out: trained on other stations' earlier data, tested on
  the held-out station's last 14 days.
- **Data:** only clean hours (quality flags = 0) from sensors that are not excluded by the quality
  rules, paired with an official reading for the same hour.
- **Metrics:** MAE in µg/m³ as the main metric, plus mean error (bias) and RMSE. The headline
  number is the **average of the per-station MAEs**, so every station counts equally. Every result
  is also reported per station and per pollution level, using the US AQI breakpoints for PM2.5:
  good (up to 9), moderate (9 to 35.4) and above 35.4.
- **Baselines:** raw (average of the two counters) and the EPA US-wide correction
  (Barkjohn et al. 2021), scored by exactly the same code as the model.
- **Ship rules for v0.3.0:** a model ships only if, on the final test,
  1. its headline MAE is lower than the EPA correction's,
  2. its MAE on moderate hours is not higher than raw's, and
  3. it beats the EPA correction at more than half of the stations.
- **Small samples:** a pollution level with fewer than 100 test hours is reported with its count,
  and no claim is made about it.

## Consequences

- The numbers will be lower than a random split would show. They are the numbers a user of the
  map would actually experience.
- Training runs once per station, so a full evaluation trains about 12 models. With this data size
  that takes seconds to minutes.
- Station-level results show where the model fails, not only how it does on average.
- With almost no smoke data yet, v0.3.0 makes no accuracy claim above 35 µg/m³. The forecast widens
  its uncertainty there until real smoke hours are available.
