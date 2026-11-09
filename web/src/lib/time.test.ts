import { expect, test } from "vitest";
import { ago, bayAreaHour, startOfHour } from "./time";

const NOW = Date.parse("2026-11-09T12:00:00Z");

test.each([
  ["2026-11-09T12:00:00Z", "just now"],
  ["2026-11-09T11:20:00Z", "40 min ago"],
  ["2026-11-09T09:00:00Z", "3 h ago"],
  ["2026-11-07T12:00:00Z", "2 days ago"],
])("%s reads as %s", (iso, expected) => {
  expect(ago(iso, NOW)).toBe(expected);
});

test("hours start on the hour", () => {
  expect(startOfHour(Date.parse("2026-11-09T12:34:56Z"))).toBe(
    Date.parse("2026-11-09T12:00:00Z"),
  );
});

test("hours read in Bay Area time, wherever you are", () => {
  // 14:00 UTC is 6 AM in California in November (PST, UTC-8)
  expect(bayAreaHour(Date.parse("2026-11-09T14:00:00Z"))).toBe("6 AM");
});
