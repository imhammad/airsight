import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { ForecastHour } from "../api/client";
import { ForecastChart } from "./ForecastChart";

const hour = (
  iso: string,
  p10: number,
  p50: number,
  p90: number,
  aqi_category = "good",
): ForecastHour => ({
  target_time: iso,
  hours_ahead: 1,
  p10,
  p50,
  p90,
  aqi_category,
  outside_experience: false,
});

test("draws a column per hour with its range and most likely value", () => {
  const { container } = render(
    <ForecastChart
      hours={[
        hour("2026-11-09T15:00:00Z", 3, 6, 9),
        hour("2026-11-09T16:00:00Z", 4.8, 9.6, 14.4, "moderate"),
        hour("2026-11-09T17:00:00Z", 2, 5, 8),
      ]}
    />,
  );

  const chart = screen.getByRole("img");
  expect(chart).toHaveAccessibleName(
    "Forecast PM2.5 for the next 3 hours, most likely between 5.0 and 9.6 µg/m³",
  );
  expect(chart.children).toHaveLength(3);
  const column = screen.getByTitle(
    "8 AM: most likely 9.6, likely 4.8 to 14.4 µg/m³",
  );
  // The highest p90 sets the scale: 14.4 is the top of the chart
  const [range, median] = Array.from(column.children);
  expect(range).toHaveStyle({
    bottom: "33.33333333333333%",
    height: "66.66666666666667%",
  });
  expect(median).toHaveStyle({ bottom: "66.66666666666666%" });
  expect(container.querySelector("figcaption")).toHaveTextContent(
    "7 AM8 AM9 AM",
  );
});

test("a clean forecast doesn't fill the chart", () => {
  render(<ForecastChart hours={[hour("2026-11-09T15:00:00Z", 2, 4, 6)]} />);

  // 6 on a scale that never goes below 12
  const [range] = Array.from(
    screen.getByTitle("7 AM: most likely 4.0, likely 2.0 to 6.0 µg/m³")
      .children,
  );
  expect(range).toHaveStyle({ height: "33.33333333333333%" });
});
