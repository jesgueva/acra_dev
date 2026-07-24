import { test, expect, Page, APIRequestContext } from "@playwright/test";

// Imported, not re-implemented: a local copy would keep asserting the old format — and keep
// passing — the moment the app's formatter changed, which is exactly what this spec must catch.
import { toDisplay } from "@/src/lib/qty";

/**
 * ACR-30 — concurrency-safe production-worksheet close, end to end against a live stack.
 *
 * The ticket ships no UI of its own: it is a backend spike. So this spec proves the thing an
 * operator actually cares about — that closing a worksheet moves stock **where they can see it**,
 * exactly once, and that a stale re-close changes nothing.
 *
 * Run against a seeded database with the backend on :8000 and a production frontend build on
 * :3000 (`npm run build && npm run start` — never `next dev`, see KI-02).
 */

const ADMIN = { username: "admin", password: "admin123" };
const OPERATOR = { username: "operator1", password: "demo123" };

const API = process.env.E2E_API_URL ?? "http://localhost:8000";

const CONSUMED = 6000; // ×100 → 60.00 units
const PLANNED = 10000; // ×100 → 100.00 units, so actual < planned leaves a real delta

async function login(page: Page, username: string, password: string) {
  await page.goto("/en/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

async function apiToken(request: APIRequestContext, username: string, password: string) {
  const res = await request.post(`${API}/api/v1/auth/login`, {
    data: { username, password },
  });
  expect(res.status()).toBe(200);
  return (await res.json()).access_token as string;
}

interface Lot {
  id: number;
  product_id: number;
  product_name: string | null;
  status: string;
  quantity_on_hand: number;
}

/**
 * Every in-storage lot, across all pages.
 *
 * `GET /inventory` applies no ORDER BY (`inventory_service._build_lot_query`), so a single page
 * is not a stable window onto the data — the spec must read the whole set rather than assume the
 * first page contains the lot FIFO will pick.
 */
async function allLots(request: APIRequestContext, token: string): Promise<Lot[]> {
  const headers = { Authorization: `Bearer ${token}` };
  const collected = new Map<number, Lot>();
  let page = 1;
  let total = Infinity;

  while (collected.size < total && page < 20) {
    const res = await request.get(`${API}/api/v1/inventory?page=${page}&page_size=100`, {
      headers,
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    total = body.total;
    for (const lot of body.results as Lot[]) collected.set(lot.id, lot);
    if ((body.results as Lot[]).length === 0) break;
    page += 1;
  }
  return [...collected.values()];
}

const inStorageTotal = (lots: Lot[], productId: number) =>
  lots
    .filter((l) => l.product_id === productId && l.status === "in_storage")
    .reduce((sum, l) => sum + l.quantity_on_hand, 0);

/** A product with enough stock on hand to absorb the close. */
function pickProduct(lots: Lot[]) {
  const byProduct = new Map<number, number>();
  for (const l of lots) {
    if (l.status !== "in_storage" || !l.product_id) continue;
    byProduct.set(l.product_id, (byProduct.get(l.product_id) ?? 0) + l.quantity_on_hand);
  }
  const productId = [...byProduct.entries()]
    .filter(([, total]) => total > CONSUMED * 3)
    .sort((a, b) => a[0] - b[0])[0]?.[0];
  expect(productId, "seed data must contain a product with stock").toBeTruthy();
  return productId as number;
}

async function createWorksheet(request: APIRequestContext, token: string, productId: number) {
  const res = await request.post(`${API}/api/v1/production-worksheets`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      production_line: "LINE-1",
      scheduled_date: "2026-07-23",
      lines: [{ product_id: productId, planned_quantity: PLANNED }],
    },
  });
  expect(res.status()).toBe(201);
  return await res.json();
}

async function closeWorksheet(
  request: APIRequestContext,
  token: string,
  worksheetId: number,
  lineId: number,
  expectedVersion: number,
) {
  return await request.post(
    `${API}/api/v1/production-worksheets/${worksheetId}/close`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        expected_version: expectedVersion,
        lines: [{ line_id: lineId, actual_quantity: CONSUMED }],
      },
    },
  );
}

