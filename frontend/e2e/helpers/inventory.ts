import { expect, type APIRequestContext } from "@playwright/test";
import { API, authHeaders } from "./auth";

/**
 * Inventory read helpers.
 *
 * These exist so specs can compute *expected* stock values from live data instead of hard-coding
 * them. The seeded database is not reset between runs and the flows here move stock, so any literal
 * quantity in a spec is a time bomb.
 */

export interface Lot {
  id: number;
  product_id: number | null;
  product_name: string | null;
  lot_number: string | null;
  storage_location: string | null;
  status: string;
  quantity_on_hand: number;
  is_triggered: boolean;
}

/**
 * Every lot, across all pages.
 *
 * `GET /inventory` applies no `ORDER BY` — see `_build_lot_query` in
 * `backend/app/services/inventory_service.py` — so page 1 is not a stable window onto the data and
 * two calls can legitimately return different rows. Anything that reasons about a specific lot has
 * to read the whole set.
 */
export async function allLots(
  request: APIRequestContext,
  token: string,
): Promise<Lot[]> {
  const collected = new Map<number, Lot>();
  let page = 1;
  let total = Infinity;

  while (collected.size < total && page < 20) {
    const res = await request.get(`${API}/api/v1/inventory?page=${page}&page_size=100`, {
      headers: authHeaders(token),
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    total = body.total;
    const results = body.results as Lot[];
    if (results.length === 0) break;
    for (const lot of results) collected.set(lot.id, lot);
    page += 1;
  }

  return [...collected.values()];
}

/** Total on-hand for one product across every in-storage lot. */
export function inStorageTotal(lots: Lot[], productId: number): number {
  return lots
    .filter((l) => l.product_id === productId && l.status === "in_storage")
    .reduce((sum, l) => sum + l.quantity_on_hand, 0);
}

/** The lots whose on-hand differs between two reads, i.e. the ones an action actually moved. */
export function movedLots(before: Lot[], after: Lot[]): Lot[] {
  const byId = new Map(before.map((l) => [l.id, l]));
  return after.filter((l) => {
    const previous = byId.get(l.id);
    return previous !== undefined && previous.quantity_on_hand !== l.quantity_on_hand;
  });
}
