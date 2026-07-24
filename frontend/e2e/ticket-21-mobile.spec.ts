import { test, expect, type Page } from "@playwright/test";
import { USERS, login, failOnPageErrors } from "./helpers/auth";

/**
 * T21 Flow 6 — Mobile viewport (NFR-010).
 *
 * Runs under the `mobile` project (iPhone 14, 390px) — see playwright.config.ts.
 *
 * The layout used to pin a 256px sidebar with `fixed … w-64` and offset every page by `ml-64`, with
 * no breakpoint, so at 390px two thirds of the screen was chrome and the content spilled sideways.
 * These assertions are what forced the responsive drawer.
 */

const MODULES = ["/en/receiving", "/en/inventory", "/en/work-orders"];

/**
 * The page must not scroll sideways.
 *
 * `scrollWidth` is compared against `clientWidth` rather than `window.innerWidth`, so a vertical
 * scrollbar's gutter is not mistaken for overflow, and 1px is allowed for sub-pixel rounding.
 */
async function horizontalOverflow(page: Page) {
  return page.evaluate(() => {
    const el = document.documentElement;
    return el.scrollWidth - el.clientWidth;
  });
}

test.describe("T21 Flow 6 — mobile viewport (NFR-010)", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("the desktop sidebar is replaced by a drawer at phone width", async ({ page }) => {
    await login(page, USERS.admin);

    // The fixed 256px sidebar must be out of the way entirely, not merely narrower.
    await expect(page.getByRole("complementary", { name: "sidebar" })).toBeHidden();
    await expect(page.getByTestId("mobile-nav-trigger")).toBeVisible();
  });

  test("the drawer opens, navigates, and closes", async ({ page }) => {
    await login(page, USERS.admin);

    await page.getByTestId("mobile-nav-trigger").click();
    const drawer = page.getByTestId("mobile-nav");
    await expect(drawer).toBeVisible();

    await drawer.getByRole("link", { name: "Inventory" }).click();
    await expect(page).toHaveURL(/\/en\/inventory/);

    // Navigating must dismiss the drawer, or it covers the page it just opened.
    await expect(drawer).toBeHidden();
    await expect(page.getByTestId("inventory-table")).toBeVisible();
  });

  test.describe("every module fits the viewport", () => {
    for (const path of MODULES) {
      test(`${path} does not scroll sideways`, async ({ page }) => {
        await login(page, USERS.admin);
        await page.goto(path);

        // Wait for real content, so the measurement is not taken against an empty skeleton.
        await expect(page.getByTestId("mobile-nav-trigger")).toBeVisible();

        expect(await horizontalOverflow(page), `${path} overflows horizontally`).toBeLessThanOrEqual(1);
      });
    }
  });

  test("the primary control of each module is reachable", async ({ page }) => {
    await login(page, USERS.admin);

    await page.goto("/en/receiving");
    await expect(page.getByTestId("submit-delivery")).toBeVisible();

    await page.goto("/en/inventory");
    await expect(page.getByTestId("search-input")).toBeVisible();

    await page.goto("/en/work-orders");
    await expect(page.getByRole("button", { name: /create work order/i })).toBeVisible();
  });

  test("the drawer respects privileges just like the sidebar", async ({ page }) => {
    // A drawer that forgets the privilege filter would be a brand-new way to leak admin modules.
    await login(page, USERS.clerk);

    await page.getByTestId("mobile-nav-trigger").click();
    const drawer = page.getByTestId("mobile-nav");
    await expect(drawer).toBeVisible();

    await expect(drawer.getByRole("link", { name: "Receiving" })).toBeVisible();
    await expect(drawer.getByRole("link", { name: "Users" })).toHaveCount(0);
    await expect(drawer.getByRole("link", { name: "Audit Log" })).toHaveCount(0);
    await expect(drawer.getByRole("link", { name: "Work Orders" })).toHaveCount(0);
  });
});
