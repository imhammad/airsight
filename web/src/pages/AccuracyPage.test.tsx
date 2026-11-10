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

test("compares the correction with raw and the EPA correction", async () => {
  const fetchMock = answerByPath({ "/v1/accuracy": [200, accuracy] });

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
  answerByPath({ "/v1/accuracy": [200, accuracy] });

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
  });

  renderAt("/accuracy");

  expect(
    await screen.findByText(/No hours have been scored/),
  ).toBeInTheDocument();
  expect(screen.queryByText("By monitor")).not.toBeInTheDocument();
});
