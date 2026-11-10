import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { answerByPath, renderAt } from "../test/render";

afterEach(() => {
  vi.unstubAllGlobals();
});

const model = {
  name: "airsight-correction",
  version: 1,
  model_version: "airsight-correction/1",
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

test("explains the method with the current model's own numbers", async () => {
  answerByPath({ "/v1/model": [200, model] });

  renderAt("/about");

  expect(
    screen.getByRole("heading", { name: "How AirSight works" }),
  ).toBeInTheDocument();
  expect(await screen.findByText("airsight-correction v1")).toBeInTheDocument();
  expect(screen.getByText("2.50 µg/m³")).toBeInTheDocument();
  expect(screen.getByText("2.87 µg/m³")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Read the model card" }),
  ).toHaveAttribute("href", model.model_card);
  const page = within(screen.getByRole("article"));
  expect(page.getByRole("link", { name: "Accuracy" })).toHaveAttribute(
    "href",
    "/accuracy",
  );
});

test("still explains the method when no model is available", async () => {
  const fetchMock = answerByPath({});

  renderAt("/about");

  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(
    screen.getByRole("heading", { name: "When we show the raw reading" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Current model")).not.toBeInTheDocument();
});
