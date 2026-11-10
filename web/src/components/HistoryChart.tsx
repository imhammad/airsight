import type { Reading } from "../api/client";
import { category } from "../lib/aqi";
import { bayAreaHour, HOUR, startOfHour } from "../lib/time";
import styles from "./HistoryChart.module.css";

const HOURS = 24;
// The scale never goes below this, so a clean day doesn't fill the chart
const MIN_SCALE = 12;

/** The last 24 hours as one bar per hour, coloured by category. Missing hours stay empty. */
export function HistoryChart({
  readings,
  now,
}: {
  readings: Reading[];
  now: number;
}) {
  const last = startOfHour(now);
  const first = last - (HOURS - 1) * HOUR;
  const byHour = new Map(
    readings.map((reading) => [Date.parse(reading.observed_at), reading]),
  );
  const slots = Array.from({ length: HOURS }, (_, i) => {
    const hour = first + i * HOUR;
    return { hour, reading: byHour.get(hour) };
  });

  const values = readings.map((reading) => reading.pm25);
  const scale = Math.max(MIN_SCALE, ...values);
  const summary =
    values.length === 0
      ? "No readings in the last 24 hours"
      : `Hourly PM2.5 over the last 24 hours, between ${Math.min(...values).toFixed(1)} and ${Math.max(...values).toFixed(1)} µg/m³`;

  return (
    <figure className={styles.figure}>
      <div className={styles.bars} role="img" aria-label={summary}>
        {slots.map(({ hour, reading }) => (
          <span key={hour} className={styles.slot}>
            {reading && (
              <span
                className={styles.bar}
                title={`${bayAreaHour(hour)}: ${reading.pm25.toFixed(1)} µg/m³`}
                style={{
                  height: `${(reading.pm25 / scale) * 100}%`,
                  background: category(reading.aqi_category).colour,
                }}
              />
            )}
          </span>
        ))}
      </div>
      <figcaption className={styles.axis}>
        <span>{bayAreaHour(first)}</span>
        <span>{bayAreaHour(first + 12 * HOUR)}</span>
        <span>Now</span>
      </figcaption>
    </figure>
  );
}
