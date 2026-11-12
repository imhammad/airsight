# ADR 0012: How we forecast air quality for the next 24 hours

- **Status:** Accepted
- **Date:** 2026-11-12
- **Issue:** #109

## Context

AirSight shows what the air is like now. People also want to know whether to run tomorrow
morning or keep the windows shut tonight. Phase 8 adds a forecast for the next 24 hours at every
sensor, with an honest range, not a single number that looks more certain than it is.

A forecast is easy to get wrong in ways that look good on paper. The classic mistake is to train
with the weather that actually happened, then serve with a weather forecast. The backtest looks
great, and the live forecast is worse. So the design must answer: what exactly is forecast, from
which inputs, what does it have to beat, and how is it tested?

## What is forecast

**The paired official reading, hour by hour, 1 to 24 hours ahead of the latest clean hour.**
This is the same target the correction model learns (ADR 0007): what an official monitor would
measure at the sensor's place. The forecast and the correction then talk about the same quantity,
and the training labels are the monitors' own readings, not another model's output.

Every forecast gives three numbers per hour: **p10, p50 and p90**. The p50 is the forecast. The
p10 to p90 range should contain the real value 8 times in 10.

## Inputs

Everything a feature uses must be known at the issue time, the latest complete hour with a
clean reading:

| Input | Why |
|---|---|
| the sensor's raw reading at issue time, and its mean over the last 3 and 24 hours | where the air is now, and its recent level |
| the sensor's raw reading 24 hours before the target hour | the daily cycle |
| the paired monitor's latest available reading | the best "now" we have; AirNow arrives about an hour late, so whatever had arrived at issue time |
| hours ahead (1 to 24), the target's local hour and day of week | morning traffic and night inversions |
| forecast temperature, humidity, wind speed and direction, and precipitation for the target hour | wind and rain clear the air; still, cold nights trap it |

**Weather without leakage.** Training uses Open-Meteo's Previous Runs API: for each target
hour, the value its model forecast 24 hours earlier (`_previous_day1`, archived since 2024).
Serving uses the live Forecast API, whose forecasts are 1 to 24 hours old. Training therefore
sees older, less accurate weather forecasts than serving does. That can make the backtest
slightly pessimistic, never optimistic. Observed weather is never used for a future hour.

## Models

**LightGBM with a quantile objective, one model per quantile (0.1, 0.5, 0.9).** Hours ahead is a
feature, so one model covers all 24 horizons and learns from 24 times as many rows as a model
per horizon would. If the three answers cross (p10 above p50, say), they are sorted, so the range
always reads low to high.

**The range is calibrated (added 2026-11-12, #111).** The first backtest beat both baselines on
MAE (2.88 against 3.37), but its p10 to p90 range held only 69% of hours. Quantile models learn
how spread out the past was, and usually come out overconfident on hours they haven't seen. So
each fit uses conformalized quantile regression: the models learn from all but the newest week,
their misses on that week set how far to widen p10 and p90 for each hour ahead (enough for 80%
of hours to fall inside), and then they learn from every row. p10 never goes below 0. The
widening is stored with the models, because serving must apply it too.

## What it must beat

Two baselines, scored by the same code:

1. **Persistence:** the paired monitor's latest reading, for every hour ahead.
2. **Same hour yesterday:** the monitor's reading 24 hours before the target hour.

Both are hard to beat at short horizons. If the model can't beat them, a forecast isn't worth
showing.

## How it is tested

**Rolling-origin backtest** on the development period. Four folds of 7 days, oldest to newest.
Each fold trains on everything before it, then issues a forecast every 3 hours inside it, the
way the live job will. No fold ever trains on hours after its own forecasts were issued.

Scores, all averaged per monitor first like ADR 0007's headline, so busy monitors can't hide
weak ones:

- **MAE of p50,** overall and by horizon: 1 to 6, 7 to 12 and 13 to 24 hours ahead;
- **coverage:** the share of hours inside the p10 to p90 range;
- **pinball loss,** to choose between model settings during development.

**Final test:** the last 14 days of the forecast dataset, scored once, after every choice is
made (ADR 0007).

**Ship rules,** on the final test. The forecast is shown only if:

1. its p50 MAE over all horizons is lower than both baselines;
2. it beats the better baseline in at least 2 of the 3 horizon groups;
3. its p10 to p90 range covers between 75% and 85% of hours.

Rule 3 catches a range that is too narrow (overconfident) or too wide (useless).

## Smoke and other unseen air

Our data has almost no hours above 35.4 µg/m³ (data-exploration.md, decision 6). When the
monitor's latest reading or the p50 is above that, the forecast is outside what the model has
learned. The API then marks it, and the range is widened to at least half to one and a half
times the p50.

## Serving

Like the correction (ADR 0005), forecasts are computed in batch, not per request:

- a Celery job runs after each correction run (every 3 hours, at :45);
- it stores every hour of every forecast in a `forecasts` table with the issue time and the
  model version;
- `GET /v1/sensors/{id}/forecast` returns the latest issue, with its model version and whether
  it is marked as outside the model's experience;
- the model is registered as `airsight-forecast` with its own `@champion` alias, promoted only
  through the ship rules above.

Keeping every issue, not only the latest, lets us score the live forecast later the same way
we score the live correction.

## Consequences

- No extra PurpleAir points: the forecast reads only data we already store.
- One new data source, the Open-Meteo Previous Runs API, for training only. It is free and needs
  no key, like the other Open-Meteo APIs.
- Persistence is a strong baseline at 1 to 6 hours. The model may lose there; rule 2 allows that
  as long as it wins further ahead, where a forecast is most useful.
- Three months of history cover summer and autumn only. Winter inversions and smoke season are
  not in the data, and the model card will say so.
- The 3-hour issue cadence, the horizon groups, the 75% to 85% coverage limits and the smoke
  threshold are judgement calls. Changing any of them means updating this ADR.
