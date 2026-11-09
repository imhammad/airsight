import { expect, test } from "vitest";
import { BROKEN, sensor } from "../test/sensors";
import { describeSensor } from "./describe";

test("describes a sensor's reading in words", () => {
  expect(describeSensor(sensor())).toBe(
    "Oceanview Neighborhood Assn, 9.1 µg/m³, Moderate",
  );
  expect(describeSensor(sensor({ name: "Old" }, { stale: true }))).toBe(
    "Old, 9.1 µg/m³, Moderate, over 6 hours old",
  );
  expect(describeSensor(BROKEN)).toBe("Broken, out of service");
});
