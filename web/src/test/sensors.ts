import type { SensorDetail } from "../api/client";

/** A sensor with a fresh reading; override any field per test. */
export function sensor(
  overrides: Partial<SensorDetail> = {},
  reading: Partial<NonNullable<SensorDetail["latest_reading"]>> = {},
): SensorDetail {
  return {
    id: "pa-27359",
    name: "Oceanview Neighborhood Assn",
    latitude: 37.87204,
    longitude: -122.30109,
    health: "ok",
    latest_reading: {
      pm25: 9.1,
      source: "corrected",
      pm25_corrected: 9.1,
      pm25_raw: 9.9,
      aqi_category: "moderate",
      model_version: "airsight-correction/1",
      observed_at: new Date(Date.now() - 40 * 60_000).toISOString(),
      stale: false,
      ...reading,
    },
    ...overrides,
  };
}

// Near downtown Oakland, where the map starts
export const LAKE_MERRITT = sensor(
  {
    id: "pa-1001",
    name: "Lake Merritt",
    latitude: 37.8021,
    longitude: -122.2585,
  },
  { pm25: 6.3, pm25_corrected: 6.3, aqi_category: "good" },
);
// In Berkeley, about 7.5 km north of downtown Oakland
export const OCEANVIEW = sensor();
// Near a monitor where the correction has been losing, so it shows its own reading
export const RAW = sensor(
  { id: "pa-1003", name: "Raw one", latitude: 37.79, longitude: -122.27 },
  {
    pm25: 8.4,
    source: "raw",
    pm25_corrected: 10.2,
    pm25_raw: 8.4,
    aqi_category: "good",
  },
);
// Closest to downtown Oakland, but excluded by the quality checks
export const BROKEN = sensor({
  id: "pa-1002",
  name: "Broken",
  latitude: 37.8055,
  longitude: -122.2724,
  health: "excluded",
  latest_reading: null,
});
// Healthy, but it doesn't report humidity, so there's no corrected reading
export const NO_READING = sensor({
  id: "pa-1004",
  name: "No humidity",
  latitude: 37.84,
  longitude: -122.28,
  latest_reading: null,
});
