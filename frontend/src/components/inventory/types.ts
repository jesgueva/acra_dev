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
