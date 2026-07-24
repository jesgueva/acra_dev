import { test, expect, Page } from "@playwright/test";
import { API_URL, USERS, apiToken, login } from "./helpers";

/**
 * ACR-35 — shipping.* privilege grants + Shipping nav link, end to end.
 *
 * Before this ticket, shipping.view / shipping.create were granted to no role, so every shipment
 * endpoint returned 403 for every user and the Shipping page was unreachable. These tests assert
 * the seeded mapping from migration 013 through the UI:
 *
 *   company_admin         view + create
 *   receiving_clerk       view + create
 *   production_supervisor view only
 *   machine_operator      neither
 *
 * Run against a seeded database (./scripts/reset-db-and-seed.sh) with the backend on :8000 and a
 * production frontend build on :3000 (NOT `next dev`, see KI-02).
 */

const { admin: ADMIN, clerk: CLERK, supervisor: SUPERVISOR, operator: OPERATOR } = USERS;

/** Collect the status of every GET /shipments the page issues. */
function watchShipmentReads(page: Page): number[] {
  const statuses: number[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/v1/shipments") && r.request().method() === "GET") {
      statuses.push(r.status());
    }
  });
  return statuses;
}

test.describe("ACR-35 shipping privileges", () => {
  test("admin reaches the Shipping page from the nav without a 403", async ({ page }) => {
    const reads = watchShipmentReads(page);
    await login(page, ADMIN.username, ADMIN.password);

    const link = page.getByRole("link", { name: "Shipping" });
    await expect(link).toBeVisible();
    await link.click();

    await expect(page).toHaveURL(/\/en\/shipping$/);
    await expect(page.getByRole("heading", { name: "Shipping", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: /New Shipment/i })).toBeVisible();

    // The regression this ticket fixes: the list read must succeed, not 403.
    await expect.poll(() => reads.length).toBeGreaterThan(0);
    expect(reads).not.toContain(403);
    expect(reads).toContain(200);
  });

  test("supervisor may read the shipment log but not book one", async ({ page }) => {
    const reads = watchShipmentReads(page);
    await login(page, SUPERVISOR.username, SUPERVISOR.password);
    await page.goto("/en/shipping");

    await expect(page.getByRole("link", { name: "Shipping" })).toBeVisible();
    await expect.poll(() => reads.length).toBeGreaterThan(0);
    expect(reads).toContain(200);

    // shipping.view without shipping.create — the button would 403 on submit, so it must not render.
    await expect(page.getByRole("button", { name: /New Shipment/i })).toHaveCount(0);
  });

  test("machine operator is blocked from shipping, not merely un-linked", async ({ page }) => {
    const reads = watchShipmentReads(page);
    await login(page, OPERATOR.username, OPERATOR.password);

    await expect(page.getByRole("link", { name: "Shipping" })).toHaveCount(0);

    // Hiding the link is not access control: typing the URL must land on the denial state,
    // and PrivilegeGate must refuse before ShippingView mounts and queries the API.
    await page.goto("/en/shipping");
    await expect(page.getByTestId("privilege-denied")).toBeVisible();
    await expect(page.getByRole("button", { name: /New Shipment/i })).toHaveCount(0);
    await expect(page.locator("tbody tr")).toHaveCount(0);
    expect(reads).toHaveLength(0);
  });

  test("the API refuses the operator directly, not just the UI", async ({ request }) => {
    // The client-side gate is convenience; the privilege is enforced server-side. Without this
    // the suite would prove only that we hid a button.
    const token = await apiToken(request, OPERATOR.username, OPERATOR.password);

    const list = await request.get(`${API_URL}/api/v1/shipments`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(list.status()).toBe(403);
    expect(await list.text()).toContain("shipping.view");
  });

  test("clerk creates a shipment, and a bad lot fails cleanly", async ({ page }) => {
    await login(page, CLERK.username, CLERK.password);
    await page.goto("/en/shipping");

    const bol = `E2E-${Date.now().toString().slice(-8)}`;
    const dialog = page.getByRole("dialog");

    // ── unknown lot → inline error, dialog stays open, no crash ────────────────
    await page.getByRole("button", { name: /New Shipment/i }).click();
    await expect(dialog).toBeVisible();
    await dialog.locator("#bol_number").fill(`${bol}-BAD`);
    await dialog.locator("#shipment_date").fill("2026-07-24");
    await dialog.locator('input[placeholder="Lot ID"]').fill("999999");
    await dialog.locator('input[placeholder="0.00"]').fill("5");
    await dialog.getByRole("button", { name: /Create Shipment/i }).click();

    await expect(dialog.getByRole("alert")).toContainText(/not found/i);
    await expect(dialog).toBeVisible();

    // ── valid lot → 201, dialog closes, row appears ───────────────────────────
    await dialog.locator("#bol_number").fill(bol);
    await dialog.locator('input[placeholder="Lot ID"]').fill("2");
    await dialog.locator('input[placeholder="0.00"]').fill("3");
    await dialog.getByRole("button", { name: /Create Shipment/i }).click();

    await expect(dialog).toBeHidden();
    await expect(page.locator("tbody tr", { hasText: bol })).toBeVisible();
  });

  // The create dialog's own field validation is pre-existing behaviour this ticket did not touch
  // (and ACR-33 is reworking it), so it is deliberately not asserted here.

  test("the Spanish nav links to the localized shipping route", async ({ page }) => {
    await login(page, CLERK.username, CLERK.password);
    await page.goto("/es/shipping");

    const link = page.getByRole("link", { name: "Expedición" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/es/shipping");
    await expect(page.getByRole("heading", { name: "Expedición", level: 1 })).toBeVisible();
  });
});
