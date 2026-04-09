"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/src/lib/api-client";
import { TraceabilityData } from "./types";

interface TraceabilityViewProps {
  lotBatchNumber: string | null;
  onClose: () => void;
}

export function TraceabilityView({ lotBatchNumber, onClose }: TraceabilityViewProps) {
  const open = lotBatchNumber !== null;

  const { data, isLoading } = useQuery<TraceabilityData>({
    queryKey: ["traceability", lotBatchNumber],
    queryFn: async () => {
      const res = await apiClient.get<TraceabilityData>(
        `/inventory/trace/${lotBatchNumber}`
      );
      return res.data;
    },
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent data-testid="traceability-dialog">
        <DialogHeader>
          <DialogTitle>Traceability — {lotBatchNumber}</DialogTitle>
          <DialogDescription>
            Source delivery, current stock, and work order consumption for this lot.
          </DialogDescription>
        </DialogHeader>

        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

        {data && (
          <div className="space-y-4 text-sm">
            {data.source_delivery && (
              <section>
                <h3 className="font-semibold mb-1">Source Delivery</h3>
                <p>Supplier: {data.source_delivery.supplier}</p>
                <p>Received: {data.source_delivery.received_date}</p>
                <p>By: {data.source_delivery.received_by}</p>
              </section>
            )}

            {data.inventory_item && (
              <section>
                <h3 className="font-semibold mb-1">Current Stock</h3>
                <p>
                  {data.inventory_item.material_name}: {data.inventory_item.quantity}{" "}
                  {data.inventory_item.unit}
                </p>
              </section>
            )}

            <section>
              <h3 className="font-semibold mb-1">Work Orders Consumed</h3>
              {data.work_orders_consumed.length === 0 ? (
                <p className="text-muted-foreground">None</p>
              ) : (
                <ul className="space-y-1">
                  {data.work_orders_consumed.map((wo) => (
                    <li key={wo.id}>
                      {wo.title} — {wo.quantity_used} units
                      {wo.completed_at && ` (completed ${wo.completed_at})`}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
