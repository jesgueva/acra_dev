"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { DataTable } from "@/src/components/layout/DataTable";
import { toDisplay } from "@/src/lib/qty";
import { InventoryLot } from "./types";

interface InventoryTableProps {
  items: InventoryLot[];
  isAdmin: boolean;
  onRowClick: (item: InventoryLot) => void;
  onAdjust: (item: InventoryLot) => void;
  onEditLocation: (item: InventoryLot) => void;
  onSplit: (item: InventoryLot) => void;
  onViewLog: (item: InventoryLot) => void;
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  in_storage: "default",
  in_production: "secondary",
  shipped: "outline",
  consumed: "outline",
};

const STATUS_LABEL: Record<string, string> = {
  in_storage: "In Storage",
  in_production: "In Production",
  shipped: "Shipped",
  consumed: "Consumed",
};

const BASE_COLUMNS = ["Product", "Lot #", "Status", "Quantity", "Location"];

export function InventoryTable({
  items,
  isAdmin,
  onRowClick,
  onAdjust,
  onEditLocation,
  onSplit,
  onViewLog,
}: InventoryTableProps) {
  const columns = isAdmin ? [...BASE_COLUMNS, "Actions"] : BASE_COLUMNS;

  return (
    <DataTable
      columns={columns}
      isEmpty={items.length === 0}
      emptyMessage="No inventory lots found."
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
            {item.product_name ?? `Product #${item.product_id}`}
          </TableCell>
          <TableCell className="px-4 py-3 font-mono text-xs">
            {item.lot_number ?? "—"}
          </TableCell>
          <TableCell className="px-4 py-3">
            <Badge
              variant={STATUS_VARIANT[item.status] ?? "outline"}
              data-testid={`status-badge-${item.id}`}
            >
              {STATUS_LABEL[item.status] ?? item.status}
            </Badge>
          </TableCell>
          <TableCell className="px-4 py-3">
            <span className="inline-flex items-center gap-2">
              {toDisplay(item.quantity_on_hand)}
              {item.is_triggered && (
                <Badge
                  variant="destructive"
                  className="text-xs"
                  data-testid={`low-stock-badge-${item.id}`}
                >
                  Low Stock
                </Badge>
              )}
            </span>
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
                  Adjust
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onEditLocation(item)}
                  data-testid={`location-btn-${item.id}`}
                >
                  Location
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onSplit(item)}
                  data-testid={`split-btn-${item.id}`}
                >
                  Split
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onViewLog(item)}
                  data-testid={`log-btn-${item.id}`}
                >
                  Log
                </Button>
              </div>
            </TableCell>
          )}
        </TableRow>
      ))}
    </DataTable>
  );
}
