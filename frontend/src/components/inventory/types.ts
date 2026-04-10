export interface InventoryItem {
  id: number;
  item_name: string;
  category: string;
  lot_batch_number: string | null;
  quantity_on_hand: number;
  storage_location: string | null;
  last_updated: string;
  is_triggered: boolean;
}

export interface InventoryListResponse {
  results: InventoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface FilterState {
  category: string;
  itemName: string;
  storageLocation: string;
  dateFrom: string;
  dateTo: string;
}

export const DEFAULT_FILTERS: FilterState = {
  category: "",
  itemName: "",
  storageLocation: "",
  dateFrom: "",
  dateTo: "",
};

export function filtersToParams(filters: FilterState): URLSearchParams {
  const p = new URLSearchParams();
  if (filters.category) p.set("category", filters.category);
  if (filters.itemName) p.set("item_name", filters.itemName);
  if (filters.storageLocation) p.set("storage_location", filters.storageLocation);
  return p;
}

function toComparableDate(value: string) {
  return new Date(value).toISOString().slice(0, 10);
}

export function filterItemsByDateRange(
  items: InventoryItem[],
  dateFrom: string,
  dateTo: string
) {
  return items.filter((item) => {
    const itemDate = toComparableDate(item.last_updated);

    if (dateFrom && itemDate < dateFrom) {
      return false;
    }

    if (dateTo && itemDate > dateTo) {
      return false;
    }

    return true;
  });
}

export interface TraceabilityData {
  lot_batch_number: string;
  source_delivery: {
    delivery_id: number;
    supplier: string;
    carrier: string;
    delivery_date: string;
    bol_reference: string;
  } | null;
  inventory_items: Array<{
    id: number;
    item_name: string;
    category: string;
    quantity_on_hand: number;
    storage_location: string | null;
  }>;
  work_orders: Array<{
    work_order_id: number;
    product: string;
    status: string;
  }>;
}
