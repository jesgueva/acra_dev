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
