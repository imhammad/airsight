# ADR 0010: Show raw readings where the correction loses

- **Status:** Accepted
- **Date:** 2026-11-10
- **Issue:** #94

## Context

AirSight exists to make low-cost sensor readings more accurate. The champion model passed the
final test (MAE 2.50 against 2.87 for raw), but live scoring in November showed it reading
1 to 2 µg/m³ high, and less accurate than the raw reading near 4 of 10 monitors. Retraining
(Phase 8) will fix the cause. Until then, and whenever a future model drifts, showing a
"corrected" number that is worse than the sensor's own breaks our promise to be honest by
default (ADR 0009).

## Options

1. **Always show the correction:** simple, but knowingly shows the less accurate number.
2. **Switch the whole app to raw** when the headline MAE loses: throws away the correction at
   the monitors where it still wins.
3. **Choose per monitor**, from recent live scores, and say which value is shown.

## Decision

Option 3.

- After every correction run (every 3 hours), score each official monitor over the **last 14
  days**, using only the current champion's corrections. The score uses the same pairing as
  `/v1/accuracy`: each sensor counts towards its nearest monitor.
- If the corrected MAE is **higher** than the raw MAE, over **at least 200 scored hours**, every
  sensor paired with that monitor shows raw. Otherwise it shows corrected. A tie keeps the
  correction.
- The choice is recomputed on every run, so a monitor switches back on its own once the
  correction wins again. A newly promoted model starts on corrected everywhere: its own
  corrections haven't been scored yet.
- Choices and the scores behind them are stored in `serving_sources`, so any switch can be
  explained later.
- Every reading carries `pm25` (the value to show) and `source` (`corrected` or `raw`).
  `aqi_category` follows `pm25`. `pm25_corrected` and `pm25_raw` are still there.
- The web app labels raw readings: a white marker with a grey ring on the map (ADR 0009), and
  a sentence on the sensor's page saying why.

## Consequences

- People see the more accurate of the two values near each monitor, and are told which it is.
- 200 hours (about 8 days of one sensor, or 2 days of four) keeps a few bad hours from flipping
  a monitor, at the cost of reacting slowly to sudden drift.
- `aqi_category` changing meaning is not an additive change, so it breaks the rule in ADR 0008.
  We accept it once, before v1.0.0, because the web app is the only client. `docs/API.md`
  records it.
- The 14-day window and the 200-hour minimum are constants in `backend/src/airsight/ml/serving.py`.
  Changing them means updating this ADR.
