export const STATUS_LABELS: Record<string, string> = {
  created: "Created",
  materials_allocated: "Materials Allocated",
  in_production: "In Production",
  completed: "Completed",
  ready_for_shipment: "Ready for Shipment",
};

export const STATUS_BADGE_VARIANTS: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  created: "outline",
  materials_allocated: "secondary",
  in_production: "default",
  completed: "secondary",
  ready_for_shipment: "default",
};
