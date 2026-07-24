import { test, expect } from "@playwright/test";
import { USERS, API, login, apiToken, authHeaders, failOnPageErrors } from "./helpers/auth";

// Imported, not re-implemented: a local copy of the formatter would keep asserting the old output —
// and keep passing — the moment the app's changed, which is exactly what this must catch.
import { formatDateTime } from "@/src/lib/datetime";

/**
 * T21 Flow 5 — Language toggle & date locale (LR-007).
 *
 * Toggling EN/ES must change the nav labels *and* the way dates are written, and the choice must
 * survive a reload. The date half is the part that used to be broken: timestamps were rendered
 * with `toLocaleString()` and no locale argument, so they followed the browser rather than the app.
 */

const SIDEBAR = { name: "sidebar" } as const;

test.describe("T21 Flow 5 — language and date locale", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("the toggle switches nav labels and survives a reload", async ({ page }) => {
    await login(page, USERS.admin);
    const sidebar = page.getByRole("complementary", SIDEBAR);

    await expect(sidebar.getByRole("link", { name: "Inventory" })).toBeVisible();

    await page.getByRole("button", { name: "toggle-language" }).click();
    await page.waitForURL(/\/es\//);

    await expect(sidebar.getByRole("link", { name: "Inventario" })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Recepción" })).toBeVisible();

    // The preference is persisted server-side, so a reload must not bounce back to English.
    await page.reload();
    await expect(page).toHaveURL(/\/es\//);
    await expect(sidebar.getByRole("link", { name: "Inventario" })).toBeVisible();

    // And back again.
    await page.getByRole("button", { name: "toggle-language" }).click();
    await page.waitForURL(/\/en\//);
    await expect(sidebar.getByRole("link", { name: "Inventory" })).toBeVisible();
  });

  test("audit timestamps are written in the active locale, not the browser's", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);
    const res = await request.get(`${API}/api/v1/audit-logs?page_size=1`, {
      headers: authHeaders(token),
    });
    const entry = (await res.json()).results[0] as { id: number; timestamp: string };
    expect(entry, "seed data must contain an audit entry").toBeTruthy();

    await login(page, USERS.admin);

    // ── English ──────────────────────────────────────────────────────────────
    await page.goto("/en/audit");
    await expect(page.getByTestId("audit-table")).toBeVisible();
    const cellEn = page.getByTestId(`audit-row-${entry.id}`).locator("td").nth(1);
    const renderedEn = (await cellEn.innerText()).trim();
    expect(renderedEn).toBe(formatDateTime(entry.timestamp, "en"));

    // ── Spanish ──────────────────────────────────────────────────────────────
    await page.goto("/es/audit");
    await expect(page.getByTestId("audit-table")).toBeVisible();
    const cellEs = page.getByTestId(`audit-row-${entry.id}`).locator("td").nth(1);
    const renderedEs = (await cellEs.innerText()).trim();
    expect(renderedEs).toBe(formatDateTime(entry.timestamp, "es"));

    // The whole point of LR-007: the two locales must actually render differently. en-US puts the
    // month first and uses a 12-hour clock; es puts the day first and uses 24-hour.
    expect(renderedEs).not.toBe(renderedEn);
  });

  test("the Spanish audit page is translated, not just re-routed", async ({ page }) => {
    await login(page, USERS.admin);
    await page.goto("/es/audit");

    await expect(page.getByRole("columnheader", { name: "Fecha y hora" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Usuario" })).toBeVisible();
  });

  test("a deep link into /es renders Spanish without a manual toggle", async ({ page }) => {
    await login(page, USERS.admin);

    await page.goto("/es/inventory");
    await expect(
      page.getByRole("complementary", SIDEBAR).getByRole("link", { name: "Inventario" }),
    ).toBeVisible();
    await expect(page.getByTestId("inventory-table")).toBeVisible();
  });
});