/** Read one lot's displayed on-hand off the inventory page. */
async function displayedQuantity(page: Page, lot: Lot) {
  await page.goto("/en/inventory");
  await expect(page.getByTestId("inventory-table")).toBeVisible();

  if (lot.product_name) {
    await page.getByTestId("search-input").fill(lot.product_name);
  }
  const row = page.getByTestId(`row-${lot.id}`);
  await expect(row).toBeVisible();
  return (await row.locator("td").nth(3).innerText()).trim();
}

test.describe("ACR-30 worksheet close moves stock exactly once", () => {
  test("closing decrements stock in the UI; a stale re-close changes nothing", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, ADMIN.username, ADMIN.password);
    const lotsBefore = await allLots(request, token);
    const productId = pickProduct(lotsBefore);
    const totalBefore = inStorageTotal(lotsBefore, productId);

    await login(page, ADMIN.username, ADMIN.password);

    // ── close the worksheet ──────────────────────────────────────────────────
    const ws = await createWorksheet(request, token, productId);
    expect(ws.status).toBe("draft");
    expect(ws.version).toBe(0);

    const closed = await closeWorksheet(request, token, ws.id, ws.lines[0].id, 0);
    expect(closed.status()).toBe(200);
    const closedBody = await closed.json();
    expect(closedBody.status).toBe("closed");
    expect(closedBody.version).toBe(1);
    expect(closedBody.lines[0].actual_quantity).toBe(CONSUMED);

    // ── the ledger moved by exactly the consumed amount, once ────────────────
    const lotsAfter = await allLots(request, token);
    expect(inStorageTotal(lotsAfter, productId)).toBe(totalBefore - CONSUMED);

    // ── and the operator can see it: every lot the close touched now renders
    //    its new value on the inventory page ─────────────────────────────────
    const byId = new Map(lotsBefore.map((l) => [l.id, l]));
    const touched = lotsAfter.filter(
      (l) => byId.get(l.id) && byId.get(l.id)!.quantity_on_hand !== l.quantity_on_hand,
    );
    expect(touched.length, "the close must have moved at least one lot").toBeGreaterThan(0);

    for (const lot of touched) {
      expect(await displayedQuantity(page, lot)).toContain(toDisplay(lot.quantity_on_hand));
    }

    // ── a stale re-close is refused and moves nothing ────────────────────────
    const replay = await closeWorksheet(request, token, ws.id, ws.lines[0].id, 0);
    expect(replay.status()).toBe(409);
    expect((await replay.json()).detail).toMatch(/already closed|modified by another/i);

    const lotsReplay = await allLots(request, token);
    expect(inStorageTotal(lotsReplay, productId)).toBe(totalBefore - CONSUMED);
  });

  test("N parallel closes of one worksheet produce exactly one winner", async ({ request }) => {
    const token = await apiToken(request, ADMIN.username, ADMIN.password);
    const lotsBefore = await allLots(request, token);
    const productId = pickProduct(lotsBefore);
    const totalBefore = inStorageTotal(lotsBefore, productId);

    const ws = await createWorksheet(request, token, productId);

    // Fire them together — this is TC-02's shape, over HTTP rather than in-process.
    const responses = await Promise.all(
      Array.from({ length: 8 }, () =>
        closeWorksheet(request, token, ws.id, ws.lines[0].id, 0),
      ),
    );
    const codes = responses.map((r) => r.status());

    expect(codes.filter((c) => c === 200)).toHaveLength(1);
    expect(codes.filter((c) => c === 409)).toHaveLength(7);
    expect(codes.some((c) => c >= 500)).toBe(false);

    // Stock moved once, not eight times.
    const lotsAfter = await allLots(request, token);
    expect(inStorageTotal(lotsAfter, productId)).toBe(totalBefore - CONSUMED);
  });

  test("a machine operator is blocked at the API, not merely hidden in the UI", async ({
    request,
  }) => {
    const token = await apiToken(request, OPERATOR.username, OPERATOR.password);

    const create = await request.post(`${API}/api/v1/production-worksheets`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { lines: [{ product_id: 1, planned_quantity: 100 }] },
    });
    expect(create.status()).toBe(403);

    const view = await request.get(`${API}/api/v1/production-worksheets/1`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(view.status()).toBe(403);
  });
});
