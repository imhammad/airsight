import type { Forecast, ForecastHour } from "../api/client";

const HOUR = 3_600_000;

/** A forecast issued `issuedHoursAgo` whole hours before the current hour, 24 hours long. */
export function forecast(
  issuedHoursAgo = 2,
  hour: (hoursAhead: number) => Partial<ForecastHour> = () => ({}),
  overrides: Partial<Forecast> = {},
): Forecast {
  const issued = Math.floor(Date.now() / HOUR) * HOUR - issuedHoursAgo * HOUR;
  return {
    sensor_id: "pa-27359",
    issued_at: new Date(issued).toISOString(),
    model_version: "airsight-forecast/1",
    stale: issuedHoursAgo > 6,
    hours: Array.from({ length: 24 }, (_, i) => ({
      target_time: new Date(issued + (i + 1) * HOUR).toISOString(),
      hours_ahead: i + 1,
      p10: 3.0,
      p50: 6.0,
      p90: 10.0,
      aqi_category: "good",
      outside_experience: false,
      ...hour(i + 1),
    })),
    ...overrides,
  };
}
