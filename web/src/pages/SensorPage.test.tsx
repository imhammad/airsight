import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { answerByPath, renderAt } from "../test/render";
import { BROKEN, NO_READING, OCEANVIEW, RAW } from "../test/sensors";

afterEach(() => {
  vi.unstubAllGlobals();
});

const hourAgo = new Date(
  Math.floor(Date.now() / 3_600_000) * 3_600_000 - 3_600_000,
).toISOString();
const history = {
  data: [{ ...OCEANVIEW.latest_reading, observed_at: hourAgo }],
  next_cursor: null,
};

test("shows the reading, the sensor's own value and the model", async () => {
  answerByPath({
    "/v1/sensors/pa-27359": [200, OCEANVIEW],
    "/v1/sensors/pa-27359/history": [200, history],
  });

  renderAt("/sensors/pa-27359");

  expect(
    await screen.findByRole("heading", { name: "Oceanview Neighborhood Assn" }),
  ).toBeInTheDocument();
  expect(screen.getByText("PurpleAir sensor 27359")).toBeInTheDocument();
  expect(screen.getByText("9.1")).toBeInTheDocument();
  expect(screen.getByText("Moderate")).toBeInTheDocument();
  expect(screen.getByText("9.9")).toBeInTheDocument();
  expect(screen.getByText("airsight-correction v1")).toBeInTheDocument();
  expect(screen.getByText("Updated 40 min ago")).toBeInTheDocument();
  expect(
    await screen.findByRole("img", { name: /between 9\.1 and 9\.1/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /How accurate is this/ }),
  ).toHaveAttribute("href", "/accuracy");
});

test("asks for exactly the last 24 hours", async () => {
  const fetchMock = answerByPath({
    "/v1/sensors/pa-27359": [200, OCEANVIEW],
    "/v1/sensors/pa-27359/history": [200, history],
  });

  renderAt("/sensors/pa-27359");
  await screen.findByRole("img");

  const url = new URL(String(fetchMock.mock.calls[1][0]));
  const start = Date.parse(url.searchParams.get("start") ?? "");
  const end = Date.parse(url.searchParams.get("end") ?? "");
  expect(end - start).toBe(24 * 3_600_000);
  expect(end).toBeGreaterThan(Date.now());
});

test("an out-of-service sensor explains itself and skips the chart", async () => {
  const fetchMock = answerByPath({ "/v1/sensors/pa-1002": [200, BROKEN] });

  renderAt("/sensors/pa-1002");

  expect(await screen.findByText("Out of service")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("an unknown sensor says so", async () => {
  answerByPath({});

  renderAt("/sensors/pa-404");

  expect(
    await screen.findByRole("heading", { name: "Sensor not found" }),
  ).toBeInTheDocument();
});

test("a sensor showing raw explains why and keeps the corrected value", async () => {
  answerByPath({
    "/v1/sensors/pa-1003": [200, RAW],
    "/v1/sensors/pa-1003/history": [200, { data: [], next_cursor: null }],
  });

  renderAt("/sensors/pa-1003");

  expect(await screen.findByText("8.4")).toBeInTheDocument();
  expect(
    screen.getByText(/our correction has been less accurate/),
  ).toBeInTheDocument();
  expect(screen.getByText("Corrected value")).toBeInTheDocument();
  expect(screen.getByText("10.2")).toBeInTheDocument();
  expect(screen.queryByText("Sensor's own reading")).not.toBeInTheDocument();
});

test("a healthy sensor without a reading isn't called out of service", async () => {
  answerByPath({ "/v1/sensors/pa-1004": [200, NO_READING] });

  renderAt("/sensors/pa-1004");

  expect(await screen.findByText("No reading yet")).toBeInTheDocument();
  expect(screen.queryByText("Out of service")).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
