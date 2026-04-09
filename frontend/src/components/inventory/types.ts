export interface InventoryItem {
  id: number;
  material_name: string;
  category: string;
  lot_batch_number: string;
  quantity: number;
  unit: string;
  is_triggered: boolean;
  received_date: string;
}

export interface InventoryResponse {
  items: InventoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface FilterState {
  category: string;
  search: string;
  dateFrom: string;
  dateTo: string;
}

export const DEFAULT_FILTERS: FilterState = {
  category: "",
  search: "",
  dateFrom: "",
  dateTo: "",
};

export function filtersToParams(filters: FilterState): URLSearchParams {
  const p = new URLSearchParams();
  if (filters.category) p.set("category", filters.category);
  if (filters.search) p.set("search", filters.search);
  if (filters.dateFrom) p.set("date_from", filters.dateFrom);
  if (filters.dateTo) p.set("date_to", filters.dateTo);
  return p;
}

export interface TraceabilityData {
  lot_batch_number: string;
  source_delivery: {
    id: number;
    supplier: string;
    received_date: string;
    received_by: string;
  } | null;
  inventory_item: {
    id: number;
    material_name: string;
    quantity: number;
    unit: string;
  } | null;
  work_orders_consumed: Array<{
    id: number;
    title: string;
    quantity_used: number;
    completed_at: string | null;
  }>;
}
