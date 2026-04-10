export interface InventoryLot {
  id: number;
  product_id: number | null;
  product_name: string | null;
  lot_number: string | null;
  storage_location: string | null;
  status: string;
  quantity_on_hand: number;   // integer ×100
  source_delivery_item_id: number | null;
  pallet_number: number | null;
  is_triggered: boolean;
}

/** @deprecated Use InventoryLot */
export type InventoryItem = InventoryLot;

export interface InventoryListResponse {
  results: InventoryLot[];
  total: number;
  page: number;
  page_size: number;
}

export interface InventoryTransaction {
  id: number;
  lot_id: number;
  transaction_type: string;
  quantity: number;           // integer ×100
  reference_type: string | null;
  reference_id: number | null;
  reason: string | null;
  created_by: number | null;
  created_at: string;
}

export interface FilterState {
  status: string;
  search: string;
}

export const DEFAULT_FILTERS: FilterState = {
  status: "",
  search: "",
};

export function filtersToParams(filters: FilterState, page?: number, pageSize?: number): URLSearchParams {
  const p = new URLSearchParams();
  if (filters.status) p.set("status", filters.status);
  if (filters.search) p.set("search", filters.search);
  if (page != null) p.set("page", String(page));
  if (pageSize != null) p.set("page_size", String(pageSize));
  return p;
}

export interface TraceabilityData {
  lot_number: string;
  source_delivery: {
    delivery_id: number;
    contact_id: number | null;
    carrier_id: number | null;
    delivery_date: string;
    bol_reference: string;
  } | null;
  lots: Array<{
    id: number;
    product_id: number | null;
    product_name: string | null;
    status: string;
    quantity_on_hand: number;
    storage_location: string | null;
  }>;
  work_orders: Array<{
    work_order_id: number;
    product: string;
    status: string;
  }>;
}
