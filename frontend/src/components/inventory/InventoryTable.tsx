"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { DataTable } from "@/src/components/layout/DataTable";
import { InventoryLot } from "./types";
import { InventoryQuantityDisplay } from "./InventoryQuantityDisplay";
import { STATUS_VARIANT } from "./inventoryLabels";

interface InventoryTableProps {
  items: InventoryLot[];
  isAdmin: boolean;
  onRowClick: (item: InventoryLot) => void;
  onAdjust: (item: InventoryLot) => void;
  onEditLocation: (item: InventoryLot) => void;
  onSplit: (item: InventoryLot) => void;
  onViewLog: (item: InventoryLot) => void;
}

export function InventoryTable({
  items,
  isAdmin,
  onRowClick,
  onAdjust,
  onEditLocation,
  onSplit,
  onViewLog,
}: InventoryTableProps) {
  const t = useTranslations("inventory");

  const columns = useMemo(() => {
    const base = [
      t("columnProduct"),
      t("columnLot"),
      t("columnStatus"),
      t("columnQuantity"),
      t("columnLocation"),
    ];
    return isAdmin ? [...base, t("columnActions")] : base;
  }, [isAdmin, t]);

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
    <DataTable
      columns={columns}
      isEmpty={items.length === 0}
      emptyMessage={t("emptyTable")}
      data-testid="inventory-table"
    >
      {items.map((item) => (
        <TableRow
          key={item.id}
          className="cursor-pointer"
          onClick={() => onRowClick(item)}
          data-testid={`row-${item.id}`}
        >
          <TableCell className="px-4 py-3 font-medium">
            {item.product_name ??
              t("productNumber", { id: item.product_id ?? 0 })}
          </TableCell>
          <TableCell className="px-4 py-3 font-mono text-xs">
            {item.lot_number ?? "—"}
          </TableCell>
          <TableCell className="px-4 py-3">
            <Badge
              variant={STATUS_VARIANT[item.status] ?? "outline"}
              data-testid={`status-badge-${item.id}`}
            >
              {statusLabel(item.status)}
            </Badge>
          </TableCell>
          <TableCell className="px-4 py-3">
            <InventoryQuantityDisplay
              quantityOnHand={item.quantity_on_hand}
              isTriggered={item.is_triggered}
              lowStockBadgeTestId={`low-stock-badge-${item.id}`}
            />
          </TableCell>
          <TableCell className="px-4 py-3">
            {item.storage_location ?? <span className="text-muted-foreground">—</span>}
          </TableCell>
          {isAdmin && (
            <TableCell
              className="px-4 py-3"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex gap-1 flex-wrap">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAdjust(item)}
                  data-testid={`adjust-btn-${item.id}`}
                >
                  {t("adjust")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onEditLocation(item)}
                  data-testid={`location-btn-${item.id}`}
                >
                  {t("location")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onSplit(item)}
                  data-testid={`split-btn-${item.id}`}
                >
                  {t("split")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onViewLog(item)}
                  data-testid={`log-btn-${item.id}`}
                >
                  {t("log")}
                </Button>
              </div>
            </TableCell>
          )}
        </TableRow>
      ))}
    </DataTable>
  );
}
