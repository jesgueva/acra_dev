"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { InventoryLot } from "./types";
import { InventoryQuantityDisplay } from "./InventoryQuantityDisplay";
import { STATUS_VARIANT } from "./inventoryLabels";

interface InventoryDetailsModalProps {
  item: InventoryLot | null;
  onClose: () => void;
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-1 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function InventoryDetailsModal({ item, onClose }: InventoryDetailsModalProps) {
  const t = useTranslations("inventory");
  const open = item !== null;

  const statusLabel = (status: string) => {
    const labels: Record<string, string> = {
      in_storage: t("status.in_storage"),
      in_production: t("status.in_production"),
      shipped: t("status.shipped"),
      consumed: t("status.consumed"),
    };
    return labels[status] ?? status;
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent data-testid="inventory-details-dialog">
        <DialogHeader>
          <DialogTitle>
            {item
              ? (item.product_name ??
                  t("productNumber", { id: item.product_id ?? 0 }))
              : t("detailsTitle")}
          </DialogTitle>
          <DialogDescription>
            {item?.lot_number
              ? t("lotLabel", { lot: item.lot_number })
              : t("detailsReadOnly")}
          </DialogDescription>
        </DialogHeader>

        {item && (
          <dl className="space-y-3">
            <DetailRow
              label={t("detailLot")}
              value={
                <span className="font-mono text-xs">{item.lot_number ?? "—"}</span>
              }
            />
            <DetailRow
              label={t("detailStatus")}
              value={
                <Badge variant={STATUS_VARIANT[item.status] ?? "outline"}>
                  {statusLabel(item.status)}
                </Badge>
              }
            />
            <DetailRow
              label={t("detailQuantity")}
              value={
                <InventoryQuantityDisplay
                  quantityOnHand={item.quantity_on_hand}
                  isTriggered={item.is_triggered}
                />
              }
            />
            <DetailRow
              label={t("detailLocation")}
              value={item.storage_location ?? <span className="text-muted-foreground">—</span>}
            />
            <DetailRow
              label={t("detailProductId")}
              value={item.product_id ?? <span className="text-muted-foreground">—</span>}
            />
            <DetailRow
              label={t("detailLotId")}
              value={item.id}
            />
            <DetailRow
              label={t("detailSourceDelivery")}
              value={
                item.source_delivery_item_id ?? (
                  <span className="text-muted-foreground">—</span>
                )
              }
            />
            <DetailRow
              label={t("detailPallet")}
              value={
                item.pallet_number ?? <span className="text-muted-foreground">—</span>
              }
            />
          </dl>
        )}
      </DialogContent>
    </Dialog>
  );
}
