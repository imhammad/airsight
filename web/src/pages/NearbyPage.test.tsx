import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { answerWith, renderAt } from "../test/render";

afterEach(() => {
  vi.unstubAllGlobals();
});

const BERKELEY = {
  sensor: {
    id: "pa-27359",
    name: "Oceanview Neighborhood Assn",
    latitude: 37.87204,
    longitude: -122.30109,
    health: "ok",
  },
  distance_km: 7.6,
  reading: {
    pm25_corrected: 9.1,
    pm25_raw: 9.9,
    aqi_category: "moderate",
    model_version: "airsight-correction/1",
    observed_at: "2026-11-07T05:00:00Z",
    stale: false,
  },
};

test("lists the nearest sensors with their corrected value and category", async () => {
  const fetchMock = answerWith(200, { data: [BERKELEY], next_cursor: null });

  renderAt("/");

  expect(
    await screen.findByText("Oceanview Neighborhood Assn"),
  ).toBeInTheDocument();
  expect(screen.getByText("9.1")).toBeInTheDocument();
  expect(screen.getByText("Moderate")).toBeInTheDocument();
  expect(screen.getByText(/7\.6 km away/)).toBeInTheDocument();
  const url = new URL(String(fetchMock.mock.calls[0][0]));
  expect(url.pathname).toBe("/v1/readings/nearest");
  expect(url.searchParams.get("limit")).toBe("20");
});

test("shows the API's explanation when a request fails", async () => {
  answerWith(
    503,
    {
      type: "about:blank",
      title: "Service Unavailable",
      status: 503,
      detail: "No model yet",
    },
    "application/problem+json",
  );

  renderAt("/");

  expect(await screen.findByRole("alert")).toHaveTextContent("No model yet");
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
});

test("says so when there are no sensors nearby", async () => {
  answerWith(200, { data: [], next_cursor: null });

  renderAt("/");

  expect(
    await screen.findByText("No sensors within 50 km."),
  ).toBeInTheDocument();
});
