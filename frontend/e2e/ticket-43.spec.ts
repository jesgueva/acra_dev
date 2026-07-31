import { expect, test } from "@playwright/test";
import { API, USERS, failOnPageErrors, login } from "./helpers/auth";

/**
 * ACR-43 / A8-3 — request correlation, asserted against the real stack.
 *
 * The unit tests prove the middleware sets and logs an id. What they cannot prove is that the id
 * survives the trip to a browser on a different origin: without `expose_headers` on CORS the
 * header is present on the wire but invisible to client JS, which quietly defeats the point of
 * handing a request id to someone reporting a problem.
 */

/** The frontend origin, which CORS must be configured to allow. */
const BROWSER_ORIGIN = process.env.E2E_BASE_URL ?? "http://localhost:3000";

test.describe("ACR-43 — request timing and correlation", () => {
  test("every API response carries a unique X-Request-ID", async ({ page }) => {
    failOnPageErrors(page);
    const missing: string[] = [];
    const ids: string[] = [];

    page.on("response", (response) => {
      const url = response.url();
      // Only the FastAPI origin — the Next.js auth proxy routes are a different server.
      if (!url.startsWith(API) || !url.includes("/api/v1/")) return;
      const id = response.headers()["x-request-id"];
      if (id) ids.push(id);
      else missing.push(`${response.request().method()} ${url}`);
    });

    await login(page, USERS.admin);
    await page.goto("/en/inventory");
    await page.waitForLoadState("networkidle");

    expect(missing, `API responses with no X-Request-ID: ${missing.join(", ")}`).toEqual([]);
    expect(ids.length, "the flow should have made at least one API call").toBeGreaterThan(0);
    expect(new Set(ids).size, "each request must get its own id").toBe(ids.length);
  });

  test("a client-supplied X-Request-ID is reused, not replaced", async ({ request }) => {
    const response = await request.get(`${API}/health`, {
      headers: { "X-Request-ID": "e2e-trace-43" },
    });

    expect(response.ok()).toBeTruthy();
    expect(response.headers()["x-request-id"]).toBe("e2e-trace-43");
  });

  test("generated ids are unique across requests", async ({ request }) => {
    const ids = new Set<string>();
    for (let i = 0; i < 5; i += 1) {
      const response = await request.get(`${API}/health`);
      ids.add(response.headers()["x-request-id"]);
    }
    expect(ids.size).toBe(5);
  });

  test("CORS exposes the id to browser JavaScript", async ({ request }) => {
    const response = await request.get(`${API}/health`, {
      headers: { Origin: BROWSER_ORIGIN },
    });

    const exposed = response.headers()["access-control-expose-headers"] ?? "";
    expect(
      exposed.toLowerCase(),
      "without this the header is on the wire but unreadable by the app",
    ).toContain("x-request-id");
  });
});
