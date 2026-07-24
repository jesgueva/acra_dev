import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config. Assumes the stack is already running:
 *   backend  — uvicorn app.main:app --port 8000
 *   frontend — npm run build && npm run start   (NOT `next dev`, see KI-02)
 *
 * Point the suite at a non-default stack with E2E_BASE_URL / E2E_API_URL. See e2e/README.md.
 */

/** The mobile flow (NFR-010) is the only spec that must run at a phone viewport. */
const MOBILE_SPEC = "**/ticket-21-mobile.spec.ts";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  // `list` for the terminal; `html` so the ticket's `npx playwright show-report` has a report to
  // open. `open: "never"` keeps CI and scripted runs from blocking on a spawned browser.
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 30_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: MOBILE_SPEC,
    },
    {
      // NFR-010. Split into its own project rather than `test.use(...)` inside the spec so the
      // viewport under test is declared once, visibly, and `--project=mobile` can select it.
      name: "mobile",
      use: { ...devices["iPhone 14"] },
      testMatch: MOBILE_SPEC,
    },
  ],
});
