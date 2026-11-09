import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { answerWith, renderAt } from "./test/render";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("every page has the wordmark and the main navigation", async () => {
  answerWith(200, { data: [], next_cursor: null });

  renderAt("/");

  expect(screen.getByRole("link", { name: "AirSight" })).toBeInTheDocument();
  const nav = screen.getByRole("navigation", { name: "Main" });
  expect(nav).toHaveTextContent("Nearby");
  expect(nav).toHaveTextContent("Accuracy");
  expect(nav).toHaveTextContent("About");
});

test("an unknown path shows a page not found message", () => {
  renderAt("/no-such-page");

  expect(
    screen.getByRole("heading", { name: "Page not found" }),
  ).toBeInTheDocument();
});
