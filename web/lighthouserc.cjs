// Lighthouse CI (issue #93): audits the production build with the stand-in API, as a phone.
// Run it with `npm run lighthouse` after `npm run build` (npm run e2e builds too).
const { chromium } = require("@playwright/test");

const PAGES = ["/", "/sensors/pa-1001", "/accuracy", "/about"];

module.exports = {
  ci: {
    collect: {
      startServerCommand: "npm run preview:mock",
      startServerReadyPattern: "Local",
      url: PAGES.map((path) => `http://localhost:4173${path}`),
      numberOfRuns: 1,
      // The Chromium Playwright installed, so the audit is the same on every machine
      chromePath: chromium.executablePath(),
      // Like Playwright, run Chromium without its sandbox: CI's Ubuntu blocks it, and we
      // only ever open our own pages
      settings: { chromeFlags: "--no-sandbox" },
    },
    assert: {
      assertions: {
        // ADR 0009's bar is accessibility 90+; best practices and SEO are held to it too
        "categories:accessibility": ["error", { minScore: 0.9 }],
        "categories:best-practices": ["error", { minScore: 0.9 }],
        "categories:seo": ["error", { minScore: 0.9 }],
        // One run on a shared CI machine is noisy, so speed warns instead of failing
        "categories:performance": ["warn", { minScore: 0.8 }],
      },
    },
    upload: {
      target: "filesystem",
      outputDir: ".lighthouseci",
    },
  },
};
