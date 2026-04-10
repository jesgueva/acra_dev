"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { apiClient } from "@/src/lib/api-client";
import { toDisplay } from "@/src/lib/qty";
import { TraceabilityData } from "./types";

interface TraceabilityViewProps {
  lotNumber: string | null;
  onClose: () => void;
}

export function TraceabilityView({ lotNumber, onClose }: TraceabilityViewProps) {
  const open = lotNumber !== null;

  const { data, isLoading } = useQuery<TraceabilityData>({
    queryKey: ["traceability", lotNumber],
    queryFn: async () => {
      if (!lotNumber) throw new Error("No lot selected");
      const res = await apiClient.get<TraceabilityData>(
        `/inventory/trace/${lotNumber}`
      );
      return res.data;
    },
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent data-testid="traceability-dialog">
        <DialogHeader>
          <DialogTitle>Traceability — {lotNumber}</DialogTitle>
          <DialogDescription>
            Source delivery, current stock, and work order consumption for this lot.
          </DialogDescription>
        </DialogHeader>

        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        )}

        {data && (
          <div className="space-y-4 text-sm">
            {data.source_delivery && (
              <section>
                <h3 className="font-semibold mb-1">Source Delivery</h3>
                <p>Delivery ID: {data.source_delivery.delivery_id}</p>
                <p>Delivered: {data.source_delivery.delivery_date}</p>
                <p>BOL: {data.source_delivery.bol_reference}</p>
              </section>
            )}

            {data.lots.length > 0 && (
              <section>
                <h3 className="font-semibold mb-1">Current Stock</h3>
                <ul className="space-y-1">
                  {data.lots.map((lot) => (
                    <li key={lot.id}>
                      {lot.product_name ?? `Product #${lot.product_id}`}:{" "}
                      {toDisplay(lot.quantity_on_hand)} at {lot.storage_location ?? "—"}{" "}
                      <span className="text-muted-foreground">({lot.status})</span>
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
