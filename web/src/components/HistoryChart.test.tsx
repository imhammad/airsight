import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Reading } from "../api/client";
import { HistoryChart } from "./HistoryChart";

// 14:30 UTC on 9 November is 6:30 AM in the Bay Area
const NOW = Date.parse("2026-11-09T14:30:00Z");

const reading = (iso: string, pm25: number, category: string): Reading => ({
  pm25_corrected: pm25,
  pm25_raw: pm25 + 1,
  aqi_category: category,
  model_version: "airsight-correction/1",
  observed_at: iso,
  stale: false,
});

test("draws one slot per hour and a bar for each reading", () => {
  const { container } = render(
    <HistoryChart
      now={NOW}
      readings={[
        reading("2026-11-08T15:00:00Z", 4.2, "good"),
        reading("2026-11-09T13:00:00Z", 10.4, "moderate"),
      ]}
    />,
  );

  const chart = screen.getByRole("img");
  expect(chart).toHaveAccessibleName(
    "Hourly PM2.5 over the last 24 hours, between 4.2 and 10.4 µg/m³",
  );
  expect(chart.children).toHaveLength(24);
  expect(screen.getByTitle("5 AM: 10.4 µg/m³")).toBeInTheDocument();
  expect(screen.getByTitle("7 AM: 4.2 µg/m³")).toBeInTheDocument();
  expect(container.querySelector("figcaption")).toHaveTextContent(
    "7 AM7 PMNow",
  );
});

test("a clean day doesn't fill the chart", () => {
  render(
    <HistoryChart
      now={NOW}
      readings={[reading("2026-11-09T14:00:00Z", 6, "good")]}
    />,
  );

  // 6 on a scale that never goes below 12
  expect(screen.getByTitle("6 AM: 6.0 µg/m³")).toHaveStyle({ height: "50%" });
});

test("says so when there are no readings", () => {
  render(<HistoryChart now={NOW} readings={[]} />);

  expect(screen.getByRole("img")).toHaveAccessibleName(
    "No readings in the last 24 hours",
  );
});
