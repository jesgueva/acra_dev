"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InventoryItem } from "./types";

interface InventoryTableProps {
  items: InventoryItem[];
  isAdmin: boolean;
  onRowClick: (item: InventoryItem) => void;
  onAdjust: (item: InventoryItem) => void;
}

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

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm" data-testid="inventory-table">
        <thead className="bg-muted/50">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Material</th>
            <th className="px-4 py-3 text-left font-medium">Category</th>
            <th className="px-4 py-3 text-left font-medium">Lot / Batch</th>
            <th className="px-4 py-3 text-left font-medium">Quantity</th>
            <th className="px-4 py-3 text-left font-medium">Received</th>
            {isAdmin && <th className="px-4 py-3 text-left font-medium">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              className="border-t hover:bg-muted/30 cursor-pointer"
              onClick={() => onRowClick(item)}
              data-testid={`row-${item.id}`}
            >
              <td className="px-4 py-3 font-medium">{item.material_name}</td>
              <td className="px-4 py-3 capitalize">{item.category}</td>
              <td className="px-4 py-3 font-mono text-xs">{item.lot_batch_number}</td>
              <td className="px-4 py-3">
                <span className="inline-flex items-center gap-2">
                  {item.quantity} {item.unit}
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
              </td>
              <td className="px-4 py-3">{item.received_date}</td>
              {isAdmin && (
                <td
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
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
