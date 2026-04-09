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
      if (!lotBatchNumber) throw new Error("No lot selected");
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
                <p>Carrier: {data.source_delivery.carrier}</p>
                <p>Delivered: {data.source_delivery.delivery_date}</p>
                <p>BOL: {data.source_delivery.bol_reference}</p>
              </section>
            )}

            {data.inventory_items.length > 0 && (
              <section>
                <h3 className="font-semibold mb-1">Current Stock</h3>
                <ul className="space-y-1">
                  {data.inventory_items.map((item) => (
                    <li key={item.id}>
                      {item.material_type}: {item.quantity_on_hand} at {item.storage_location}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3 className="font-semibold mb-1">Linked Work Orders</h3>
              {data.work_orders.length === 0 ? (
                <p className="text-muted-foreground">None</p>
              ) : (
                <ul className="space-y-1">
                  {data.work_orders.map((wo) => (
                    <li key={wo.work_order_id}>
                      {wo.product} — {wo.status}
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
