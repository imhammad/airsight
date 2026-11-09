import type { SensorDetail } from "../api/client";
import { category } from "./aqi";

/** A sensor and its reading in words, for screen readers where the map only shows colour. */
export function describeSensor(sensor: SensorDetail): string {
  const name = sensor.name ?? sensor.id;
  const reading = sensor.latest_reading;
  if (sensor.health === "excluded" || !reading)
    return `${name}, out of service`;
  const label = `${name}, ${reading.pm25_corrected.toFixed(1)} µg/m³, ${category(reading.aqi_category).label}`;
  return reading.stale ? `${label}, over 6 hours old` : label;
}

/** "airsight-correction/1" as people read it: "airsight-correction v1". */
export function modelLabel(modelVersion: string): string {
  const [name, version] = modelVersion.split("/");
  return version ? `${name} v${version}` : modelVersion;
}
