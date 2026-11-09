/**
 * The AirSight API, typed from docs/openapi.json.
 *
 * Every response type comes from the generated schema.ts, so when the API changes and the
 * types are regenerated (npm run api:types), the compiler shows every place that must follow.
 */
import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type Reading = Schemas["Reading"];
export type Sensor = Schemas["Sensor"];
export type SensorDetail = Schemas["SensorDetail"];
export type NearbyReading = Schemas["NearbyReading"];
export type ModelInfo = Schemas["ModelInfo"];
export type Accuracy = Schemas["Accuracy"];
export type Problem = Schemas["Problem"];

type Get<P extends keyof paths> = paths[P]["get"];
type Ok<P extends keyof paths> =
  Get<P> extends {
    responses: { 200: { content: { "application/json": infer Body } } };
  }
    ? Body
    : never;
type Query<P extends keyof paths> =
  Get<P> extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;

/** An error answer from the API, with its Problem Details (ADR 0008). */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;

  constructor(status: number, problem: Problem | null) {
    super(problem?.detail ?? `The API answered ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

// Same origin by default: Vite proxies /v1 in development
const BASE_URL: string = import.meta.env.VITE_API_URL ?? "";

async function get<P extends keyof paths>(
  path: string,
  query?: Record<string, string | number | null | undefined>,
): Promise<Ok<P>> {
  const url = new URL(BASE_URL + path, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null)
      url.searchParams.set(key, String(value));
  }
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const problem = response.headers.get("Content-Type")?.includes("json")
      ? ((await response.json()) as Problem)
      : null;
    throw new ApiError(response.status, problem);
  }
  return (await response.json()) as Ok<P>;
}

export const api = {
  nearest: (query: Query<"/v1/readings/nearest">) =>
    get<"/v1/readings/nearest">("/v1/readings/nearest", query),
  sensors: (query: Query<"/v1/sensors"> = {}) =>
    get<"/v1/sensors">("/v1/sensors", query),
  sensor: (sensorId: string) =>
    get<"/v1/sensors/{sensor_id}">(
      `/v1/sensors/${encodeURIComponent(sensorId)}`,
    ),
  history: (
    sensorId: string,
    query: Query<"/v1/sensors/{sensor_id}/history">,
  ) =>
    get<"/v1/sensors/{sensor_id}/history">(
      `/v1/sensors/${encodeURIComponent(sensorId)}/history`,
      query,
    ),
  model: () => get<"/v1/model">("/v1/model"),
  accuracy: (query: Query<"/v1/accuracy"> = {}) =>
    get<"/v1/accuracy">("/v1/accuracy", query),
};
