"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { DataTable } from "@/src/components/layout/DataTable";
import { InventoryItem } from "./types";

interface InventoryTableProps {
  items: InventoryItem[];
  isAdmin: boolean;
  onRowClick: (item: InventoryItem) => void;
  onAdjust: (item: InventoryItem) => void;
}

const BASE_COLUMNS = ["Material", "Category", "Lot / Batch", "Quantity", "Location"];

export function InventoryTable({
  items,
  isAdmin,
  onRowClick,
  onAdjust,
}: InventoryTableProps) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4" data-testid="empty-state">
        No inventory items found.
      </p>
    );
  }

  const columns = isAdmin ? [...BASE_COLUMNS, "Actions"] : BASE_COLUMNS;

  return (
    <DataTable columns={columns} data-testid="inventory-table">
      {items.map((item) => (
        <TableRow
          key={item.id}
          className="cursor-pointer"
          onClick={() => onRowClick(item)}
          data-testid={`row-${item.id}`}
        >
          <TableCell className="px-4 py-3 font-medium">{item.item_name}</TableCell>
          <TableCell className="px-4 py-3 capitalize">{item.category}</TableCell>
          <TableCell className="px-4 py-3 font-mono text-xs">{item.lot_batch_number}</TableCell>
          <TableCell className="px-4 py-3">
            <span className="inline-flex items-center gap-2">
              {item.quantity_on_hand}
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
          <TableCell className="px-4 py-3">{item.storage_location}</TableCell>
          {isAdmin && (
            <TableCell
              className="px-4 py-3"
              onClick={(e) => e.stopPropagation()}
            >
              <Button
                size="sm"
                variant="outline"
                onClick={() => onAdjust(item)}
                data-testid={`adjust-btn-${item.id}`}
              >
                Adjust
              </Button>
            </TableCell>
          )}
        </TableRow>
      ))}
    </DataTable>
  );
}
