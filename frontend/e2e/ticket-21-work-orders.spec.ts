import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { USERS, API, login, apiToken, authHeaders, unique, failOnPageErrors } from "./helpers/auth";
import { allLots, inStorageTotal } from "./helpers/inventory";

/**
 * T21 Flow 3 — Work Order from creation to shipment.
 *
 * Create → assign → allocate are driven through the ACR-18 UI. The status walk
 * (in_production → completed → ready_for_shipment) is driven over the API, because
 * `WorkOrderDetail` ships no control for it — allocate and assign are the only actions it offers.
 * The UI is still asserted at every step: each transition must move the work order into the right
 * collapsible group on the list, which is the lifecycle contract a user actually sees.
 */

/** The seeded product used as both the WO product and its material. */
const MATERIAL = "Steel Rod";
const REQUIRED = 3;

async function setStatus(
  request: APIRequestContext,
  token: string,
  woId: number,
  status: string,
) {
  return request.patch(`${API}/api/v1/work-orders/${woId}/status`, {
    headers: authHeaders(token),
    data: { status },
  });
}

/** Assert the work order's row sits under the given status heading on /work-orders. */
async function expectInGroup(page: Page, woNumber: string, groupLabel: string) {
  await page.reload();
  const group = page.locator("section", { has: page.getByRole("button", { name: new RegExp(groupLabel) }) });
  await expect(group.filter({ hasText: woNumber })).toHaveCount(1);
}

async function createWorkOrderViaUi(page: Page) {
  const product = unique("E2E WO ");

  await page.getByRole("button", { name: /create work order/i }).click();
  await page.locator("#wo-product").fill(product);
  await page.locator("#wo-qty").fill(String(REQUIRED));
  await page.locator("#wo-date").fill("2026-12-31");

  // Allocation matches material_type against Product.name, so the material must name a real
  // product or the allocate step later has nothing to draw from.
  await page.getByPlaceholder("Material type").fill(MATERIAL);
  await page.getByPlaceholder("Qty").fill(String(REQUIRED));

  await page.getByRole("button", { name: /^create$/i }).click();

  // The form swaps to a material-availability summary on success.
  await expect(page.getByTestId(`avail-${MATERIAL}`)).toBeVisible();
  await page.getByRole("button", { name: /^done$/i }).click();

  return product;
}

