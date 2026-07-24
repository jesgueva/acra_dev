import { test, expect, Page, APIRequestContext } from "@playwright/test";
import { toDisplay } from "../src/lib/qty";

/**
 * ACR-30 — concurrency-safe worksheet close, end to end against a live stack.
 *
 * The spike adds no operator UI, so what these tests prove is that a close moves real stock to
 * the place an operator actually looks: the Inventory page. The concurrency guarantee itself is
 * proven in backend/tests/integration/test_worksheet_close_concurrency.py (TC-02) — asserting a
 * race through a browser would only add flake.
 *
 * Run against a seeded database with the backend on :8000 and a production frontend build on
 * :3000 (NOT `next dev`, see KI-02).
 */

const ADMIN = { username: "admin", password: "admin123" };
const OPERATOR = { username: "operator1", password: "demo123" }; // machine_operator: no privileges
const API = process.env.E2E_API_URL ?? "http://localhost:8000";

const CONSUME = 1000; // ×100 → 10.00 units

interface Lot {
  id: number;
  product_id: number;
  product_name: string | null;
  storage_location: string | null;
  status: string;
  quantity_on_hand: number;
}

async function login(page: Page, username: string, password: string) {
  await page.goto("/en/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

async function apiToken(request: APIRequestContext, username: string, password: string) {
  const resp = await request.post(`${API}/api/v1/auth/login`, {
    data: { username, password },
  });
  expect(resp.status()).toBe(200);
  return (await resp.json()).access_token as string;
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

async function allLots(request: APIRequestContext, token: string): Promise<Lot[]> {
  const resp = await request.get(`${API}/api/v1/inventory?page_size=100`, {
    headers: auth(token),
  });
  expect(resp.status()).toBe(200);
  return (await resp.json()).results as Lot[];
}

/**
 * The lot the close will actually draw from: lowest id, in storage, non-empty, for a product with
 * enough stock in that single lot to cover the draw. Picking the FIFO target explicitly is what
 * lets the test assert on one specific row rather than on a total.
 */
async function pickFifoLot(request: APIRequestContext, token: string): Promise<Lot> {
  const lots = await allLots(request, token);
  const drawable = lots
    .filter((l) => l.status === "in_storage" && l.quantity_on_hand > 0)
    .sort((a, b) => a.id - b.id);

  const firstByProduct = new Map<number, Lot>();
  for (const lot of drawable) {
    if (!firstByProduct.has(lot.product_id)) firstByProduct.set(lot.product_id, lot);
  }

  const target = [...firstByProduct.values()].find(
    (l) => l.quantity_on_hand > CONSUME && l.storage_location,
  );
  expect(target, "seed data should contain a drawable lot with a storage location").toBeTruthy();
  return target!;
}

async function lotById(request: APIRequestContext, token: string, id: number): Promise<Lot> {
  const lot = (await allLots(request, token)).find((l) => l.id === id);
  expect(lot, `lot ${id} should still be listed`).toBeTruthy();
  return lot!;
}

async function createWorksheet(
  request: APIRequestContext,
  token: string,
  productId: number,
) {
  const resp = await request.post(`${API}/api/v1/production-worksheets`, {
    headers: auth(token),
    data: {
      production_line: "E2E-LINE",
      scheduled_date: "2026-07-24",
      lines: [{ product_id: productId, planned_quantity: CONSUME }],
    },
  });
  expect(resp.status()).toBe(201);
  const ws = await resp.json();
  expect(ws.version).toBe(0);
  expect(ws.status).toBe("draft");
  return ws;
}

function closeWorksheet(
  request: APIRequestContext,
  token: string,
  worksheetId: number,
  lineId: number,
  expectedVersion: number,
) {
  return request.post(`${API}/api/v1/production-worksheets/${worksheetId}/close`, {
    headers: auth(token),
    data: {
      expected_version: expectedVersion,
      lines: [{ line_id: lineId, actual_quantity: CONSUME }],
    },
  });
}

/** Bring one lot's row on screen — the page filters on product name or storage location. */
async function findLotRow(page: Page, lot: Lot) {
  await page.goto("/en/inventory");
  await expect(page.getByTestId("inventory-table")).toBeVisible();
  await page.getByTestId("search-input").fill(lot.storage_location!);
  const row = page.getByTestId(`row-${lot.id}`);
  await expect(row).toBeVisible();
  return row;
}

test.describe("ACR-30 worksheet close moves real stock", () => {
  test("closing a worksheet decrements the lot shown on the Inventory page", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, ADMIN.username, ADMIN.password);
    const lot = await pickFifoLot(request, token);

    await login(page, ADMIN.username, ADMIN.password);

    // The operator's view before the close.
    const rowBefore = await findLotRow(page, lot);
    await expect(rowBefore).toContainText(toDisplay(lot.quantity_on_hand));

    const ws = await createWorksheet(request, token, lot.product_id);
    const closed = await closeWorksheet(request, token, ws.id, ws.lines[0].id, 0);
    expect(closed.status()).toBe(200);

    const body = await closed.json();
    expect(body.status).toBe("closed");
    expect(body.version).toBe(1); // the guard bumped it exactly once
    expect(body.closed_at).not.toBeNull();
    expect(body.lines[0].actual_quantity).toBe(CONSUME);

    // ...and after: the same row, down by exactly the actual quantity.
    const expected = lot.quantity_on_hand - CONSUME;
    expect((await lotById(request, token, lot.id)).quantity_on_hand).toBe(expected);

    const rowAfter = await findLotRow(page, lot);
    await expect(rowAfter).toContainText(toDisplay(expected));
  });

  test("a second close is refused and stock does not move again", async ({ page, request }) => {
    const token = await apiToken(request, ADMIN.username, ADMIN.password);
    const lot = await pickFifoLot(request, token);

    const ws = await createWorksheet(request, token, lot.product_id);
    expect((await closeWorksheet(request, token, ws.id, ws.lines[0].id, 0)).status()).toBe(200);

    const afterFirst = (await lotById(request, token, lot.id)).quantity_on_hand;

    // Same stale expected_version — the double-submit an impatient operator produces.
    const replay = await closeWorksheet(request, token, ws.id, ws.lines[0].id, 0);
    expect(replay.status()).toBe(409);
    expect((await replay.json()).detail).toContain("already closed");

    // The decrement happened once, and the page agrees.
    expect((await lotById(request, token, lot.id)).quantity_on_hand).toBe(afterFirst);

    await login(page, ADMIN.username, ADMIN.password);
    const row = await findLotRow(page, lot);
    await expect(row).toContainText(toDisplay(afterFirst));
  });

  test("an operator without the privilege is blocked by the API, not just the UI", async ({
    request,
  }) => {
    const adminToken = await apiToken(request, ADMIN.username, ADMIN.password);
    const lot = await pickFifoLot(request, adminToken);
    const ws = await createWorksheet(request, adminToken, lot.product_id);

    const operatorToken = await apiToken(request, OPERATOR.username, OPERATOR.password);

    const create = await request.post(`${API}/api/v1/production-worksheets`, {
      headers: auth(operatorToken),
      data: { lines: [{ product_id: lot.product_id, planned_quantity: 100 }] },
    });
    expect(create.status()).toBe(403);

    const view = await request.get(`${API}/api/v1/production-worksheets/${ws.id}`, {
      headers: auth(operatorToken),
    });
    expect(view.status()).toBe(403);

    const close = await closeWorksheet(request, operatorToken, ws.id, ws.lines[0].id, 0);
    expect(close.status()).toBe(403);
    expect((await close.json()).detail).toContain("production.worksheet.close");

    // The worksheet the operator failed to close is still open and untouched.
    const still = await request.get(`${API}/api/v1/production-worksheets/${ws.id}`, {
      headers: auth(adminToken),
    });
    expect((await still.json()).status).toBe("draft");
  });
});
