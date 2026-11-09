import { expect, test } from "vitest";
import { ago } from "./time";

const NOW = Date.parse("2026-11-09T12:00:00Z");

test.each([
  ["2026-11-09T12:00:00Z", "just now"],
  ["2026-11-09T11:20:00Z", "40 min ago"],
  ["2026-11-09T09:00:00Z", "3 h ago"],
  ["2026-11-07T12:00:00Z", "2 days ago"],
])("%s reads as %s", (iso, expected) => {
  expect(ago(iso, NOW)).toBe(expected);
});
