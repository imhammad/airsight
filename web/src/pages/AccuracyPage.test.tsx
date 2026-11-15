import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { answerByPath, renderAt } from "../test/render";

afterEach(() => {
  vi.unstubAllGlobals();
});

const station = (
  name: string,
  corrected: number,
  raw: number,
  source: "corrected" | "raw",
) => ({
  station: name,
  sensors: 2,
  hours: 300,
  mae: { corrected, raw, epa: 3.6 },
  bias: 0.4,
  source,
});

const accuracy = {
  model_version: "airsight-correction/1",
  start: "2026-10-27T05:00:00Z",
  end: "2026-11-10T05:00:00Z",
  hours: 3550,
  headline_mae: { corrected: 2.77, raw: 3.11, epa: 3.6 },
  stations: [
    station("Oakland West", 2.52, 3.36, "corrected"),
    station("San Rafael", 2.92, 2.14, "raw"),
  ],
};

const errors = (forecast: number | null, persistence: number | null) => ({
  forecast,
  persistence,
  same_hour_yesterday: forecast === null ? null : 3.9,
});

const forecastAccuracy = {
  model_version: "airsight-forecast/1",
  start: "2026-11-03T05:00:00Z",
  end: "2026-11-10T05:00:00Z",
  hours: 1200,
  headline_mae: errors(2.71, 3.18),
  coverage: 0.79,
  by_horizon: [
    { hours_ahead: "1-6", hours: 300, mae: errors(2.38, 2.61), coverage: 0.8 },
    {
      hours_ahead: "7-12",
      hours: 300,
      mae: errors(2.74, 3.27),
      coverage: 0.79,
    },
    {
      hours_ahead: "13-24",
      hours: 600,
      mae: errors(2.86, 3.42),
      coverage: 0.78,
    },
  ],
  stations: [
    {
      station: "Oakland West",
      sensors: 2,
      hours: 1200,
      mae: errors(2.71, 3.18),
      coverage: 0.79,
    },
  ],
};

const noForecastYet = {
  ...forecastAccuracy,
  model_version: null,
  hours: 0,
  headline_mae: errors(null, null),
  coverage: null,
  by_horizon: [],
  stations: [],
};

test("compares the correction with raw and the EPA correction", async () => {
  const fetchMock = answerByPath({
    "/v1/accuracy": [200, accuracy],
    "/v1/accuracy/forecast": [200, forecastAccuracy],
  });

  renderAt("/accuracy");

  expect(
    await screen.findByRole("heading", {
      name: "How close are we to the official monitors?",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Last 14 days · 3,550 hours · 2 official monitors"),
  ).toBeInTheDocument();
  expect(screen.getByText("2.77")).toBeInTheDocument();
  expect(screen.getByText("3.11")).toBeInTheDocument();
  expect(screen.getByText("3.60")).toBeInTheDocument();
  const url = new URL(String(fetchMock.mock.calls[0][0]));
  expect(url.searchParams.get("days")).toBe("14"); // the raw fallback's window
});

test("lists each monitor with what the map shows there", async () => {
  answerByPath({
    "/v1/accuracy": [200, accuracy],
    "/v1/accuracy/forecast": [200, forecastAccuracy],
  });

  renderAt("/accuracy");

  expect(
    await screen.findByText("Better than raw at 1 of 2"),
  ).toBeInTheDocument();
  const rows = within(
    screen.getByRole("list", { name: "Monitors" }),
  ).getAllByRole("listitem");
  expect(rows[0]).toHaveTextContent("Oakland West");
  expect(rows[0]).toHaveTextContent("Corrected");
  expect(rows[1]).toHaveTextContent("San Rafael");
  expect(rows[1]).toHaveTextContent("2.92 corrected · 2.14 raw");
  expect(rows[1]).toHaveTextContent("Showing raw");
});

test("says so when nothing has been scored yet", async () => {
  answerByPath({
    "/v1/accuracy": [
      200,
      {
        ...accuracy,
        hours: 0,
        headline_mae: { corrected: null, raw: null, epa: null },
        stations: [],
      },
    ],
    "/v1/accuracy/forecast": [200, noForecastYet],
  });

  renderAt("/accuracy");

  expect(
    await screen.findByText(/No hours have been scored/),
  ).toBeInTheDocument();
  expect(screen.queryByText("By monitor")).not.toBeInTheDocument();
  expect(
    await screen.findByText(/No forecast hours have been scored/),
  ).toBeInTheDocument();
});

test("scores the forecast against two guesses that need no model", async () => {
  const fetchMock = answerByPath({
    "/v1/accuracy": [200, accuracy],
    "/v1/accuracy/forecast": [200, forecastAccuracy],
  });

  renderAt("/accuracy");

  expect(
    await screen.findByText(
      "Last 7 days · 1,200 forecast hours · 1 official monitor",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("2.71")).toBeInTheDocument();
  expect(screen.getByText("3.18")).toBeInTheDocument();
  expect(screen.getByText("79%")).toBeInTheDocument();
  const rows = within(
    screen.getByRole("list", { name: "Forecast by hours ahead" }),
  ).getAllByRole("listitem");
  expect(rows.map((row) => row.textContent)).toEqual([
    "1 to 6 hours ahead2.38 forecast · 2.61 unchangedRange held 80%",
    "7 to 12 hours ahead2.74 forecast · 3.27 unchangedRange held 79%",
    "13 to 24 hours ahead2.86 forecast · 3.42 unchangedRange held 78%",
  ]);
  const forecastCall = fetchMock.mock.calls
    .map(([input]) => new URL(String(input)))
    .find((url) => url.pathname === "/v1/accuracy/forecast");
  expect(forecastCall?.searchParams.get("days")).toBe("7");
});

test("the correction scores still show when the forecast score fails", async () => {
  answerByPath({
    "/v1/accuracy": [200, accuracy],
    "/v1/accuracy/forecast": [
      500,
      { type: "about:blank", title: "Error", status: 500, detail: "Boom" },
    ],
  });

  renderAt("/accuracy");

  expect(
    await screen.findByText("Better than raw at 1 of 2"),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: /try again/i }),
  ).toBeInTheDocument();
});
