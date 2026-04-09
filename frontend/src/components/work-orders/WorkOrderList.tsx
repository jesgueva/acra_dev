"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { WorkOrder } from "./types";

const STATUS_LABELS: Record<string, string> = {
  created: "Created",
  materials_allocated: "Materials Allocated",
  in_production: "In Production",
  completed: "Completed",
  ready_for_shipment: "Ready for Shipment",
};

const STATUS_BADGE_VARIANTS: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  created: "outline",
  materials_allocated: "secondary",
  in_production: "default",
  completed: "secondary",
  ready_for_shipment: "default",
};

interface WorkOrderRowProps {
  wo: WorkOrder;
  onSelect: (wo: WorkOrder) => void;
}

function WorkOrderRow({ wo, onSelect }: WorkOrderRowProps) {
  return (
    <button
      className="flex w-full items-center justify-between rounded-md border bg-white px-4 py-3 text-left text-sm shadow-sm hover:bg-muted/50"
      onClick={() => onSelect(wo)}
      data-testid={`wo-row-${wo.id}`}
    >
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-muted-foreground">
          {wo.wo_number}
        </span>
        <span className="font-medium">{wo.product}</span>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={STATUS_BADGE_VARIANTS[wo.status] ?? "outline"}>
          {wo.priority}
        </Badge>
        <span className="text-xs text-muted-foreground">{wo.target_date}</span>
      </div>
    </button>
  );
}

interface StatusGroupProps {
  status: string;
  workOrders: WorkOrder[];
  onSelect: (wo: WorkOrder) => void;
}

function StatusGroup({ status, workOrders, onSelect }: StatusGroupProps) {
  const [collapsed, setCollapsed] = useState(false);
  const label = STATUS_LABELS[status] ?? status;

  return (
    <section aria-label={label}>
      <button
        className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground"
        onClick={() => setCollapsed((c) => !c)}
        aria-expanded={!collapsed}
      >
        {collapsed ? (
          <ChevronRight className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
        {label}
        <span className="ml-1 rounded-full bg-muted px-1.5 text-xs font-normal text-muted-foreground">
          {workOrders.length}
        </span>
      </button>
      {!collapsed && (
        <div className="space-y-2">
          {workOrders.map((wo) => (
            <WorkOrderRow key={wo.id} wo={wo} onSelect={onSelect} />
          ))}
          {workOrders.length === 0 && (
            <p className="px-2 text-sm text-muted-foreground">No work orders.</p>
          )}
        </div>
      )}
    </section>
  );
}

interface WorkOrderListProps {
  groups: Record<string, WorkOrder[]>;
  onSelect: (wo: WorkOrder) => void;
}

export function WorkOrderList({ groups, onSelect }: WorkOrderListProps) {
  return (
    <div className="space-y-6">
      {Object.entries(groups).map(([status, workOrders]) => (
        <StatusGroup
          key={status}
          status={status}
          workOrders={workOrders}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
