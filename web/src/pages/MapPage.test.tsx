import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { SensorMapProps } from "../components/SensorMap";
import { answerWith, renderAt } from "../test/render";
import { BROKEN, LAKE_MERRITT, OCEANVIEW } from "../test/sensors";

// MapLibre needs WebGL, which jsdom lacks; its own test covers it. Here each marker is a button.
vi.mock("../components/SensorMap", () => ({
  default: ({ sensors, onSelect }: SensorMapProps) => (
    <div>
      {sensors.map((sensor) => (
        <button key={sensor.id} onClick={() => onSelect(sensor.id)}>
          Marker {sensor.name}
        </button>
      ))}
    </div>
  ),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const page = { data: [OCEANVIEW, BROKEN, LAKE_MERRITT], next_cursor: null };

test("shows the nearest working sensor to downtown Oakland first", async () => {
  const fetchMock = answerWith(200, page);

  renderAt("/");

  expect(
    await screen.findByRole("heading", { name: "Lake Merritt" }),
  ).toBeInTheDocument();
  expect(screen.getByText("6.3")).toBeInTheDocument();
  expect(screen.getAllByText("Good").length).toBeGreaterThan(0); // badge and legend
  expect(
    screen.getByText(/Nearest sensor · 1\.3 km from downtown Oakland/),
  ).toBeInTheDocument();
  expect(screen.getByText("Updated 40 min ago")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "See details and the last 24 hours" }),
  ).toHaveAttribute("href", "/sensors/pa-1001");
  expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe(
    "/v1/readings/latest",
  );
});

test("choosing a marker shows that sensor", async () => {
  answerWith(200, page);
  renderAt("/");

  fireEvent.click(
    await screen.findByText("Marker Oceanview Neighborhood Assn"),
  );

  expect(
    screen.getByRole("heading", { name: "Oceanview Neighborhood Assn" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/^Sensor · 7\.\d km from/)).toBeInTheDocument();
  expect(screen.getByText(/take it easier/)).toBeInTheDocument();
});

test("an out-of-service sensor says why it has no value", async () => {
  answerWith(200, page);
  renderAt("/");

  fireEvent.click(await screen.findByText("Marker Broken"));

  expect(screen.getByText(/found this sensor unreliable/)).toBeInTheDocument();
  expect(screen.getByText("Out of service")).toBeInTheDocument(); // in the legend
});

test("your location picks the sensor nearest to you", async () => {
  answerWith(200, page);
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: {
      getCurrentPosition: (success: PositionCallback) =>
        success({
          coords: { latitude: 37.8716, longitude: -122.2727 }, // Berkeley
        } as GeolocationPosition),
    },
  });
  renderAt("/");

  await screen.findByRole("heading", { name: "Lake Merritt" });
  fireEvent.click(screen.getByRole("button", { name: "Use my location" }));

  expect(
    await screen.findByRole("heading", { name: "Oceanview Neighborhood Assn" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/km from you/)).toBeInTheDocument();
});

test("says so when you don't share your location", async () => {
  answerWith(200, page);
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: {
      getCurrentPosition: (
        _success: PositionCallback,
        failure: PositionErrorCallback,
      ) => failure({ code: 1 } as GeolocationPositionError),
    },
  });
  renderAt("/");

  await screen.findByRole("heading", { name: "Lake Merritt" });
  fireEvent.click(screen.getByRole("button", { name: "Use my location" }));

  expect(screen.getByRole("status")).toHaveTextContent(
    "We couldn't get your location",
  );
  expect(
    screen.getByRole("heading", { name: "Lake Merritt" }),
  ).toBeInTheDocument();
});

test("shows the API's explanation when loading fails", async () => {
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
});

test("says so when you are outside the Bay Area", async () => {
  answerWith(200, page);
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: {
      getCurrentPosition: (success: PositionCallback) =>
        success({
          coords: { latitude: 3.139, longitude: 101.6869 }, // Kuala Lumpur
        } as GeolocationPosition),
    },
  });
  renderAt("/");

  await screen.findByRole("heading", { name: "Lake Merritt" });
  fireEvent.click(screen.getByRole("button", { name: "Use my location" }));

  expect(screen.getByRole("status")).toHaveTextContent(
    "AirSight covers the San Francisco Bay Area",
  );
  expect(
    screen.getByRole("heading", { name: "Lake Merritt" }),
  ).toBeInTheDocument();
});

test("choosing a sensor clears the location message", async () => {
  answerWith(200, page);
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: {
      getCurrentPosition: (
        _success: PositionCallback,
        failure: PositionErrorCallback,
      ) => failure({ code: 1 } as GeolocationPositionError),
    },
  });
  renderAt("/");
  await screen.findByRole("heading", { name: "Lake Merritt" });
  fireEvent.click(screen.getByRole("button", { name: "Use my location" }));
  expect(screen.getByRole("status")).toBeInTheDocument();

  fireEvent.click(screen.getByText("Marker Oceanview Neighborhood Assn"));

  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
