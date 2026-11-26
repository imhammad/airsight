// Takes the README screenshots from the live site: the map on a phone and the accuracy page on a
// laptop, in light and dark, each pair composed into one picture on the web app's own ground.
//
//   node scripts/readme/screenshots.mjs
//
// Run from the repo root. It uses the web app's Playwright (web/node_modules) and its Chromium
// (`npx playwright install chromium` in web/ if it is missing). Set AIRSIGHT_URL to shoot
// another copy of the site, such as http://localhost:8080.
import { writeFile } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const SITE = process.env.AIRSIGHT_URL ?? "https://airsight.tailbcc5c4.ts.net";
const OUT = new URL("../../docs/assets/readme/", import.meta.url);
const THEMES = {
  light: { ground: "#f6f5f2", line: "#e3e1dc" },
  dark: { ground: "#111315", line: "#2a2e32" },
};

async function shoot(browser, theme, path, viewport, mobile) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    colorScheme: theme,
    isMobile: mobile,
    hasTouch: mobile,
  });
  const page = await context.newPage();
  await page.goto(SITE + path, { waitUntil: "networkidle", timeout: 60_000 });
  // Map tiles and chart transitions settle after the network goes quiet
  await page.waitForTimeout(2_500);
  const png = await page.screenshot();
  await context.close();
  return `data:image/png;base64,${png.toString("base64")}`;
}

// A laptop window with the phone in front of it, bottom right
function compose(theme, laptop, phone) {
  const { ground, line } = THEMES[theme];
  const frame = `border:1px solid ${line};background-size:cover;background-position:top left;position:absolute`;
  const shadow = theme === "light" ? "0 12px 32px rgba(26,28,30,0.14)" : "0 12px 32px rgba(0,0,0,0.5)";
  return `
    <body style="margin:0;background:${ground}">
      <div style="position:relative;width:1200px;height:760px">
        <div style="${frame};left:40px;top:40px;width:1000px;height:625px;border-radius:12px;background-image:url(${laptop})"></div>
        <div style="${frame};left:900px;top:150px;width:260px;height:563px;border-radius:28px;box-shadow:${shadow};background-image:url(${phone})"></div>
      </div>
    </body>`;
}

const browser = await chromium.launch();
try {
  for (const theme of Object.keys(THEMES)) {
    const laptop = await shoot(browser, theme, "/accuracy", { width: 1280, height: 800 }, false);
    const phone = await shoot(browser, theme, "/", { width: 390, height: 844 }, true);
    const page = await browser.newPage({ viewport: { width: 1200, height: 760 }, deviceScaleFactor: 1.5 });
    await page.setContent(compose(theme, laptop, phone));
    const target = new URL(`screens-${theme}.jpg`, OUT);
    await writeFile(target, await page.screenshot({ type: "jpeg", quality: 88 }));
    await page.close();
    console.log(`wrote docs/assets/readme/screens-${theme}.jpg`);
  }
} finally {
  await browser.close();
}
