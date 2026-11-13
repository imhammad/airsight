import { expect, test } from "vitest";
import type { ForecastHour } from "../api/client";
import { summarize, upcoming } from "./forecast";

// 14:30 UTC on 9 November is 6:30 AM in the Bay Area
const NOW = Date.parse("2026-11-09T14:30:00Z");

const hour = (
  iso: string,
  p50: number,
  aqi_category = "good",
  p90 = p50 + 4,
): ForecastHour => ({
  target_time: iso,
  hours_ahead: 1,
  p10: Math.max(0, p50 - 3),
  p50,
  p90,
  aqi_category,
  outside_experience: false,
});

test("upcoming keeps the hour in progress and drops the hours already past", () => {
  const hours = [
    hour("2026-11-09T13:00:00Z", 5),
    hour("2026-11-09T14:00:00Z", 6),
    hour("2026-11-09T15:00:00Z", 7),
  ];

  expect(upcoming(hours, NOW).map((h) => h.target_time)).toEqual([
    "2026-11-09T14:00:00Z",
    "2026-11-09T15:00:00Z",
  ]);
});

test("a steady forecast names its category, its peak and how high it could get", () => {
  const hours = [
    hour("2026-11-09T15:00:00Z", 5.2),
    hour("2026-11-09T16:00:00Z", 7.9, "good", 12.1),
    hour("2026-11-09T17:00:00Z", 6.0),
  ];

  expect(summarize(hours)).toBe(
    "Most likely good throughout, highest around 8 AM at 7.9 µg/m³. It could reach 12.1.",
  );
});

test("each change of category is told in order, including a return", () => {
  const hours = [
    hour("2026-11-09T15:00:00Z", 6),
    hour("2026-11-09T16:00:00Z", 12.4, "moderate"),
    hour("2026-11-09T17:00:00Z", 11, "moderate"),
    hour("2026-11-09T18:00:00Z", 7),
  ];

  expect(summarize(hours)).toBe(
    "Most likely good, then moderate, then good, highest around 8 AM at 12.4 µg/m³. It could reach 16.4.",
  );
});
