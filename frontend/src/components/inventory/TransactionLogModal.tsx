"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { apiClient } from "@/src/lib/api-client";
import { toDisplay } from "@/src/lib/qty";
import { InventoryTransaction } from "./types";

const TYPE_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  receive: "default",
  ship: "destructive",
  adjust: "secondary",
  move: "outline",
  split: "outline",
  produce: "default",
  consume: "destructive",
};

interface TransactionLogModalProps {
  lotId: number | null;
  onClose: () => void;
}

export function TransactionLogModal({ lotId, onClose }: TransactionLogModalProps) {
  const open = lotId !== null;

  const { data, isLoading } = useQuery<InventoryTransaction[]>({
    queryKey: ["transactions", lotId],
    queryFn: async () => {
      if (!lotId) throw new Error("No lot selected");
      const res = await apiClient.get<InventoryTransaction[]>(
        `/inventory/lots/${lotId}/transactions`
      );
      return res.data;
    },
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Transaction Log — Lot #{lotId}</DialogTitle>
          <DialogDescription>
            Full audit trail of quantity changes for this lot.
          </DialogDescription>
        </DialogHeader>

        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-3/4" />
          </div>
        )}

        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">No transactions recorded.</p>
        )}

        {data && data.length > 0 && (
          <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
            {data.map((txn) => (
              <div key={txn.id} className="flex items-start gap-3 rounded-md border p-3 text-sm">
                <Badge variant={TYPE_VARIANT[txn.transaction_type] ?? "outline"} className="shrink-0 capitalize">
                  {txn.transaction_type}
                </Badge>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className={txn.quantity >= 0 ? "text-green-500" : "text-destructive"}>
                      {txn.quantity >= 0 ? "+" : ""}
                      {toDisplay(txn.quantity)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(txn.created_at).toLocaleString()}
                    </span>
                  </div>
                  {txn.reason && (
                    <p className="text-muted-foreground truncate">{txn.reason}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