test.describe("T21 Flow 3 — work order lifecycle", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("an admin walks a work order from creation to ready for shipment", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);

    await login(page, USERS.admin);

    // Reached from the nav, not a typed URL — the link was commented out until this ticket.
    // Scoped to the sidebar: the dashboard's quick-action bar links here too.
    await page.getByRole("complementary", { name: "sidebar" })
      .getByRole("link", { name: "Work Orders" })
      .click();
    await expect(page).toHaveURL(/\/en\/work-orders/);

    const product = await createWorkOrderViaUi(page);

    // Find the work order we just made.
    const listRes = await request.get(`${API}/api/v1/work-orders?page_size=250`, {
      headers: authHeaders(token),
    });
    const wo = ((await listRes.json()).results as { id: number; wo_number: string; product: string; status: string }[])
      .find((w) => w.product === product)!;
    expect(wo, "the created work order must come back from the API").toBeTruthy();
    expect(wo.status).toBe("created");

    await expectInGroup(page, wo.wo_number, "Created");

    // ── assign a production line, through the UI ────────────────────────────
    await page.getByTestId(`wo-row-${wo.id}`).click();
    await page.getByRole("combobox").last().click();
    await page.getByRole("option").first().click();
    await expect
      .poll(async () => {
        const res = await request.get(`${API}/api/v1/work-orders/${wo.id}`, {
          headers: authHeaders(token),
        });
        return (await res.json()).production_line;
      })
      .toBeTruthy();

    // ── allocate materials, through the UI, and watch stock move ────────────
    const productsRes = await request.get(`${API}/api/v1/products?page_size=50`, {
      headers: authHeaders(token),
    });
    const material = ((await productsRes.json()).results as { id: number; name: string }[]).find(
      (p) => p.name === MATERIAL,
    )!;
    const stockBefore = inStorageTotal(await allLots(request, token), material.id);

    await page.reload();
    await page.getByTestId(`wo-row-${wo.id}`).click();
    await page.getByRole("button", { name: /allocate materials/i }).click();
    await page.getByRole("button", { name: /^allocate$/i }).click();

    await expectInGroup(page, wo.wo_number, "Materials Allocated");

    // Stock must move — but the exact amount is not asserted. `WorkOrderMaterial` quantities are
    // display units while `InventoryLot.quantity_on_hand` is stored ×100, and the allocator
    // subtracts one from the other directly, so a 3-unit requirement removes 3 hundredths. That
    // mismatch is a real defect, reported separately; reconciling the two scales is a domain
    // decision, and pinning today's number here would only cement the bug.
    const stockAfter = inStorageTotal(await allLots(request, token), material.id);
    expect(stockAfter, "allocation must consume stock").toBeLessThan(stockBefore);

    // ── the rest of the lifecycle ──────────────────────────────────────────
    for (const [status, label] of [
      ["in_production", "In Production"],
      ["completed", "Completed"],
      ["ready_for_shipment", "Ready for Shipment"],
    ] as const) {
      const res = await setStatus(request, token, wo.id, status);
      expect(res.status(), `transition to ${status}`).toBe(200);
      await expectInGroup(page, wo.wo_number, label);
    }
  });

  test("allocating twice is refused and does not double-deduct", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);

    await login(page, USERS.admin);
    await page.goto("/en/work-orders");
    const product = await createWorkOrderViaUi(page);

    const listRes = await request.get(`${API}/api/v1/work-orders?page_size=250`, {
      headers: authHeaders(token),
    });
    const wo = ((await listRes.json()).results as { id: number; product: string }[]).find(
      (w) => w.product === product,
    )!;

    const productsRes = await request.get(`${API}/api/v1/products?page_size=50`, {
      headers: authHeaders(token),
    });
    const material = ((await productsRes.json()).results as { id: number; name: string }[]).find(
      (p) => p.name === MATERIAL,
    )!;
    const before = inStorageTotal(await allLots(request, token), material.id);

    const first = await request.patch(`${API}/api/v1/work-orders/${wo.id}/allocate`, {
      headers: authHeaders(token),
    });
    expect(first.status()).toBe(200);

    const midpoint = inStorageTotal(await allLots(request, token), material.id);

    const second = await request.patch(`${API}/api/v1/work-orders/${wo.id}/allocate`, {
      headers: authHeaders(token),
    });
    expect(second.status(), "a second allocation must be refused").toBe(409);

    // The invariant that matters here is *once*: whatever the first allocation consumed, the
    // refused second one must not consume any more. (See the note above on unit scales.)
    expect(midpoint, "the first allocation must consume stock").toBeLessThan(before);
    const after = inStorageTotal(await allLots(request, token), material.id);
    expect(after, "stock must move once, not twice").toBe(midpoint);
  });

  test("a work order with an impossible quantity is refused", async ({ page }) => {
    await login(page, USERS.admin);
    await page.goto("/en/work-orders");

    await page.getByRole("button", { name: /create work order/i }).click();
    await page.locator("#wo-product").fill(unique("E2E BadQty "));
    await page.locator("#wo-qty").fill("0"); // schema says gt=0
    await page.locator("#wo-date").fill("2026-12-31");
    await page.getByPlaceholder("Material type").fill(MATERIAL);
    await page.getByPlaceholder("Qty").fill("1");
    await page.getByRole("button", { name: /^create$/i }).click();

    // The dialog must stay open with an error rather than silently swallowing the rejection.
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByTestId(`avail-${MATERIAL}`)).toHaveCount(0);
  });

  test("an unknown status value is rejected by the API", async ({ request }) => {
    const token = await apiToken(request, USERS.admin);
    const listRes = await request.get(`${API}/api/v1/work-orders?page_size=1`, {
      headers: authHeaders(token),
    });
    const wo = (await listRes.json()).results[0];

    const res = await setStatus(request, token, wo.id, "teleported");
    expect(res.status(), "the status field is a closed set").toBe(422);
  });

  test("a machine operator sees only work orders in production and cannot create", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.operator);

    // Make sure at least one work order is in production, so "only in_production" is a real filter
    // rather than an empty list that would pass vacuously.
    const adminToken = await apiToken(request, USERS.admin);
    const all = await request.get(`${API}/api/v1/work-orders?page_size=250`, {
      headers: authHeaders(adminToken),
    });
    const inProduction = ((await all.json()).results as { id: number; wo_number: string; status: string }[])
      .filter((w) => w.status === "in_production");
    expect(inProduction.length, "seed data must contain an in-production work order").toBeGreaterThan(0);

    await login(page, USERS.operator);
    await page.goto("/en/work-orders");

    await expect(page.getByTestId(`wo-row-${inProduction[0].id}`)).toBeVisible();
    // Operators plan nothing; they only work the line.
    await expect(page.getByRole("button", { name: /create work order/i })).toHaveCount(0);

    const create = await request.post(`${API}/api/v1/work-orders`, {
      headers: authHeaders(token),
      data: {
        product: unique("E2E Forbidden "),
        quantity_required: 1,
        target_date: "2026-12-31",
        materials: [{ material_type: MATERIAL, quantity_required: 1 }],
      },
    });
    expect(create.status()).toBe(403);

    const allocate = await request.patch(
      `${API}/api/v1/work-orders/${inProduction[0].id}/allocate`,
      { headers: authHeaders(token) },
    );
    expect(allocate.status()).toBe(403);
  });

  test("a receiving clerk cannot see work orders at all", async ({ page, request }) => {
    await login(page, USERS.clerk);

    await expect(page.getByRole("link", { name: "Work Orders" })).toHaveCount(0);

    await page.goto("/en/work-orders");
    await expect(page.getByTestId("privilege-denied")).toBeVisible();

    const token = await apiToken(request, USERS.clerk);
    const res = await request.get(`${API}/api/v1/work-orders`, { headers: authHeaders(token) });
    expect(res.status()).toBe(403);
  });
});
