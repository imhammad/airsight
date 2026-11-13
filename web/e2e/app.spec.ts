import { expect, test, type Page } from "@playwright/test";

// The basemap comes from a third party (OpenFreeMap). These tests are about AirSight, so
// they get a plain background instead: no network, and the same picture on every run.
const BLANK_MAP = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "ground",
      type: "background",
      paint: { "background-color": "#e9e7e2" },
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.fulfill({ json: BLANK_MAP }),
  );
});

const panel = (page: Page) =>
  page.getByRole("complementary", { name: "Selected sensor" });
const marker = (page: Page, name: string) =>
  page.getByRole("button", { name: new RegExp(`^${name}`) });

test("opens on the sensor nearest downtown Oakland", async ({ page }) => {
  await page.goto("/");

  await expect(
    panel(page).getByRole("heading", { name: "Lake Merritt" }),
  ).toBeVisible();
  await expect(panel(page)).toContainText("Nearest sensor");
  await expect(panel(page)).toContainText("6.3");
  await expect(page.getByRole("list", { name: "Legend" })).toContainText(
    "Raw reading",
  );
});

test("tap a sensor on the map, then see its detail", async ({ page }) => {
  await page.goto("/");

  await marker(page, "West Oakland").click();
  await expect(
    panel(page).getByRole("heading", { name: "West Oakland" }),
  ).toBeVisible();
  await panel(page)
    .getByRole("link", { name: "See details and the last 24 hours" })
    .click();

  await expect(page).toHaveURL("/sensors/pa-1006");
  await expect(
    page.getByRole("heading", { name: "West Oakland" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Last 24 hours" }),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: /^Hourly PM2.5/ })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Next 24 hours" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /^Forecast PM2.5 for the next 23 hours/ }),
  ).toBeVisible();
});

test("a keyboard can pick a sensor, and a raw one says why", async ({
  page,
}) => {
  await page.goto("/");

  await marker(page, "Mission Dolores").focus();
  await page.keyboard.press("Enter");

  await expect(
    panel(page).getByRole("heading", { name: "Mission Dolores" }),
  ).toBeVisible();
  await expect(panel(page)).toContainText("This is the sensor's own reading.");
  await expect(marker(page, "Mission Dolores")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("the accuracy and about pages are one tap away", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });

  await nav.getByRole("link", { name: "Accuracy" }).click();
  await expect(
    page.getByRole("heading", {
      name: "How close are we to the official monitors?",
    }),
  ).toBeVisible();
  await expect(page.getByRole("list", { name: "Monitors" })).toContainText(
    "Showing raw",
  );

  await nav.getByRole("link", { name: "About" }).click();
  await expect(
    page.getByRole("heading", { name: "How AirSight works" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "When we show the raw reading" }),
  ).toBeVisible();
});

test("when the API can't be reached, it says so and can try again", async ({
  page,
}) => {
  await page.route("**/v1/readings/latest*", (route) => route.abort());
  await page.goto("/");

  // The app retries 3 times (about 7 seconds) before it gives up
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("We couldn't reach AirSight", {
    timeout: 15_000,
  });

  await page.unroute("**/v1/readings/latest*");
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(
    panel(page).getByRole("heading", { name: "Lake Merritt" }),
  ).toBeVisible();
});

test("an unknown address says the page wasn't found", async ({ page }) => {
  await page.goto("/no-such-page");

  await expect(
    page.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Back to the air near you" }).click();
  await expect(page).toHaveURL("/");
});

// Sideways scrolling on a phone means something is wider than the screen
for (const path of ["/", "/sensors/pa-1006", "/accuracy", "/about"]) {
  test(`${path} fits the screen without scrolling sideways`, async ({
    page,
  }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
}
