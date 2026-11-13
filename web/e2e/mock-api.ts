/**
 * A stand-in for the AirSight API, for the end-to-end tests and Lighthouse (issue #93).
 *
 * `npm run preview:mock` serves the built app with this plugin, so the browser checks run
 * without the database or the model. The answers are typed from docs/openapi.json, so when
 * the API changes, `tsc` shows where this stand-in must follow.
 */
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import type { components } from "../src/api/schema.d.ts";

type Schemas = components["schemas"];
type SensorDetail = Schemas["SensorDetail"];
type Reading = Schemas["Reading"];

const MODEL = "airsight-correction/1";
const HOUR = 3_600_000;

/** The start of the current hour, minus `hours`, as the API writes times. */
function hoursAgo(hours: number): string {
  return new Date(
    Math.floor(Date.now() / HOUR) * HOUR - hours * HOUR,
  ).toISOString();
}

function reading(pm25: number, overrides: Partial<Reading> = {}): Reading {
  return {
    pm25,
    source: "corrected",
    pm25_corrected: pm25,
    pm25_raw: pm25 + 0.8,
    aqi_category: pm25 <= 9 ? "good" : "moderate",
    model_version: MODEL,
    observed_at: hoursAgo(0),
    stale: false,
    ...overrides,
  };
}

/** The sensors on the map, one for each state a marker can show. Times are made per request. */
function sensors(): SensorDetail[] {
  return [
    {
      // Closest to downtown Oakland, so the map starts on it
      id: "pa-1001",
      name: "Lake Merritt",
      latitude: 37.8021,
      longitude: -122.2585,
      health: "ok",
      latest_reading: reading(6.3),
    },
    {
      // Close enough to downtown to be on screen on a phone, so the tests can tap it
      id: "pa-1006",
      name: "West Oakland",
      latitude: 37.814,
      longitude: -122.283,
      health: "ok",
      latest_reading: reading(9.8),
    },
    {
      // Near a monitor where the correction has been losing, so it shows its own reading
      id: "pa-1003",
      name: "Mission Dolores",
      latitude: 37.7599,
      longitude: -122.4269,
      health: "ok",
      latest_reading: reading(8.4, {
        source: "raw",
        pm25_corrected: 10.2,
        pm25_raw: 8.4,
      }),
    },
    {
      id: "pa-1005",
      name: "Fruitvale",
      latitude: 37.7748,
      longitude: -122.2241,
      health: "ok",
      latest_reading: reading(7.1, { observed_at: hoursAgo(8), stale: true }),
    },
    {
      id: "pa-1002",
      name: "Jack London Square",
      latitude: 37.7955,
      longitude: -122.2776,
      health: "excluded",
      latest_reading: null,
    },
  ];
}

function history(sensor: SensorDetail): Schemas["ReadingPage"] {
  const latest = sensor.latest_reading;
  const data = latest
    ? Array.from({ length: 24 }, (_, index) => {
        const hours = 23 - index;
        // A gentle daily curve, so the chart has something to draw
        const pm25 =
          Math.round((latest.pm25 + 2 * Math.sin(index / 4)) * 10) / 10;
        return {
          ...latest,
          pm25,
          pm25_corrected: pm25,
          observed_at: hoursAgo(hours),
        };
      })
    : [];
  return { data, next_cursor: null };
}

/** A forecast issued 2 hours ago, rising into the evening, for sensors with a reading. */
function forecast(sensor: SensorDetail): Schemas["Forecast"] | null {
  const latest = sensor.latest_reading;
  if (!latest) return null;
  return {
    sensor_id: sensor.id,
    issued_at: hoursAgo(2),
    model_version: "airsight-forecast/1",
    stale: false,
    hours: Array.from({ length: 24 }, (_, index) => {
      const p50 = Math.round((latest.pm25 + 3 * Math.sin(index / 5)) * 10) / 10;
      return {
        target_time: hoursAgo(1 - index),
        hours_ahead: index + 1,
        p10: Math.round(Math.max(0, p50 - 3 - index / 8) * 10) / 10,
        p50,
        p90: Math.round((p50 + 4 + index / 6) * 10) / 10,
        aqi_category: p50 <= 9 ? "good" : "moderate",
        outside_experience: false,
      };
    }),
  };
}

const model: Schemas["ModelInfo"] = {
  name: "airsight-correction",
  version: 1,
  model_version: MODEL,
  dataset: "f5a557c189d5",
  trained_before: "2026-10-23T00:00:00Z",
  promoted_at: "2026-11-06T10:00:00Z",
  final_test: {
    headline_mae: 2.5,
    raw_headline_mae: 2.87,
    epa_headline_mae: 3.42,
    hours: 3021,
  },
  model_card:
    "https://github.com/imhammad/airsight/blob/main/docs/model-cards/airsight-correction-v1.md",
};

function station(
  name: string,
  corrected: number,
  raw: number,
  source: Schemas["StationAccuracy"]["source"],
): Schemas["StationAccuracy"] {
  return {
    station: name,
    sensors: 3,
    hours: 900,
    mae: { corrected, raw, epa: 3.6 },
    bias: 0.4,
    source,
  };
}

function accuracy(): Schemas["Accuracy"] {
  return {
    model_version: MODEL,
    start: hoursAgo(14 * 24),
    end: hoursAgo(0),
    hours: 2700,
    headline_mae: { corrected: 2.49, raw: 3.06, epa: 3.6 },
    stations: [
      station("Berkeley Aquatic Park", 2.31, 3.02, "corrected"),
      station("Oakland West", 2.52, 3.36, "corrected"),
      station("San Francisco", 2.92, 2.14, "raw"),
    ],
  };
}

function problem(status: number, title: string): Schemas["Problem"] {
  return { type: "about:blank", title, status, detail: title, errors: null };
}

/** The status and body for one API path; a path we don't know is a 404. */
function answer(path: string): [number, unknown] {
  const all = sensors();
  if (path === "/v1/readings/latest")
    return [200, { data: all, next_cursor: null }];
  if (path === "/v1/model") return [200, model];
  if (path === "/v1/accuracy") return [200, accuracy()];
  const match = /^\/v1\/sensors\/([^/]+)(\/history|\/forecast)?$/.exec(path);
  const sensor =
    match && all.find((item) => item.id === decodeURIComponent(match[1]));
  if (sensor && match[2] === "/forecast") {
    const body = forecast(sensor);
    return body ? [200, body] : [404, problem(404, "No forecast")];
  }
  if (sensor) return [200, match[2] ? history(sensor) : sensor];
  return [404, problem(404, "Not found")];
}

function serve(
  request: IncomingMessage,
  response: ServerResponse,
  next: () => void,
) {
  const url = new URL(request.url ?? "/", "http://localhost");
  if (!url.pathname.startsWith("/v1/")) return next();
  const [status, body] = answer(url.pathname);
  response.statusCode = status;
  response.setHeader(
    "Content-Type",
    status === 200 ? "application/json" : "application/problem+json",
  );
  response.end(JSON.stringify(body));
}

/** Answers /v1 requests in `vite preview`, in place of the real API. */
export function mockApi(): Plugin {
  return {
    name: "airsight-mock-api",
    configurePreviewServer(server) {
      server.middlewares.use(serve);
    },
  };
}
