import { expect, test } from "vitest";
import { closest, distanceKm } from "./geo";

const OAKLAND = { lat: 37.8053, lon: -122.2725 };
const SAN_FRANCISCO = { lat: 37.7749, lon: -122.4194 };

test("measures the distance between two places", () => {
  // About 13.3 km across the bay
  expect(distanceKm(OAKLAND, SAN_FRANCISCO)).toBeCloseTo(13.3, 1);
  expect(distanceKm(OAKLAND, OAKLAND)).toBe(0);
});

test("finds the closest place", () => {
  const berkeley = { lat: 37.8716, lon: -122.2727, name: "Berkeley" };
  const sf = { ...SAN_FRANCISCO, name: "San Francisco" };

  expect(closest([sf, berkeley], OAKLAND)?.name).toBe("Berkeley");
  expect(closest([], OAKLAND)).toBeUndefined();
});
