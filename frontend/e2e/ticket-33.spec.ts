import { test, expect, Page } from "@playwright/test";

/**
 * ACR-33 — Shipment invoice generation + Transfer / Direct Customer source.
 *
 * Run against a seeded database with the backend up and a production frontend
 * build (`npm run build && npm run start`) — NOT `next dev` (KI-02).
 */

const ADMIN = { username: "admin", password: "admin123" };
const CLERK = { username: "clerk1", password: "demo123" };

// Unique per run so repeat runs against the same database do not collide on BOL.
const RUN = Date.now().toString().slice(-6);
const DIRECT_BOL = `E2E-DIR-${RUN}`;
const TRANSFER_BOL = `E2E-TRF-${RUN}`;

async function login(page: Page, username: string, password: string) {
  await page.goto("/en/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

/** Radix Select renders a listbox, not a native <select>. */
async function chooseType(page: Page, label: "Direct Customer" | "Transfer") {
  await page.getByTestId("type-select").click();
  await page.getByRole("option", { name: label }).click();
}

async function fillHeader(page: Page, bol: string) {
  await page.getByTestId("bol-input").fill(bol);
  await page.getByTestId("date-input").fill("2026-07-23");
}

test.describe("ACR-33 — Direct Customer shipment with source + invoice", () => {
  test("admin sees the Shipping nav link", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await expect(page.getByRole("link", { name: "Shipping" })).toBeVisible();
  });

  test("creates a Direct Customer shipment carrying a source, then invoices it", async ({
    page,
  }) => {
    // An uncaught exception or a 5xx is a failure. A 404 from the invoice endpoint is not — it is
    // how "not invoiced yet" is expressed — and the browser logs a console error for it regardless,
    // so watch the real signals instead of console noise.
    const failures: string[] = [];
    page.on("pageerror", (e) => failures.push(`pageerror: ${e.message}`));
    page.on("response", (r) => {
      if (r.status() >= 500) failures.push(`${r.status()} ${r.url()}`);
    });

    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/shipping");
    await expect(page.getByTestId("shipment-table")).toBeVisible();

    // ── create ──────────────────────────────────────────────────────────────
    await page.getByTestId("new-shipment-button").click();
    await fillHeader(page, DIRECT_BOL);

    // direct_customer is the default, so source is offered straight away.
    await expect(page.getByTestId("source-input")).toBeVisible();
    await page.getByTestId("source-input").fill("SC");

    await page.getByTestId("lot-input-0").fill("3");
    await page.getByTestId("qty-input-0").fill("1");
    await page.getByTestId("price-input-0").fill("2.50");

    await page.getByTestId("submit-shipment").click();

    const row = page.locator("tr", { hasText: DIRECT_BOL });
    await expect(row).toBeVisible();
    await expect(row).toContainText("Direct Customer");
    await expect(row).toContainText("SC");

    // ── invoice ─────────────────────────────────────────────────────────────
    await row.click();
    await expect(page.getByTestId("generate-invoice")).toBeVisible();
    await page.getByTestId("generate-invoice").click();

    await expect(page.getByTestId("invoice-panel")).toBeVisible();
    await expect(page.getByTestId("invoice-number")).toHaveText(/^INV-2026-\d{5}$/);
    // 1.00 unit x 2.50 = 2.50
    await expect(page.getByTestId("invoice-total")).toContainText("2.50 USD");

    // Once raised, the invoice is immutable — no second Generate button.
    await expect(page.getByTestId("generate-invoice")).toBeHidden();

    expect(failures).toEqual([]);
  });

  test("the invoice survives a reload", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/shipping");

    await page.locator("tr", { hasText: DIRECT_BOL }).click();
    await expect(page.getByTestId("invoice-panel")).toBeVisible();
    const number = await page.getByTestId("invoice-number").textContent();

    await page.reload();
    await page.locator("tr", { hasText: DIRECT_BOL }).click();
    await expect(page.getByTestId("invoice-number")).toHaveText(number!.trim());
  });
});

test.describe("ACR-33 — Transfer shipment", () => {
  test("hides source for a Transfer and creates one without it", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/shipping");

    await page.getByTestId("new-shipment-button").click();
    await fillHeader(page, TRANSFER_BOL);

    await expect(page.getByTestId("source-input")).toBeVisible();
    await chooseType(page, "Transfer");
    // §4.3: source belongs to a Direct Customer note only.
    await expect(page.getByTestId("source-input")).toBeHidden();

    await page.getByTestId("lot-input-0").fill("4");
    await page.getByTestId("qty-input-0").fill("1");
    await page.getByTestId("submit-shipment").click();

    const row = page.locator("tr", { hasText: TRANSFER_BOL });
    await expect(row).toBeVisible();
    await expect(row).toContainText("Transfer");
  });
});

test.describe("ACR-33 — validation and permissions", () => {
  test("blocks a submit with no usable line", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/shipping");

    await page.getByTestId("new-shipment-button").click();
    await fillHeader(page, `E2E-EMPTY-${RUN}`);
    await page.getByTestId("submit-shipment").click();

    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.locator("tr", { hasText: `E2E-EMPTY-${RUN}` })).toHaveCount(0);
  });

  test("rejects a quantity larger than the lot holds", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/shipping");

    await page.getByTestId("new-shipment-button").click();
    await fillHeader(page, `E2E-OVER-${RUN}`);
    await page.getByTestId("lot-input-0").fill("5");
    await page.getByTestId("qty-input-0").fill("999999");
    await page.getByTestId("submit-shipment").click();

    await expect(page.getByRole("alert")).toContainText(/insufficient stock/i);
  });

  test("a user without shipping privileges cannot reach shipping", async ({ page }) => {
    await login(page, CLERK.username, CLERK.password);

    await expect(page.getByRole("link", { name: "Shipping" })).toHaveCount(0);

    // Hidden is not the same as blocked — the data must not load either.
    await page.goto("/en/shipping");
    await expect(page.getByTestId("shipment-table")).toHaveCount(0);
  });
});

test.describe("ACR-33 — Spanish locale", () => {
  test("renders the new labels in Spanish", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/es/shipping");

    await expect(page.getByTestId("shipment-table")).toBeVisible();
    await page.getByTestId("new-shipment-button").click();

    // Scope to the dialog: "Origen" is also a column header on the table behind it.
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Origen", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Precio Unitario", { exact: true })).toBeVisible();
  });
});
