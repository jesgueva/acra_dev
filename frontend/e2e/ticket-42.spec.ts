import { expect, test, type ConsoleMessage, type Request } from "@playwright/test";
import { API_URL, USERS, login } from "./helpers";

/**
 * ACR-42 — the containerized stack serves the app correctly (A10-1 / A10-4).
 *
 * Written to run against the Docker Compose stack:
 *
 *   docker compose up -d --build
 *   docker compose --profile seed run --rm seed
 *   npx playwright test e2e/ticket-42.spec.ts
 *
 * It also passes against the host-process stack (`uvicorn` + `npm run build && npm run start`),
 * because every assertion here is about a *production* build rather than about Docker specifically.
 * That is deliberate: the point of A10-1 is that the containerized stack behaves identically to the
 * documented local one, so a spec that only passed under Docker would be testing the wrong thing.
 *
 * Never run this against `next dev` — see KI-02.
 *
 * Point at a non-default stack with E2E_BASE_URL / E2E_API_URL, as the other specs do.
 */

/** Chunk requests are noisy and irrelevant here; we care about API and document responses. */
const isServerError = (status: number) => status >= 500;

test.describe("ACR-42 containerized stack", () => {
  test("serves the login page and authenticates end to end", async ({ page }) => {
    const serverErrors: string[] = [];
    page.on("response", (response) => {
      if (isServerError(response.status())) {
        serverErrors.push(`${response.status()} ${response.url()}`);
      }
    });

    await login(page, USERS.admin.username, USERS.admin.password);

    // Landed somewhere authenticated rather than bounced back to /login.
    await expect(page).not.toHaveURL(/\/login$/);
    expect(serverErrors, `5xx responses during login: ${serverErrors.join(", ")}`).toEqual([]);
  });

  test("the browser talks to the host-published API, not a compose-internal hostname", async ({
    page,
  }) => {
    // The regression this guards: NEXT_PUBLIC_API_URL is inlined into the browser bundle at BUILD
    // time. If the image were built with the compose service name, the stack would come up
    // perfectly healthy and every XHR would fail on a hostname the browser cannot resolve.
    const apiRequests: string[] = [];
    page.on("request", (request: Request) => {
      const url = request.url();
      if (url.includes("/api/v1/")) apiRequests.push(url);
    });

    await login(page, USERS.admin.username, USERS.admin.password);
    await page.waitForLoadState("networkidle");

    expect(apiRequests.length, "expected the page to call the API at least once").toBeGreaterThan(0);

    const internal = apiRequests.filter((url) => /:\/\/(backend|db):/.test(url));
    expect(internal, `browser requested compose-internal hostnames: ${internal.join(", ")}`)
      .toEqual([]);

    for (const url of apiRequests) {
      expect(url.startsWith(API_URL), `${url} does not start with ${API_URL}`).toBeTruthy();
    }
  });

  test("renders both locales without console errors", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (message: ConsoleMessage) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    for (const locale of ["en", "es"] as const) {
      const response = await page.goto(`/${locale}/login`);
      expect(response?.status(), `/${locale}/login status`).toBe(200);
      await expect(page.locator("#username")).toBeVisible();
      await expect(page.locator("#password")).toBeVisible();
    }

    expect(consoleErrors, `console errors: ${consoleErrors.join(" | ")}`).toEqual([]);
  });

  test("static assets served by the standalone server actually resolve", async ({ page }) => {
    // `output: "standalone"` does not include .next/static or public/ in its dependency trace —
    // they are copied in separately by the Dockerfile. Miss that COPY and the page renders while
    // every asset 404s, which looks like a styling bug rather than a packaging one.
    const notFound: string[] = [];
    page.on("response", (response) => {
      const url = response.url();
      if (response.status() === 404 && (url.includes("/_next/") || url.includes("/static/"))) {
        notFound.push(url);
      }
    });

    await page.goto("/en/login");
    await page.waitForLoadState("networkidle");

    expect(notFound, `static assets 404ed: ${notFound.join(", ")}`).toEqual([]);
  });

  test("the API rejects anonymous reads", async ({ request }) => {
    // Containerizing must not accidentally relax auth — e.g. by losing an env var and falling back
    // to a permissive default.
    const response = await request.get(`${API_URL}/api/v1/inventory`);
    expect([401, 403]).toContain(response.status());
  });

  test("the backend health endpoint is reachable", async ({ request }) => {
    const response = await request.get(`${API_URL}/health`);
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ status: "ok" });
  });
});
