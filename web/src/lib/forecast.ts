import type { ForecastHour } from "../api/client";
import { category } from "./aqi";
import { bayAreaHour, startOfHour } from "./time";

/** The forecast hours still ahead: the hour in progress and later (past ones are dropped). */
export function upcoming(hours: ForecastHour[], now: number): ForecastHour[] {
  const current = startOfHour(now);
  return hours.filter((hour) => Date.parse(hour.target_time) >= current);
}

/** The forecast in one sentence: where it goes, when it peaks and how high it could get. */
export function summarize(hours: ForecastHour[]): string {
  if (hours.length === 0) return "No forecast hours left";
  const peak = hours.reduce((best, hour) =>
    hour.p50 > best.p50 ? hour : best,
  );
  const highest = Math.max(...hours.map((hour) => hour.p90));
  // Each change of category in order, so good, moderate, good reads as all three
  const labels = hours
    .map((hour) => category(hour.aqi_category).label.toLowerCase())
    .filter((label, i, all) => i === 0 || label !== all[i - 1]);
  const outlook =
    labels.length === 1
      ? `Most likely ${labels[0]} throughout`
      : `Most likely ${labels.join(", then ")}`;
  const peakTime = bayAreaHour(Date.parse(peak.target_time));
  return `${outlook}, highest around ${peakTime} at ${peak.p50.toFixed(1)} µg/m³. It could reach ${highest.toFixed(1)}.`;
}
