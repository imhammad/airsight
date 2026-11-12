# ADR 0011: How and when we retrain the correction model

- **Status:** Accepted
- **Date:** 2026-11-12
- **Issue:** #107

## Context

The champion, airsight-correction v1, learned from August to October. Since going live in
November it reads 1 to 2 µg/m³ high and is less accurate than the raw reading near 4 of 10
monitors. The raw fallback (ADR 0010) keeps people from seeing the worse number, but it doesn't
fix the model. We now have more data, including the cleaner November air the model never saw.

A retrain needs answers to four questions. Which data does it learn from? How do we test it
honestly? When does it replace the champion? What starts a retrain?

## Options for the training data

1. **All data since August, equally weighted:** the most variety, but old weather patterns count
   as much as this month's.
2. **Only the last 60 days:** closest to today's air, but one unusual fortnight can dominate, and
   there are fewer high-pollution hours to learn from.
3. **All data, with recent hours weighted more:** keeps the variety while leaning towards
   current conditions. Its risk is a badly chosen weight.

We can't know in advance which works best for our sensors, so we don't pick one by argument.

## Decision

**Data.** Every retrain trains all three candidates. Option 3 uses a sample weight that halves
every 30 days back in time. The data-quality rules in force at the time of the retrain apply to
all three, including #99 (disagreeing channels) and #100 (no humidity).

**Choosing between the candidates.** The data is split by time, oldest to newest:

| Part | Used for |
|---|---|
| everything before the last 28 days | training |
| the 14 days after that | validation: picks the candidate and its settings |
| the last 14 days | the final test (ADR 0007), run once |

Validation uses the ADR 0007 harness, leave-one-station-out, scored by pollution level. The
candidate with the lowest station-averaged MAE on validation goes forward. The final test is
not looked at until the choice is made.

**Replacing the champion.** The chosen candidate is retrained on everything before the final
test. Then it and the current champion are both scored on the same final test. Neither model
has seen those 14 days. The candidate replaces the champion only if it:

- has a lower station-averaged MAE than the champion on the final test, and
- still meets the ADR 0007 ship rules: it beats the EPA correction overall, and it isn't worse
  than raw on moderate hours.

Otherwise the champion stays, and the new model card says why.

**What starts a retrain.** A person starts a retrain, after one of these happens:

- the 14-day live accuracy (`/v1/accuracy`) is worse than raw overall, or
- 3 or more monitors have been on raw (`serving_sources`) for 7 days in a row.

Phase 9 turns these two signals into alerts. Retraining stays a manual decision until we trust
the alerts.

**How often.** At most once every 14 days. Each retrain spends a fresh 14-day final test.
Retraining sooner would reuse hours a previous test has already seen, and a reused test is no
longer a test.

## Consequences

- One retrain trains three candidates. That is cheap: training takes minutes.
- The three-way comparison shows whether our sensors drift with the seasons. If option 1 keeps
  winning, the drift was a data gap rather than a change; if 2 or 3 win, recency matters.
- After each retrain the model card records the candidates' validation scores, which one won,
  and the final-test comparison with the champion.
- The final test is the newest 14 days, so a retrain needs those 14 days of corrected live data.
  This is also the earliest a new model could be judged anyway.
- The 30-day half-life, the 60-day window and both triggers are judgement calls. Changing any of
  them means updating this ADR.
