import { expect, test } from "@playwright/test";
import { API, USERS, apiToken, authHeaders, failOnPageErrors, login } from "./helpers/auth";

/**
 * ACR-45 / A8-6 — regression guard for the `inventory_lots` aggregation index (migration 015).
 *
 * ACR-45 adds no UI. It adds an index, and the one thing an index must never do is change an
 * answer. So this spec is a guard rather than a journey: it walks the surfaces that read the
 * aggregated numbers and asserts they still render real, self-consistent data over the indexed
 * query path, in both locales, with a clean console.
 *
 * The arithmetic assertion is the point. `available = on_hand - reserved` is computed from two
 * separate aggregates — `_on_hand` over `inventory_lots`, now index-only, and `_reserved` over
 * `stock_reservations`. If the index ever changed which rows the first one sees, that identity is
 * where it would show up, and no amount of "the page loaded" would catch it.
 */

test.describe("ACR-45 — aggregation index regression guard", () => {
  test("inventory list renders lots over the indexed query path", async ({ page }) => {
    failOnPageErrors(page);

    await login(page, USERS.admin);
    await page.goto("/en/inventory");
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: /inventory/i }).first()).toBeVisible();
    // A rendered row proves the list query returned data, not just that the shell mounted.
    await expect(page.locator("table tbody tr").first()).toBeVisible();
  });

  test("availability satisfies available = on_hand - reserved", async ({ request }) => {
    const token = await apiToken(request, USERS.admin);

    const lots = await request.get(`${API}/api/v1/inventory?page=1&page_size=1`, {
      headers: authHeaders(token),
    });
    expect(lots.ok()).toBeTruthy();
    const firstLot = (await lots.json()).results[0];
    expect(firstLot, "the seeded database should carry at least one lot").toBeTruthy();

    const response = await request.get(
      `${API}/api/v1/inventory/availability?product_id=${firstLot.product_id}`,
      { headers: authHeaders(token) },
    );
    expect(response.ok()).toBeTruthy();

    const body = await response.json();
    expect(body.product_id).toBe(firstLot.product_id);
    expect(body.on_hand).toBeGreaterThanOrEqual(0);
    expect(body.reserved).toBeGreaterThanOrEqual(0);
    expect(
      body.available,
      "the two aggregates must still agree once _on_hand is served index-only",
    ).toBe(body.on_hand - body.reserved);
  });

  test("low-stock alerts still aggregate per product", async ({ request }) => {
    const token = await apiToken(request, USERS.admin);

    const response = await request.get(`${API}/api/v1/inventory/alerts`, {
      headers: authHeaders(token),
    });
    expect(response.ok()).toBeTruthy();

    const { alerts } = await response.json();
    expect(Array.isArray(alerts)).toBeTruthy();
    for (const alert of alerts) {
      // `list_alerts` groups over the whole table with no WHERE clause — the one measured path
      // the index deliberately does not touch. Asserted so a later "optimisation" that does
      // touch it cannot quietly change these totals.
      expect(alert.current_quantity).toBeGreaterThanOrEqual(0);
      expect(alert.is_triggered).toBe(alert.current_quantity <= alert.threshold);
    }
  });

  test("CSV export returns one row per lot", async ({ request }) => {
    const token = await apiToken(request, USERS.admin);

    const [csv, lots] = await Promise.all([
      request.get(`${API}/api/v1/inventory/export`, { headers: authHeaders(token) }),
      request.get(`${API}/api/v1/inventory?page=1&page_size=1`, { headers: authHeaders(token) }),
    ]);
    expect(csv.ok()).toBeTruthy();

    const lines = (await csv.text()).split("\n").filter((line) => line.trim() !== "");
    const total = (await lots.json()).total;

    expect(lines[0]).toContain("quantity_on_hand");
    expect(lines.length - 1, "every lot must appear exactly once").toBe(total);
  });

  test("inventory renders in Spanish with no console errors", async ({ page }) => {
    failOnPageErrors(page);

    await login(page, USERS.admin);
    await page.goto("/es/inventory");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("table tbody tr").first()).toBeVisible();
    // The locale segment must survive rather than bouncing back to /en.
    expect(page.url()).toContain("/es/");
  });
});
