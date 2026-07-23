import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config. Assumes the stack is already running:
 *   backend  — uvicorn app.main:app --port 8000
 *   frontend — npm run build && npm run start   (NOT `next dev`, see KI-02)
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
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
    },
  ],
});
