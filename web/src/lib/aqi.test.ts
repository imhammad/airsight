import { expect, test } from "vitest";
import { CATEGORIES, category } from "./aqi";

test("every API category has a label, a colour and advice", () => {
  for (const key of [
    "good",
    "moderate",
    "unhealthy_sensitive",
    "unhealthy",
    "very_unhealthy",
    "hazardous",
  ]) {
    const found = category(key);
    expect(found.label).not.toBe("");
    expect(found.colour).toMatch(/^var\(--aqi-/);
    expect(found.advice).not.toBe("");
  }
  expect(Object.keys(CATEGORIES)).toHaveLength(6);
});

test("an unknown category fails loudly", () => {
  expect(() => category("purple")).toThrow("Unknown AQI category: purple");
});
