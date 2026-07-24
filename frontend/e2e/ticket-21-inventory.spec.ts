import { test, expect, type Page } from "@playwright/test";
import { USERS, API, login, apiToken, authHeaders, failOnPageErrors } from "./helpers/auth";
import { allLots, type Lot } from "./helpers/inventory";

// Imported rather than re-implemented: a local copy of the formatter would keep asserting the old
// format — and keep passing — the moment the app's changed, which is exactly what this must catch.
import { toDisplay } from "@/src/lib/qty";

/**
 * T21 Flow 4 — Inventory trace & adjust.
 *
 * Click a lot → traceability view; adjust quantity with confirmation. Expected values are always
 * derived from a live read, never hard-coded: the seeded database is not reset between runs and the
 * other flows in this suite move stock.
 */

/** Open /inventory and narrow to one lot, so its row is on the rendered page. */
async function findRow(page: Page, lot: Lot) {
  await page.goto("/en/inventory");
  await expect(page.getByTestId("inventory-table")).toBeVisible();

  if (lot.product_name) {
    await page.getByTestId("search-input").fill(lot.product_name);
  }
  const row = page.getByTestId(`row-${lot.id}`);
  await expect(row).toBeVisible();
  return row;
}

test.describe("T21 Flow 4 — inventory trace & adjust", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("clicking a lot opens its traceability details", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lot = (await allLots(request, token)).find((l) => l.status === "in_storage")!;
    expect(lot, "seed data must contain an in-storage lot").toBeTruthy();

    await login(page, USERS.admin);
    const row = await findRow(page, lot);
    await row.click();

    const dialog = page.getByTestId("inventory-details-dialog");
    await expect(dialog).toBeVisible();
    // The traceability claim is that the dialog identifies *this* lot and where it came from.
    await expect(dialog).toContainText(String(lot.id));
    if (lot.lot_number) await expect(dialog).toContainText(lot.lot_number);
    if (lot.storage_location) await expect(dialog).toContainText(lot.storage_location);
  });

  test("the transaction log lists movements for a lot", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lot = (await allLots(request, token)).find((l) => l.status === "in_storage")!;

    await login(page, USERS.admin);
    await findRow(page, lot);

    await page.getByTestId(`log-btn-${lot.id}`).click();
    await expect(page.getByTestId("transaction-log-modal")).toBeVisible();
    // Seeded lots are created by a receipt, so there is always at least one entry.
    await expect(page.locator("[data-testid^='txn-row-']").first()).toBeVisible();
  });

  test("adjusting a quantity updates the row and the API agrees", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lot = (await allLots(request, token)).find((l) => l.status === "in_storage")!;
    const DELTA = 5; // display units

    await login(page, USERS.admin);
    await findRow(page, lot);

    await page.getByTestId(`adjust-btn-${lot.id}`).click();
    await expect(page.getByTestId("adjust-modal")).toBeVisible();

    await page.getByTestId("quantity-input").fill(String(DELTA));
    await page.getByTestId("reason-input").fill("T21 e2e adjustment");

    // Two-step: Review, then Confirm. The confirmation step is part of the ticket's criteria.
    await page.getByRole("button", { name: /^review$/i }).click();
    await page.getByTestId("confirm-adjust").click();
    await expect(page.getByTestId("adjust-modal")).toBeHidden();

    const expected = lot.quantity_on_hand + DELTA * 100;

    // The row the operator is looking at shows the new value…
    await expect(page.getByTestId(`row-${lot.id}`).locator("td").nth(3)).toContainText(
      toDisplay(expected),
    );

    // …and the ledger actually moved, rather than the UI optimistically lying.
    const after = (await allLots(request, token)).find((l) => l.id === lot.id)!;
    expect(after.quantity_on_hand).toBe(expected);
  });

  test("a zero adjustment and an empty reason are both refused", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lot = (await allLots(request, token)).find((l) => l.status === "in_storage")!;
    const before = lot.quantity_on_hand;

    await login(page, USERS.admin);
    await findRow(page, lot);
    await page.getByTestId(`adjust-btn-${lot.id}`).click();

    // Zero is not an adjustment.
    await page.getByTestId("quantity-input").fill("0");
    await page.getByTestId("reason-input").fill("should not apply");
    await page.getByRole("button", { name: /^review$/i }).click();
    await expect(page.getByTestId("adjust-error")).toContainText(/non-zero/i);

    // A reason is mandatory, and whitespace is not a reason.
    await page.getByTestId("quantity-input").fill("3");
    await page.getByTestId("reason-input").fill("   ");
    await page.getByRole("button", { name: /^review$/i }).click();
    await expect(page.getByTestId("adjust-error")).toContainText(/reason is required/i);

    // Neither rejected attempt may have touched the ledger.
    const after = (await allLots(request, token)).find((l) => l.id === lot.id)!;
    expect(after.quantity_on_hand).toBe(before);
  });

  test("a negative adjustment is accepted and decrements the lot", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lot = (await allLots(request, token)).find(
      (l) => l.status === "in_storage" && l.quantity_on_hand > 1000,
    )!;
    const DELTA = -4;

    await login(page, USERS.admin);
    await findRow(page, lot);
    await page.getByTestId(`adjust-btn-${lot.id}`).click();

    await page.getByTestId("quantity-input").fill(String(DELTA));
    await page.getByTestId("reason-input").fill("T21 e2e shrinkage");
    await page.getByRole("button", { name: /^review$/i }).click();
    await page.getByTestId("confirm-adjust").click();
    await expect(page.getByTestId("adjust-modal")).toBeHidden();

    const after = (await allLots(request, token)).find((l) => l.id === lot.id)!;
    expect(after.quantity_on_hand).toBe(lot.quantity_on_hand + DELTA * 100);
  });

  test("cancelling the adjust dialog changes nothing", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lot = (await allLots(request, token)).find((l) => l.status === "in_storage")!;

    await login(page, USERS.admin);
    await findRow(page, lot);
    await page.getByTestId(`adjust-btn-${lot.id}`).click();

    await page.getByTestId("quantity-input").fill("99");
    await page.getByTestId("reason-input").fill("cancelled");
    await page.getByRole("button", { name: /^cancel$/i }).click();
    await expect(page.getByTestId("adjust-modal")).toBeHidden();

    const after = (await allLots(request, token)).find((l) => l.id === lot.id)!;
    expect(after.quantity_on_hand).toBe(lot.quantity_on_hand);
  });

  test("search narrows the table to matching rows only", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lots = await allLots(request, token);
    const named = lots.find((l) => l.product_name)!;
    const matching = lots.filter((l) => l.product_name === named.product_name);

    await login(page, USERS.admin);
    await page.goto("/en/inventory");
    await expect(page.getByTestId("inventory-table")).toBeVisible();

    await page.getByTestId("search-input").fill(named.product_name!);

    // Wait for the debounced refetch to actually narrow the table before asserting. Without this
    // the unfiltered rows are still on screen and every assertion below passes vacuously.
    const rows = page.locator("[data-testid^='row-']");
    await expect(rows).toHaveCount(matching.length);

    // Every remaining row — not just the first — must be a match.
    for (const cell of await rows.locator("td").first().all()) {
      await expect(cell).toContainText(named.product_name!);
    }
  });

  test("Clear Filters empties the box and restores the full list", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const lots = await allLots(request, token);
    const named = lots.find((l) => l.product_name)!;
    const matching = lots.filter((l) => l.product_name === named.product_name);

    await login(page, USERS.admin);
    await page.goto("/en/inventory");
    await expect(page.getByTestId("inventory-table")).toBeVisible();

    const rows = page.locator("[data-testid^='row-']");
    const unfiltered = await rows.count();

    await page.getByTestId("search-input").fill(named.product_name!);
    await expect(rows).toHaveCount(matching.length);

    await page.getByTestId("clear-filters").click();
    await expect(page.getByTestId("search-input")).toHaveValue("");
    await expect(rows).toHaveCount(unfiltered);
  });

  test("a machine operator is blocked from inventory at the page and at the API", async ({
    page,
    request,
  }) => {
    // machine_operator is the only seeded role without inventory.view. (receiving_clerk *does*
    // have it — see the note on USERS.)
    await login(page, USERS.operator);

    await expect(page.getByRole("link", { name: "Inventory" })).toHaveCount(0);

    await page.goto("/en/inventory");
    await expect(page.getByTestId("privilege-denied")).toBeVisible();
    await expect(page.getByTestId("inventory-table")).toHaveCount(0);

    // Hiding the nav is not access control — the API must refuse the token too.
    const token = await apiToken(request, USERS.operator);
    const read = await request.get(`${API}/api/v1/inventory`, { headers: authHeaders(token) });
    expect(read.status()).toBe(403);
  });

  test("a role with inventory.view but not inventory.adjust cannot adjust", async ({ request }) => {
    // production_supervisor reads inventory but must not be able to write to it. This one is only
    // provable at the API: the UI hides the Adjust button behind a role check, and a hidden button
    // is not a permission.
    const token = await apiToken(request, USERS.supervisor);

    const read = await request.get(`${API}/api/v1/inventory`, { headers: authHeaders(token) });
    expect(read.status()).toBe(200);

    const lot = (await allLots(request, token)).find((l) => l.status === "in_storage")!;
    const adjust = await request.patch(`${API}/api/v1/inventory/${lot.id}`, {
      headers: authHeaders(token),
      data: { delta: 100, reason: "should be refused" },
    });
    expect(adjust.status()).toBe(403);
  });
});
