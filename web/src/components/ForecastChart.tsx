import type { ForecastHour } from "../api/client";
import { category } from "../lib/aqi";
import { bayAreaHour } from "../lib/time";
import styles from "./ForecastChart.module.css";

// Same floor as the history chart, so the two read on a similar scale
const MIN_SCALE = 12;

const percent = (value: number, scale: number) => `${(value / scale) * 100}%`;

/** The hours ahead as one column each: the likely range (p10 to p90) and the most likely value. */
export function ForecastChart({ hours }: { hours: ForecastHour[] }) {
  const scale = Math.max(MIN_SCALE, ...hours.map((hour) => hour.p90));
  const times = hours.map((hour) => Date.parse(hour.target_time));
  const middle = times[Math.floor((times.length - 1) / 2)];
  const low = Math.min(...hours.map((hour) => hour.p50));
  const high = Math.max(...hours.map((hour) => hour.p50));
  const label = `Forecast PM2.5 for the next ${hours.length} hours, most likely between ${low.toFixed(1)} and ${high.toFixed(1)} µg/m³`;

  return (
    <figure className={styles.figure}>
      <div className={styles.columns} role="img" aria-label={label}>
        {hours.map((hour, i) => {
          const colour = category(hour.aqi_category).colour;
          return (
            <span
              key={hour.target_time}
              className={styles.slot}
              title={`${bayAreaHour(times[i])}: most likely ${hour.p50.toFixed(1)}, likely ${hour.p10.toFixed(1)} to ${hour.p90.toFixed(1)} µg/m³`}
            >
              <span
                className={styles.range}
                style={{
                  bottom: percent(hour.p10, scale),
                  height: percent(hour.p90 - hour.p10, scale),
                  background: colour,
                }}
              />
              <span
                className={styles.median}
                style={{ bottom: percent(hour.p50, scale) }}
              />
            </span>
          );
        })}
      </div>
      <figcaption className={styles.axis}>
        <span>{bayAreaHour(times[0])}</span>
        <span>{bayAreaHour(middle)}</span>
        <span>{bayAreaHour(times[times.length - 1])}</span>
      </figcaption>
    </figure>
  );
}
