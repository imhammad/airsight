import { expect, test } from "vitest";
import { BROKEN, NO_READING, RAW, sensor } from "../test/sensors";
import { describeSensor, modelLabel } from "./describe";

test("describes a sensor's reading in words", () => {
  expect(describeSensor(sensor())).toBe(
    "Oceanview Neighborhood Assn, 9.1 µg/m³, Moderate",
  );
  expect(describeSensor(sensor({ name: "Old" }, { stale: true }))).toBe(
    "Old, 9.1 µg/m³, Moderate, over 6 hours old",
  );
  expect(describeSensor(RAW)).toBe("Raw one, 8.4 µg/m³ raw reading, Good");
  expect(describeSensor(BROKEN)).toBe("Broken, out of service");
  expect(describeSensor(NO_READING)).toBe("No humidity, no reading yet");
});

test("names the model the way people read versions", () => {
  expect(modelLabel("airsight-correction/1")).toBe("airsight-correction v1");
  expect(modelLabel("something-else")).toBe("something-else");
});
