import type { SensorDetail } from "../api/client";
import { category } from "./aqi";

/** A sensor and its reading in words, for screen readers where the map only shows colour. */
export function describeSensor(sensor: SensorDetail): string {
  const name = sensor.name ?? sensor.id;
  const reading = sensor.latest_reading;
  if (sensor.health === "excluded") return `${name}, out of service`;
  if (!reading) return `${name}, no reading yet`;
  const raw = reading.source === "raw" ? " raw reading" : "";
  const label = `${name}, ${reading.pm25.toFixed(1)} µg/m³${raw}, ${category(reading.aqi_category).label}`;
  return reading.stale ? `${label}, over 6 hours old` : label;
}

/** Why a sensor shows raw (ADR 0010), in the same words wherever it appears. */
export const RAW_NOTE =
  "This is the sensor's own reading. Near here, our correction has been less accurate than the raw reading over the last 14 days, so we show raw until it improves.";

/** Why a sensor that passed the quality checks has no reading to show. */
export const NO_READING_NOTE =
  "We don't have a reading from this sensor that we can correct yet. Some sensors don't report humidity, which the correction needs.";

/** "airsight-correction/1" as people read it: "airsight-correction v1". */
export function modelLabel(modelVersion: string): string {
  const [name, version] = modelVersion.split("/");
  return version ? `${name} v${version}` : modelVersion;
}
