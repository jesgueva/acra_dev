export type WorkOrderStatus =
  | "created"
  | "materials_allocated"
  | "in_production"
  | "completed"
  | "ready_for_shipment";

export type WorkOrderPriority = "low" | "medium" | "high" | "urgent";

export interface WorkOrderMaterial {
  id: number;
  material_type: string;
  quantity_required: number;
  quantity_allocated: number;
}

export interface WorkOrder {
  id: number;
  wo_number: string;
  product: string;
  status: WorkOrderStatus;
  priority: WorkOrderPriority;
  display_sequence: number;
  production_line?: string | null;
  target_date: string;
  quantity_required: number;
  quantity_produced: number;
  created_by: number;
  created_at: string;
  updated_at: string;
  materials: WorkOrderMaterial[];
}

export interface WorkOrderListResponse {
  total: number;
  page: number;
  page_size: number;
  results: WorkOrder[];
}

export interface MaterialAvailability {
  material_type: string;
  required: number;
  available: number;
  sufficient: boolean;
}

export interface WorkOrderCreateResponse {
  id: number;
  wo_number: string;
  status: string;
  material_availability: MaterialAvailability[];
}
